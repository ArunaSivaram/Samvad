"""
rag.py
Retrieval + grounded LLM answer for the Gita RAG pipeline.

Public API:
    retrieve(question, k=3, chapter=None)      -- just the FAISS/metadata hits
    answer(question, k=3, chapter=None)        -- hits + grounded LLM reply
    direct_answer(question)                    -- LLM reply with NO retrieval (RAG-off)
    load_index()                               -- warms the singletons

answer() and direct_answer() both return:
    {
        "answer":             str  -- the reply text (Claude, or a canned low-confidence message),
        "sources":            list -- the retrieved verses (empty for direct_answer),
        "used_llm":           bool -- whether Claude was called this call,
        "invalid_citations":  list -- (chapter.verse) refs Claude cited that were NOT in sources,
    }

Pipeline (grounded path, answer()):
  1. Route the question:
       - Explicit verse reference ("2.47", "chapter 2 verse 47") -> direct
         metadata lookup, score 1.0.
       - Otherwise -> embed with all-MiniLM-L6-v2 and do a FAISS top-k search.
  2. Confidence check: if the top hit's cosine similarity is below
     SCORE_THRESHOLD, short-circuit with a canned message. We do NOT call
     the LLM -- forcing an answer from weak context is how RAG systems
     end up citing irrelevant verses with false confidence.
  3. LLM answer: send the verses to Claude Sonnet 4.6 with a strict
     "cite only these verses" system prompt. After the call, parse the
     reply for (chapter.verse) citations and check them against the
     retrieved sources -- anything the model cites that wasn't retrieved
     is a hallucination, surfaced as invalid_citations.

Setup: put your Anthropic API key in a .env file next to this script:
    ANTHROPIC_API_KEY=sk-ant-...
"""

import json
import os
import re
import sys
from pathlib import Path
from typing import Any

import anthropic
import faiss
from dotenv import load_dotenv
from sentence_transformers import SentenceTransformer

# ---------- paths and config ----------
PROJECT_DIR = Path(__file__).parent
INDEX_FILE = PROJECT_DIR / "index" / "gita.faiss"
META_FILE = PROJECT_DIR / "index" / "meta.json"
SANSKRIT_FILE = PROJECT_DIR / "data" / "gita_sanskrit.json"

EMBEDDING_MODEL = "all-MiniLM-L6-v2"
LLM_MODEL = "claude-sonnet-4-6"
LLM_MAX_TOKENS = 1024

# Minimum top-hit cosine similarity to even try calling the LLM. Below this,
# retrieval is essentially guessing (see the "I'm anxious about my exam
# results" case -- all top hits scored 0.18-0.21 and were tangential at best).
SCORE_THRESHOLD = 0.3


# ---------- cached singletons ----------
_embedder: SentenceTransformer | None = None
_index: faiss.Index | None = None
_meta: list[dict] | None = None
_sanskrit: dict[str, dict] | None = None
_llm: anthropic.Anthropic | None = None


def _load_sanskrit() -> dict[str, dict]:
    """Load (and cache) Devanagari + IAST per verse, keyed by "chapter.verse"."""
    global _sanskrit
    if _sanskrit is None:
        if SANSKRIT_FILE.exists():
            _sanskrit = json.loads(SANSKRIT_FILE.read_text(encoding="utf-8"))
        else:
            _sanskrit = {}
    return _sanskrit


def _enrich(record: dict, score: float) -> dict:
    """Build a result dict with Sanskrit + Besant fields for one verse."""
    key = f"{record['chapter']}.{record['verse']}"
    sanskrit = _load_sanskrit().get(key, {})
    return {
        "chapter": record["chapter"],
        "chapter_title": record["chapter_title"],
        "verse": record["verse"],
        "speaker": record["speaker"],
        "text": record["text"],
        "devanagari": sanskrit.get("devanagari", ""),
        "iast": sanskrit.get("iast", ""),
        "score": score,
    }


def load_index() -> tuple[SentenceTransformer, faiss.Index, list[dict]]:
    """Load (and cache) the embedding model, FAISS index, and metadata list."""
    global _embedder, _index, _meta
    if _embedder is None:
        _embedder = SentenceTransformer(EMBEDDING_MODEL)
    if _index is None:
        _index = faiss.read_index(str(INDEX_FILE))
    if _meta is None:
        _meta = json.loads(META_FILE.read_text(encoding="utf-8"))
    return _embedder, _index, _meta


def _get_llm() -> anthropic.Anthropic:
    """Load the Anthropic client, reading ANTHROPIC_API_KEY from .env / env."""
    global _llm
    if _llm is None:
        load_dotenv()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Put it in a .env file next to "
                "rag.py (ANTHROPIC_API_KEY=sk-ant-...) or export it in your shell."
            )
        _llm = anthropic.Anthropic()
    return _llm


# ---------- metadata router (Option A: explicit verse references) ----------
_VERSE_REF_PATTERNS = [
    re.compile(r"\bchapter\s+(\d{1,2})[,\s]+verse\s+(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\bverse\s+(\d{1,2})\.(\d{1,3})\b", re.IGNORECASE),
    re.compile(r"\b(\d{1,2})\.(\d{1,3})\b"),
]


def _parse_verse_reference(question: str) -> tuple[int, str] | None:
    """Return (chapter, verse_string) if the question names a verse, else None."""
    for pattern in _VERSE_REF_PATTERNS:
        match = pattern.search(question)
        if match:
            chapter = int(match.group(1))
            verse = match.group(2)
            if 1 <= chapter <= 18:  # Gita has exactly 18 chapters
                return chapter, verse
    return None


def _lookup_verse(chapter: int, verse: str, meta: list[dict]) -> dict | None:
    """Direct scan of meta.json for an exact chapter+verse match."""
    for record in meta:
        if record["chapter"] == chapter and record["verse"] == verse:
            return record
    return None


# ---------- retrieval ----------
def retrieve(
    question: str,
    k: int = 3,
    chapter: int | None = None,
) -> list[dict[str, Any]]:
    """
    Return the top-k most relevant verses. Metadata router first, vector
    search second. See module docstring for routing details.
    """
    embedder, index, meta = load_index()

    # Path 1: metadata router. If the question names a specific verse, return it.
    # (We intentionally ignore the `chapter` filter here -- a direct reference
    # is more specific than a chapter filter, so it wins.)
    ref = _parse_verse_reference(question)
    if ref is not None:
        hit = _lookup_verse(*ref, meta)
        if hit is not None:
            return [_enrich(hit, 1.0)]
        # Parsed ref but verse doesn't exist -- fall through to vector search.

    # Path 2: vector search.
    q_vec = embedder.encode(
        [question], normalize_embeddings=True
    ).astype("float32")

    # When filtering by chapter, pull a bigger pool so we still end up with k
    # hits after filtering. For an unfiltered query we just need k.
    search_k = k * 20 if chapter is not None else k
    search_k = min(search_k, index.ntotal)
    scores, indices = index.search(q_vec, search_k)

    hits: list[dict[str, Any]] = []
    for score, idx in zip(scores[0], indices[0]):
        record = meta[idx]
        if chapter is not None and record["chapter"] != chapter:
            continue
        hits.append(_enrich(record, round(float(score), 2)))
        if len(hits) >= k:
            break
    return hits


# ---------- LLM answer step ----------
SYSTEM_PROMPT = """You are the Gita Study Assistant. You answer questions about the Bhagavad Gita using ONLY the verses provided in the user's message. The verses are from Annie Besant's public-domain English translation.

Voice:
- Write like a thoughtful friend sitting next to the reader, not a textbook. Warm, plain, direct.
- Address the reader as "you" when it fits. Acknowledge the feeling behind the question when there is one.
- Prefer short sentences and ordinary words. If a verse uses old-fashioned language, briefly say what it means in plain English before citing it.

Rules:
- Base every claim on the provided verses. Do not add outside knowledge, commentary from other translators, or interpretation beyond what the verses support.
- Cite every claim inline in the format (chapter.verse), for example (2.47).
- If the provided verses do not answer the question, say so plainly rather than guessing.
- End your reply with a "Sources:" section listing the chapter.verse of each verse you actually used (not every verse provided).
- Do not use em dashes, en dashes, or double hyphens. Use commas, periods, or parentheses instead.
- If the answer has distinct sections, label each section with a Markdown heading on its own line, like "## The ideal: a steady, unattached mind". Do not use "**Section title**" for section labels. You may still use **bold** for emphasis inside a sentence.
- Keep answers concise and faithful to the text."""


DIRECT_SYSTEM_PROMPT = """You are the Gita Study Assistant, running in RAG-off mode. In this mode you have NO access to the Besant translation and NO retrieval has been performed. Answer the user's question about the Bhagavad Gita from your own training knowledge.

Voice:
- Write like a thoughtful friend, not a textbook. Warm, plain, direct.
- Address the reader as "you" when it fits. Acknowledge the feeling behind the question when there is one.

Rules:
- Be concise and clear.
- Do NOT cite specific (chapter.verse) numbers. You cannot verify them in this mode, so citing risks misattribution.
- Describe teachings generally and name people, concepts, or traditions when you are confident.
- Do not use em dashes, en dashes, or double hyphens. Use commas, periods, or parentheses instead.
- If the answer has distinct sections, label each section with a Markdown heading on its own line, like "## Section title". Do not use "**Section title**" for section labels. You may still use **bold** for emphasis inside a sentence."""


# Scrub em/en/double dashes that sometimes slip through despite the prompt
# instruction. Swap them for ", " and collapse the resulting runs so the text
# reads naturally.
_DASH_PATTERN = re.compile(r"\s*(?:—|–|--)\s*")
_MULTI_COMMA_PATTERN = re.compile(r",\s*,+")
_COMMA_BEFORE_PUNCT = re.compile(r",\s*([.!?;:])")

# A line that is entirely "**Heading text**" is being used as a section label.
# Promote it to a real Markdown heading so the frontend renders it as such.
_BOLD_LINE_AS_HEADING = re.compile(r"^[ \t]*\*\*(.+?)\*\*[ \t]*$", re.MULTILINE)


def _strip_dashes(text: str) -> str:
    text = _DASH_PATTERN.sub(", ", text)
    text = _MULTI_COMMA_PATTERN.sub(",", text)
    text = _COMMA_BEFORE_PUNCT.sub(r"\1", text)
    return text


def _normalize_headings(text: str) -> str:
    return _BOLD_LINE_AS_HEADING.sub(r"## \1", text)


# Citations in the model's reply look like "(2.47)" -- the format our system
# prompt tells it to use. We match literal parentheses around digit.digit.
_CITATION_PATTERN = re.compile(r"\((\d+)\.(\d+)\)")


def _find_invalid_citations(answer_text: str, sources: list[dict]) -> list[str]:
    """
    Return any (chapter.verse) citations in answer_text that are NOT present
    in the retrieved sources. These are hallucinated groundings -- the model
    cited a verse it was never shown.
    """
    cited = {f"{m.group(1)}.{m.group(2)}" for m in _CITATION_PATTERN.finditer(answer_text)}
    valid = {f"{s['chapter']}.{s['verse']}" for s in sources}
    return sorted(cited - valid)


def _format_verses_for_prompt(hits: list[dict]) -> str:
    """Render retrieved verses as a readable block for Claude."""
    return "\n\n".join(
        f"[{h['chapter']}.{h['verse']}] "
        f"(Speaker: {h['speaker']}; Chapter title: {h['chapter_title']})\n"
        f"{h['text']}"
        for h in hits
    )


LOW_CONFIDENCE_REPLY = (
    "I don't see verses in the Gita that directly address this question. "
    "The closest matches had low similarity scores, which usually means "
    "the question is phrased very differently from the text or it covers "
    "material the Gita does not discuss. Try rephrasing, or ask about a "
    "specific chapter or verse."
)


def answer(
    question: str,
    k: int = 3,
    chapter: int | None = None,
) -> dict[str, Any]:
    """Retrieve + grounded LLM answer. See module docstring for return shape."""
    hits = retrieve(question, k=k, chapter=chapter)

    if not hits:
        return {
            "answer": LOW_CONFIDENCE_REPLY,
            "sources": [],
            "used_llm": False,
            "invalid_citations": [],
        }

    # Low-confidence short-circuit -- don't let the LLM confabulate grounding.
    if hits[0]["score"] < SCORE_THRESHOLD:
        return {
            "answer": LOW_CONFIDENCE_REPLY,
            "sources": hits,
            "used_llm": False,
            "invalid_citations": [],
        }

    # Confident enough -- send to Claude.
    user_message = (
        f"Question: {question}\n\n"
        f"Verses retrieved from the Besant translation (most relevant first):\n\n"
        f"{_format_verses_for_prompt(hits)}"
    )
    response = _get_llm().messages.create(
        model=LLM_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )
    answer_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    answer_text = _normalize_headings(_strip_dashes(answer_text))
    return {
        "answer": answer_text,
        "sources": hits,
        "used_llm": True,
        "invalid_citations": _find_invalid_citations(answer_text, hits),
    }


def direct_answer(question: str) -> dict[str, Any]:
    """
    RAG-off mode: send the question straight to Claude, no retrieval.

    Returns the same shape as answer() so the UI can handle both uniformly.
    sources is always empty here, and invalid_citations is always empty
    (we instruct the model not to cite specific verses in this mode).
    """
    response = _get_llm().messages.create(
        model=LLM_MODEL,
        max_tokens=LLM_MAX_TOKENS,
        system=DIRECT_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": question}],
    )
    answer_text = "".join(
        block.text for block in response.content if block.type == "text"
    )
    answer_text = _normalize_headings(_strip_dashes(answer_text))
    return {
        "answer": answer_text,
        "sources": [],
        "used_llm": True,
        "invalid_citations": [],
    }


# ---------- CLI smoke tests ----------
def _print_retrieval(questions: list[str]) -> None:
    for q in questions:
        print(f"\nQ: {q}")
        for h in retrieve(q, k=3):
            snippet = h["text"][:100]
            if len(h["text"]) > 100:
                snippet += "…"
            print(f"  {h['chapter']}.{h['verse']} ({h['score']:.2f}) {snippet}")


def _print_answers(questions: list[str]) -> None:
    for q in questions:
        print(f"\n--- Q: {q}")
        result = answer(q)
        tag = "LLM" if result["used_llm"] else "short-circuit"
        print(f"[{tag}]")
        print(result["answer"])
        if result["invalid_citations"]:
            print(f"!! invalid citations: {result['invalid_citations']}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "retrieval":
        semantic = [
            "doing your duty without attachment to results",
            "the soul is never born and never dies",
            "who speaks the first verse",
            "I'm anxious about my exam results",
        ]
        metadata = ["what does verse 2.47 say", "chapter 11 verse 32"]
        print("=== Semantic (vector) ===")
        _print_retrieval(semantic)
        print("\n=== Metadata (router) ===")
        _print_retrieval(metadata)
    else:
        test_questions = [
            "What does Krishna say about doing one's duty without attachment?",
            "What does verse 2.47 say?",
            "I'm anxious about my exam results.",
        ]
        _print_answers(test_questions)

"""
api.py
FastAPI backend wrapping rag.py.

One POST endpoint, /ask, that mirrors rag.answer() / rag.direct_answer():

Request body (JSON):
    {
      "question":  str,                 # required
      "k":         int (1-8, default 3),
      "chapter":   int | null,          # optional chapter filter, 1-18
      "use_rag":   bool (default true)  # false = RAG-off mode (no retrieval)
    }

Response body (JSON):
    {
      "answer":            str,
      "sources":           [{chapter, chapter_title, verse, speaker, text, score}, ...],
      "used_llm":          bool,
      "invalid_citations": [str, ...]
    }

Run (development):
    uvicorn api:app --reload --port 8000

Then try it from another terminal:
    curl -X POST http://localhost:8000/ask \\
         -H 'Content-Type: application/json' \\
         -d '{"question": "What does verse 2.47 say?"}'
"""

import json
from pathlib import Path
from typing import Iterator, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from rag import (
    DIRECT_SYSTEM_PROMPT,
    LLM_MAX_TOKENS,
    LLM_MODEL,
    LOW_CONFIDENCE_REPLY,
    SCORE_THRESHOLD,
    SYSTEM_PROMPT,
    _find_invalid_citations,
    _format_verses_for_prompt,
    _get_llm,
    _normalize_headings,
    _strip_dashes,
    answer,
    direct_answer,
    load_index,
    retrieve,
)

_SUMMARIES_FILE = Path(__file__).parent / "data" / "chapter_summaries.json"
_chapter_summaries: dict[int, dict] | None = None


def _load_chapter_summaries() -> dict[int, dict]:
    """Load (and cache) the hand-curated per-chapter summary + themes."""
    global _chapter_summaries
    if _chapter_summaries is None:
        raw = json.loads(_SUMMARIES_FILE.read_text(encoding="utf-8"))
        _chapter_summaries = {int(k): v for k, v in raw.items()}
    return _chapter_summaries

app = FastAPI(title="Gita Study Assistant API")

# CORS = "Cross-Origin Resource Sharing". The browser's security model blocks
# JavaScript from calling an API on a different origin (host:port) unless the
# server explicitly allows it. During development our React dev server runs on
# port 5173 and this API runs on 8000 -- different origins -- so we must allow
# 5173 here or the browser will refuse the request with no visible error.
#
# In production, both React and this API are served from the same origin, so
# CORS has no effect. Leaving it configured keeps dev simple.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- request / response models ----------
# Pydantic models describe the shape of JSON that comes in and goes out.
# FastAPI uses them to (a) validate incoming requests (returns a 422 if the
# browser sends something malformed), (b) generate auto-docs at /docs, and
# (c) make the Python side strongly typed.

class AskRequest(BaseModel):
    question: str = Field(..., min_length=1, description="The user's question.")
    k: int = Field(default=3, ge=1, le=8, description="Top-k verses to retrieve.")
    chapter: Optional[int] = Field(
        default=None, ge=1, le=18,
        description="Optional chapter filter (1-18).",
    )
    use_rag: bool = Field(default=True, description="If false, skip retrieval entirely.")


class Source(BaseModel):
    chapter: int
    chapter_title: str
    verse: str
    speaker: str
    text: str
    devanagari: str = ""
    iast: str = ""
    score: float


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]
    used_llm: bool
    invalid_citations: list[str]


class Chapter(BaseModel):
    number: int
    title: str
    summary: str = ""
    themes: list[str] = []


# ---------- endpoints ----------
@app.get("/health")
def health() -> dict[str, str]:
    """
    Trivial ping endpoint. Deployment platforms (Render, Railway, etc.) hit
    this periodically to check the service is up. If this returns anything
    other than 200, they'll restart the container.
    """
    return {"status": "ok"}


@app.get("/chapters", response_model=list[Chapter])
def chapters() -> list[Chapter]:
    """
    Return the 18 Gita chapter numbers, titles, and curated summary + themes.
    Titles come from the indexed metadata; summaries come from the hand-written
    data/chapter_summaries.json.
    """
    _, _, meta = load_index()
    titles: dict[int, str] = {}
    for r in meta:
        titles[r["chapter"]] = r["chapter_title"]
    summaries = _load_chapter_summaries()
    return [
        Chapter(
            number=n,
            title=t,
            summary=summaries.get(n, {}).get("summary", ""),
            themes=summaries.get(n, {}).get("themes", []),
        )
        for n, t in sorted(titles.items())
    ]


@app.post("/ask", response_model=AskResponse)
def ask(req: AskRequest) -> dict:
    """
    Answer a question. Thin wrapper around rag.answer / rag.direct_answer.

    FastAPI auto-validates `req` against AskRequest before this function runs,
    so we can trust the shape at this point.
    """
    try:
        if req.use_rag:
            return answer(req.question, k=req.k, chapter=req.chapter)
        else:
            return direct_answer(req.question)
    except RuntimeError as e:
        # Most commonly: ANTHROPIC_API_KEY not set. Surface as a 500 so the
        # React side can display a useful error message.
        raise HTTPException(status_code=500, detail=str(e))


# ---------- streaming endpoint ----------
# The React UI consumes /ask/stream for a token-by-token "typing" effect.
# Event types emitted as Server-Sent Events:
#   sources  -- retrieved verses, emitted once before any tokens
#   token    -- a single text delta from Claude (may be a few chars to a word)
#   final    -- the full cleaned answer text + invalid_citations + used_llm
#   error    -- any error surfaced to the client (replaces an HTTP error code,
#               since we can't change the HTTP status after the stream begins)

def _sse(obj: dict) -> str:
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


def _stream_ask(req: AskRequest) -> Iterator[str]:
    try:
        if req.use_rag:
            hits = retrieve(req.question, k=req.k, chapter=req.chapter)
            yield _sse({"type": "sources", "sources": hits})

            # Low-confidence short-circuit: stream the canned reply and stop.
            if not hits or hits[0]["score"] < SCORE_THRESHOLD:
                yield _sse({"type": "token", "text": LOW_CONFIDENCE_REPLY})
                yield _sse({
                    "type": "final",
                    "text": LOW_CONFIDENCE_REPLY,
                    "used_llm": False,
                    "invalid_citations": [],
                })
                return

            system_prompt = SYSTEM_PROMPT
            user_message = (
                f"Question: {req.question}\n\n"
                "Verses retrieved from the Besant translation "
                "(most relevant first):\n\n"
                f"{_format_verses_for_prompt(hits)}"
            )
        else:
            hits = []
            yield _sse({"type": "sources", "sources": []})
            system_prompt = DIRECT_SYSTEM_PROMPT
            user_message = req.question

        raw_parts: list[str] = []
        client = _get_llm()
        with client.messages.stream(
            model=LLM_MODEL,
            max_tokens=LLM_MAX_TOKENS,
            system=system_prompt,
            messages=[{"role": "user", "content": user_message}],
        ) as stream:
            for text_chunk in stream.text_stream:
                raw_parts.append(text_chunk)
                yield _sse({"type": "token", "text": text_chunk})

        full_raw = "".join(raw_parts)
        final_text = _normalize_headings(_strip_dashes(full_raw))
        invalid = _find_invalid_citations(final_text, hits) if hits else []
        yield _sse({
            "type": "final",
            "text": final_text,
            "used_llm": True,
            "invalid_citations": invalid,
        })
    except Exception as e:
        # Mid-stream errors can't be an HTTP 500 — the response has already
        # started — so surface them as a dedicated event the UI can show.
        yield _sse({"type": "error", "error": str(e)})


@app.post("/ask/stream")
def ask_stream(req: AskRequest) -> StreamingResponse:
    return StreamingResponse(
        _stream_ask(req),
        media_type="text/event-stream",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )

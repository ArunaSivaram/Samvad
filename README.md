# Gita Study Assistant

A grounded chat app that answers questions about the Bhagavad Gita using Annie Besant's 1895 public-domain English translation. Every answer cites chapter and verse; the system refuses to answer when the retrieved verses don't support a confident response.

Built as a portfolio project to practice retrieval-augmented generation (RAG) end to end: chunking, embeddings, vector search, prompt engineering, confidence thresholds, and — most important — building a measurement harness before shipping.

## Demo

![App screenshot](screenshot.png)

*(Replace this placeholder with a real screenshot of the running app.)*

## How it works

```
User question
     │
     ▼
┌──────────────────────────────────────┐
│ 1. Metadata router                   │
│    Regex for "verse 2.47",           │
│    "chapter 2 verse 47", "2.47"      │
│    → direct lookup in meta.json,     │
│      score = 1.00                    │
└───────────────┬──────────────────────┘
                │ (no verse-ref match)
                ▼
┌──────────────────────────────────────┐
│ 2. Vector search                     │
│    Embed question with MiniLM        │
│    FAISS top-k cosine similarity     │
└───────────────┬──────────────────────┘
                │
                ▼
┌──────────────────────────────────────┐
│ 3. Confidence check                  │
│    Top score < 0.3?                  │
│    → canned "I don't know" reply     │
│      (skip LLM — save tokens         │
│      and prevent hallucination)      │
└───────────────┬──────────────────────┘
                │ (above threshold)
                ▼
┌──────────────────────────────────────┐
│ 4. Grounded LLM answer               │
│    Claude Sonnet 4.6 with strict     │
│    "cite only these verses" system   │
│    prompt. Post-check: verify every  │
│    (X.Y) citation was in the         │
│    retrieved context.                │
└───────────────┬──────────────────────┘
                │
                ▼
          Answer with inline (chapter.verse)
          citations + sources panel
          + invalid-citation warning (if any)
```

## Stack

| Component | Choice | Why |
|---|---|---|
| Corpus | Annie Besant's 1895 Gita (701 verses) | Public domain, English, structurally clean JSON |
| Chunking | One verse per chunk, one-line structural prefix | Verses are short and self-contained; prefix helps chapter-scoped queries |
| Embeddings | `all-MiniLM-L6-v2` (384-dim) | Small (~90 MB), fast on CPU, good enough for short texts |
| Vector store | FAISS `IndexFlatIP` | Exact search; 701 vectors doesn't need approximation |
| LLM | Anthropic Claude Sonnet 4.6 | Strong instruction-following; correctly refuses when grounding is weak |
| UI | Streamlit chat primitives | Fast to build, native `st.chat_message` / `st.chat_input` |

## Setup

Requires Python 3.10+ (tested on 3.12), and an Anthropic API key.

```bash
# 1. Create a virtual environment
python3.12 -m venv .venv
source .venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Build the vector index (one-time; takes ~30s on CPU)
python build_index.py

# 4. Add your API key
echo "ANTHROPIC_API_KEY=sk-ant-..." > .env

# 5. Run the chat app
streamlit run app.py
```

To run the evaluation suite instead:

```bash
python eval.py          # makes ~8 Claude API calls, writes eval_results.md
```

## Repo layout

```
gita-rag/
├── data/gita_besant.json    # source corpus — 701 verses
├── index/gita.faiss         # built by build_index.py
├── index/meta.json          # built by build_index.py (same row order as the vectors)
├── build_index.py           # chunking + embedding + indexing
├── rag.py                   # retrieval + grounded LLM answer (+ RAG-off mode)
├── app.py                   # Streamlit chat UI
├── eval.py                  # fixed-question regression suite
├── eval_results.md          # last eval snapshot (version-controlled)
├── requirements.txt
├── README.md
└── .env                     # your API key (gitignored)
```

## Evaluation

`python eval.py` sends 10 fixed questions through the pipeline and writes a scorecard to `eval_results.md`. First run (2026-11-15):

| Metric | Result |
|---|---|
| Retrieval hit rate (Q1–Q7, canonical-verse questions) | **2/7 = 29%** |
| Invalid citations across all 10 answers | **0** |
| Polite decline on off-topic Q9 ("stock market outlook") | ✓ |
| Correct "no chapter 19" on out-of-range Q10 | ✓ |

### Reading the numbers honestly

**The grounding layer is solid.** Zero hallucinated citations across 10 answers. When the LLM cites (2.47), it was actually shown verse 2.47. When the retrieved verses don't support an answer — as on Q6, *"who speaks the first verse?"* — the LLM refuses rather than guessing: *"Based on the verses provided, I cannot answer this question."*

**Retrieval is the bottleneck.** 5 of 7 ground-truth questions missed the top-3. The pattern is clear: Victorian prose (*"Thy business is with the action only…"*) is semantically distant from modern natural-language queries (*"doing your duty without attachment"*). The MiniLM embedder loses on that gap.

This is an expected limitation of pure vector search, not a bug. Fixes identified but not applied, so the measurement stays honest:
- Raise top-k from 3 to 5 or 10 — cheap, probably moves us to 5/7.
- Swap to a stronger embedder (`BAAI/bge-base-en-v1.5` or `all-mpnet-base-v2`), rebuild the index.
- Add a cross-encoder reranker on the top-20 candidates.
- Hand-curate alternative phrasings for canonical verses and index both forms.

## What this project demonstrates

For hiring managers and reviewers, this project is a window into:

- **Shipping with measurement attached.** `eval.py` and `eval_results.md` are version-controlled; any future change to prompts, embedder, or chunking can be diff'd against this baseline.
- **Honest numbers over demo polish.** 29% retrieval looks weak in isolation but is the right diagnostic — it localizes the weak link (embedder / Victorian-prose mismatch) and avoids the temptation to cherry-pick wins.
- **Layered hallucination defense.** Four separate mechanisms conspire to prevent ungrounded answers: strict "cite only these verses" system prompt, confidence-threshold short-circuit, post-hoc citation validation, and the honest refusal path when the model judges the grounding insufficient.
- **Hybrid retrieval.** The metadata router sits in front of vector search for exact-reference queries ("what does 2.47 say?"), because embeddings fundamentally can't treat verse numbers as identifiers.
- **Knowing when to stop.** The eval exposes clear improvement paths, but shipping with a measured limitation is a feature, not a bug, for a portfolio artifact.

## Design choices worth noting

- **Chunk text includes a structural prefix** (`"Chapter 2 (Yoga by the Sānkhya), verse 47, The Blessed Lord: Thy business is…"`) so chapter-scoped queries have something to match on. The original verse text is kept untouched in `meta.json` — it's what we show the user and send to the LLM.
- **Score is cosine similarity because vectors are unit-normalised.** `IndexFlatIP` is inner-product search; with `normalize_embeddings=True` at index time and query time, inner product equals cosine similarity.
- **Metadata router ignores the chapter filter.** An explicit verse reference ("2.47") is more specific than a chapter filter, so the reference wins.
- **The 0.3 threshold was chosen empirically** from the first smoke test — "exam results" scored 0.18–0.21 and matched tangentially, while genuine hits scored ≥ 0.44.
- **No prompt caching.** The system prompt is ~250 tokens, below Sonnet 4.6's 2048-token cacheable-prefix minimum. Caching wouldn't trigger at this size.

## Credits

- **Translation:** Annie Besant, *The Bhagavad Gita*, 1895. Public domain.
- **Embedding model:** `sentence-transformers/all-MiniLM-L6-v2`.
- **LLM:** Anthropic Claude Sonnet 4.6.
- **Vector store:** [FAISS](https://github.com/facebookresearch/faiss) (Meta FAIR).
- **UI:** [Streamlit](https://streamlit.io).

Project code: MIT-style, do what you like. Translation is public domain.

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Samvad (formerly "Gita Study Assistant") is a RAG chat app that answers questions about the Bhagavad Gita, grounded in Annie Besant's 1895 English translation with inline chapter–verse citations. The `README.md` has the design rationale, stack table, and eval methodology; it is slightly out of date on the UI (see "Two UIs" below).

## Dev loop

Two services run side by side:

```bash
# 1. Backend (from repo root, in an active .venv)
uvicorn api:app --reload --port 8001

# 2. Frontend (in a second terminal)
cd web && npm run dev    # Vite on http://localhost:5173
```

The React UI hardcodes `API_URL = "http://localhost:8001"` in `web/src/App.tsx`. CORS in `api.py` allows any localhost port via regex.

## One-time setup / rebuild commands

```bash
# Python env + deps + build the vector index (see README for details)
pip install -r requirements.txt
python build_index.py           # writes index/gita.faiss + index/meta.json

# Fetch Sanskrit (Devanagari + IAST) for all 701 verses from
# vedicscriptures.github.io. Resumable; parallelised. Required for the
# Sanskrit lines to show in the UI.
python fetch_sanskrit.py        # writes data/gita_sanskrit.json

# Frontend deps
cd web && npm install
```

Regeneration rules of thumb: rebuild the index whenever `data/gita_besant.json`, chunking, or the embedding model changes. The Sanskrit fetch only needs to run if `data/gita_besant.json` adds verses.

## Frequent commands

```bash
npx tsc -b                      # (from web/) type-check, no emit
npm run build                   # (from web/) prod Vite build, runs tsc first
npm run lint                    # (from web/) oxlint
python eval.py                  # regression suite — makes ~8 Claude calls, rewrites eval_results.md
```

There is **no Python unit-test suite**. `eval.py` is the measurement baseline, committed alongside `eval_results.md`. Any change to retrieval, prompts, or the embedder should re-run eval and update the snapshot.

## Two UIs

- `web/` — current React + Vite + TypeScript frontend. This is the UI we build against.
- `app.py` — legacy Streamlit UI, still runnable (`streamlit run app.py`) and useful for quick backend-only testing. It calls `rag.answer` / `rag.direct_answer` directly (no HTTP), so it doesn't exercise `api.py`.

## Backend architecture

`rag.py` is the self-contained retrieval + grounded-answer core. `api.py` is a thin FastAPI wrapper. Key invariants:

- **FAISS + metadata share row order.** `build_index.py` writes `index/gita.faiss` and `index/meta.json` in lockstep; `retrieve()` uses the FAISS index positions to look up metadata records. Never rebuild one without the other.
- **Embeddings are unit-normalised at both index and query time**, which is why `IndexFlatIP` (inner product) gives cosine similarity.
- **Metadata router runs before vector search.** `_parse_verse_reference` catches "2.47", "verse 2.47", "chapter 2 verse 47" and goes straight to `meta.json` with score 1.0. It intentionally ignores the chapter filter — an explicit reference is more specific.
- **Low-confidence short-circuit at `SCORE_THRESHOLD = 0.3`.** Below this, `answer()` returns `LOW_CONFIDENCE_REPLY` without calling the LLM. This prevents confabulated grounding on weak retrieval.
- **Citation validation is post-hoc.** `_find_invalid_citations` scans the LLM reply for `(C.V)` patterns and flags any that aren't in the retrieved sources — surfaced in the UI as a warning.
- **Post-processing lives in two helpers, applied in order:**
  - `_strip_dashes` — em / en / `--` → `, ` (Claude is instructed not to emit these, but this is the safety net; also collapses resulting comma runs).
  - `_normalize_headings` — a standalone `**Text**` line on its own is promoted to `## Text` so the Markdown renderer treats it as a heading. **Must use `[ \t]*` not `\s*` for line-end whitespace** to avoid consuming blank lines across paragraphs.
- **Both post-processors must run in both answer paths** — `rag.answer()` and the streaming `/ask/stream` endpoint in `api.py` — otherwise they drift.

## Streaming pipeline

`POST /ask/stream` returns Server-Sent Events. Event shapes:

| type | payload | when |
|---|---|---|
| `sources` | `{ sources: [...] }` | once, after retrieval, before any tokens |
| `token` | `{ text: str }` | per Claude text delta (raw, un-scrubbed) |
| `final` | `{ text: str, invalid_citations: [...], used_llm: bool }` | once, at end — fully scrubbed/normalised text |
| `error` | `{ error: str }` | if anything throws mid-stream (HTTP status is already 200 by then) |

The frontend accumulates `token.text` into the assistant message's `answer` field, then **overwrites** with `final.text` so the user sees cleanly scrubbed output. The low-confidence short-circuit also goes through this same pipeline (streams `LOW_CONFIDENCE_REPLY` as a single token event).

`POST /ask` (non-streaming) is kept intact for curl testing but is not used by the UI.

## Data merge quirks

- `rag._enrich()` adds `devanagari` + `iast` fields to every retrieved verse at response time by looking up `data/gita_sanskrit.json` keyed by `"C.V"`. No re-indexing needed; FAISS stays on the Besant English.
- **Chapter 13 has a 1-verse Sanskrit numbering offset.** Besant numbers chapter 13 from verse 0 (Arjuna's question) through 34. The vedicscriptures API merges Arjuna's question into verse 1, so it uses 1–34. `fetch_sanskrit.py::_remote_verse` encodes this shift for chapter 13 only; Besant 13.34 has no direct Sanskrit counterpart and renders blank (the UI handles it gracefully).
- `GET /chapters` merges `data/chapter_summaries.json` (hand-curated 2–3 sentence summaries + 4–5 theme tags per chapter) into the chapter list the UI consumes.

## Frontend architecture

Single-file app in `web/src/App.tsx`. Notable pieces:

- Assistant messages render through `react-markdown` (`.message-body--md`); user messages render as plain text with `pre-wrap`. CSS in `web/src/App.css` styles `h1`–`h4`, `strong`, lists, blockquotes, code *only inside* the markdown body to avoid leaking into the rest of the app.
- `SourcesCarousel` shows one retrieved verse per card (Devanagari → IAST → Besant English) with prev/next + dot indicator.
- When a chapter is picked from the dropdown, an inline chapter card appears with summary + clickable theme chips; clicking a chip pre-fills the input with `What does chapter N say about <theme>?` and focuses it.

## When adding features

- Prefer extending `retrieve()` / `_enrich()` over touching the index or re-embedding. The index is deliberately simple (701 flat vectors) and swapping the embedder is a conscious rebuild, not an incidental change.
- Any change to prompts, embedder, or scoring should also update `eval_results.md` after re-running `python eval.py` — the honest-numbers posture is a feature of this project, not just documentation.
- `_strip_dashes` and `_normalize_headings` are applied twice (sync answer + streaming). If you add a new post-processor, add it in both places.

## Landing page / GitHub Pages

`index.html` at the repo root is a **standalone product landing page** (no build step, inline CSS, inline SVG favicon as a data URL) that pitches Samvad as a platform. It's served via GitHub Pages at **https://arunasivaram.github.io/Samvad/** when Pages is enabled in repo settings (Source: Deploy from branch `main`, folder `/ (root)`). This file is intentionally self-contained so it works both locally (just open it) and on Pages with no build pipeline.

Demo-video convention: the "See it in action" section uses a `<video>` with sources tried in order: `demo.mp4` → `demo.webm` → `demo.gif` fallback image, all expected at the repo root. Dropping any one of these files in and pushing is enough to make the loop appear. Optional `demo-poster.png` acts as the still frame while loading.

## Git state

Remote `origin` → `https://github.com/ArunaSivaram/Samvad.git`. Default branch is **`main`** (renamed from the git default `master`). Two commits live on `main`: the initial commit of the whole working app, then the landing-page commit. `web/package-lock.json` and the built FAISS index are both committed intentionally — the index because it keeps setup to one `pip install` + `python build_index.py` is optional.

## Rebranding state (not yet complete)

The frontend rebrand to **Samvad** is done (title tag, hero, favicon, landing page). The backend prompts and surface strings still reference the old **"Gita Study Assistant"** name in:
- `rag.py` — `SYSTEM_PROMPT` and `DIRECT_SYSTEM_PROMPT` both open with "You are the Gita Study Assistant."
- `api.py` — `FastAPI(title="Gita Study Assistant API")`
- `app.py` — Streamlit `page_title` + module docstring
- `eval.py` — docstring/CLI headers
- `README.md` — all references

Future work: swap these to "Samvad" (or keep the Gita-specific phrasing in the Gita-specific system prompts and only rename the framing docstrings/titles — a judgment call worth asking about).

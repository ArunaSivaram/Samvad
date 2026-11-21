# Learnings

A running log of design decisions made for Samvad, the open items they imply, and where to resume. CLAUDE.md captures *how the codebase works*; this file captures *why we chose what we chose* and *what's half-done*.

## Resume here (next session)

**Immediate next: deploy the two services.** User flagged this as the next conversation topic — walking through a hosting plan for the FastAPI backend and the React frontend, together with a check that GitHub Pages has been enabled for `index.html`. Prior recommendation (not yet executed):

- **Backend → Hugging Face Spaces** (free Docker tier, 16GB RAM, always-on). Good fit for sentence-transformers + FAISS + torch.
- **Frontend → Vercel** (or Cloudflare Pages). Vite builds to static; push-to-deploy.
- **Pre-deploy code changes required** (not yet done):
  1. `web/src/App.tsx` hardcodes `API_URL = "http://localhost:8001"`. Make it a `VITE_API_URL` env var, default to localhost for dev.
  2. CORS regex in `api.py` only allows `localhost|127.0.0.1`. Add the deployed frontend origin.
  3. Dockerfile for the backend. Should pre-download MiniLM at build time so cold-start doesn't hit HF rate limits.
  4. `.env.example` already covers `ANTHROPIC_API_KEY`; set it as a Space secret in HF.
- **Costs**: hosting = $0 on the recommended stack. Anthropic API calls still cost — remind user to set a monthly spend cap in the Anthropic console.

**Also pending (lower priority):**
- GitHub Pages toggle: code is pushed, repo setting needs a manual flip at Settings → Pages (Source: Deploy from branch `main` / root). Site will be live at `https://arunasivaram.github.io/Samvad/`.
- Demo video: drop `demo.mp4` / `demo.webm` / `demo.gif` at repo root, push. Landing page picks it up automatically.
- Backend rebrand: strings in `rag.py`, `api.py`, `app.py`, `eval.py`, and `README.md` still say "Gita Study Assistant". See CLAUDE.md "Rebranding state" for the exact list.
- Mahābhārata corpus: landing page frames it as "Retrieval next". Actual source text + chunking not yet added.

## Design decisions with rationale

### Typography and palette
- **Lora (serif) + Inter (sans) + Noto Sans Devanagari** chosen over Cormorant Garamond or all-serif. Lora is warm enough for verse quotes but neutral enough for the UI; Cormorant is prettier but higher contrast and reads more "fancy" than "study companion." Devanagari needs its own font family so the ॐ wordmark renders cleanly cross-platform.
- **Saffron (`#b45309`) on warm cream (`#fbf8f1`)** with ink text (`#1f1a14`). Palette carries a quiet scripture-study mood without being loud about it. Dark mode is a matched warm-dark palette (bg `#1a1612`) rather than a cold mode flip.

### Information architecture
- **Carousel over expandable list for retrieved sources.** One verse card at a time with prev/next and a position counter beats a stacked `<details>` list for focus and modern feel. Each card shows Devanagari → IAST → Besant English, top to bottom.
- **Inline chapter card over separate chapters tab.** When the user picks a chapter in the dropdown, a card slides in below the settings bar with summary + clickable theme chips. Theme chips pre-fill the input with `What does chapter N say about <theme>?` and focus it — nudges follow-up questions without committing to multi-turn context (that's a future upgrade).
- **Streaming markdown body, plain user body.** Assistant messages render through `react-markdown` so `## Section` headings show as styled headings; user messages stay plain with `pre-wrap`. Separate CSS variant (`.message-body--md`) scopes markdown styles so `h2`/`strong`/lists don't leak elsewhere.

### Grounding philosophy
- **Four layers kept deliberately separate**: strict "cite only these" prompt, confidence-threshold short-circuit (score < 0.3), post-hoc citation validation, and the "refuse plainly" instruction. Collapsing these into one layer sounds cleaner but makes the failure modes less observable. Current eval: zero hallucinated citations across the 10-question set.
- **"Humanize the tone" done with prompt instruction + post-process scrubbing.** Belt-and-suspenders: `SYSTEM_PROMPT` tells Claude to write like a thoughtful friend and never use em/en/double dashes, and `_strip_dashes()` catches any that slip through. Same pattern for headings: prompt says use `## Title`, `_normalize_headings` promotes any stray `**Title**` lines.
- **Dash regex gotcha**: in `_BOLD_LINE_AS_HEADING`, use `[ \t]*$` not `\s*$` — `\s` includes `\n` and greedy-consumes blank lines between paragraphs.

### Data additions
- **Chapter summaries are curated, not LLM-generated.** Writing 18 × (2–3 sentences + 4–5 themes) by hand was faster than wiring a build-time summarization step, and the curated copy reads cleaner. If we ever want grounded-from-verses summaries, there's a pre-generation path noted.
- **Sanskrit from vedicscriptures.github.io.** Public, static-JSON endpoint per verse. 700/701 verses matched; chapter 13 has a 1-verse numbering offset (Besant starts at verse 0 with Arjuna's question; the API starts at verse 1 and folds Arjuna's question into v1). `fetch_sanskrit.py::_remote_verse` encodes the shift; Besant 13.34 has no Sanskrit counterpart and renders blank (UI handles gracefully).

### Streaming architecture
- **SSE over WebSockets.** FastAPI `StreamingResponse` + `text/event-stream` is simpler, works through proxies, and matches the one-way token-flow pattern perfectly. Three event types: `sources` (once up front), `token` (per Claude delta), `final` (full scrubbed text + invalid citations). An `error` event replaces mid-stream 500s since the HTTP status is already 200 by then.
- **Stream raw tokens; overwrite at the end.** The `token` events emit raw Claude output (un-scrubbed). The `final` event sends the fully scrubbed/normalized text; the frontend overwrites the accumulated streamed text with it. The visual "flash" at end is near-imperceptible since the delta is small (scrubbed dashes, promoted headings).

### Honesty / portfolio posture
- **Mahābhārata framed as "Retrieval next"** on the landing page, not shown as equivalent to Gita. User explicitly picked honest framing over marketing-style equivalence — protects portfolio credibility.
- **`eval.py` + `eval_results.md` committed as a measurement baseline.** Current eval shows 29% retrieval hit rate — weak-looking but honest. This is a feature of the project, not a documentation gap.

## Name rationale

"Samvad" (संवाद) = Sanskrit for "dialogue." Fits: (a) the chat interface, (b) the Gita's structural core (a dialogue between Krishna and Arjuna). User initially suggested "Saka" but confirmed they meant **Sakha** / **Sakhā** (सखा, "friend") — a separate option worth keeping in mind if Samvad ever feels too formal. Picked Samvad for now.

## Things I chose not to do

Called out so future-me doesn't re-propose them:

- **Multi-turn conversation context.** Offered as a modernization move alongside streaming; user didn't pick it. Follow-ups like "what about meditation?" currently land as independent queries. Worth revisiting.
- **Chat history sidebar (localStorage).** Also offered alongside streaming; user didn't pick it. Would turn this into a persistent chat app.
- **Pre-generated-from-verses chapter summaries.** Curated won. If grounded summaries become valuable, build-time script path is noted in that conversation.
- **Real Mahābhārata corpus integration.** User picked "coming soon" framing over actually indexing it. Scope decision; defer until after deployment.
- **React Router or `/about` route for the landing page.** User picked standalone HTML at repo root. Cleaner for GitHub Pages; keeps the React bundle focused on the app.

## Open follow-ups in code

- `rag.py` `_strip_dashes` and `_normalize_headings` run twice (sync `answer()` + streaming `_stream_ask`). If you add a third post-processor, add it in both places. Consider extracting to a single `_post_process()` to prevent drift.
- The React frontend hardcodes API_URL; env var migration is the first step of any deploy.
- `app.py` (legacy Streamlit) still works and still calls `rag.answer` directly. If the backend gets significantly refactored, it may silently break. Decide whether to keep or retire it.

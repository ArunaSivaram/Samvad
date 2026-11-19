"""
app.py
Streamlit chat UI for the Gita Study Assistant.

Run:
    streamlit run app.py

Uses:
    rag.answer()         for grounded responses (retrieval + LLM).
    rag.direct_answer()  for RAG-off mode (LLM only, no retrieval).
"""

import streamlit as st

from rag import answer, direct_answer, load_index

# ---------- page setup ----------
st.set_page_config(page_title="Gita Study Assistant", layout="centered")


@st.cache_resource
def load_resources() -> list[tuple[int, str]]:
    """
    Warm the embedder + FAISS + meta singletons (defined in rag.py) and
    return the unique (chapter_num, chapter_title) pairs we need to build
    the chapter filter dropdown. st.cache_resource ensures we only do this
    once per Streamlit process, not on every rerun.
    """
    _, _, meta = load_index()
    chapters = {r["chapter"]: r["chapter_title"] for r in meta}
    return sorted(chapters.items())


chapter_options = load_resources()


# ---------- header ----------
st.title("Gita Study Assistant")
st.caption("Answers from Annie Besant's translation, with chapter and verse.")


# ---------- sidebar ----------
with st.sidebar:
    st.subheader("Retrieval settings")
    k = st.slider("Top-k verses", min_value=1, max_value=8, value=3)

    chapter_labels = ["All chapters"] + [
        f"{num}. {title}" for num, title in chapter_options
    ]
    chapter_choice = st.selectbox("Chapter filter", chapter_labels)
    # Parse the chapter number back out of "1. The Despondency of Arjuna".
    if chapter_choice == "All chapters":
        selected_chapter: int | None = None
    else:
        selected_chapter = int(chapter_choice.split(".", 1)[0])

    use_rag = st.toggle("Use RAG", value=True)
    if not use_rag:
        st.caption(
            "RAG off: the model answers from its own training, with no sources."
        )

    if st.button("Clear chat"):
        st.session_state.messages = []
        st.rerun()

    st.divider()
    st.markdown("**About**")
    st.caption(
        "Knowledge base: 701 verses from the Bhagavad Gita, "
        "Annie Besant translation (public domain). "
        "Embeddings: all-MiniLM-L6-v2. Vector store: FAISS."
    )


# ---------- session state ----------
# Each assistant message is stored as {"role": "assistant", "result": <answer-dict>}
# so we can re-render its sources, warnings, etc. on every rerun.
# User messages are stored as {"role": "user", "content": "<text>"}.
if "messages" not in st.session_state:
    st.session_state.messages = []


# ---------- rendering helpers ----------
def render_assistant(result: dict) -> None:
    """Render an assistant reply: body + optional warning + sources expander."""
    st.markdown(result["answer"])

    invalid = result.get("invalid_citations", [])
    if invalid:
        st.warning(
            "Cited verse not in retrieved context: " + ", ".join(invalid)
        )

    sources = result.get("sources", [])
    if sources:
        with st.expander("Source verses"):
            for h in sources:
                st.markdown(
                    f"**{h['chapter']}.{h['verse']}**: "
                    f"{h['speaker']} · {h['chapter_title']} · "
                    f"similarity {h['score']:.2f}"
                )
                st.markdown(f"> {h['text']}")


def handle_question(question: str) -> None:
    """
    Append the user turn, run retrieval + LLM (or direct LLM), render both
    turns inline, then persist them to session state so later reruns show
    them from history.
    """
    with st.chat_message("user"):
        st.markdown(question)
    st.session_state.messages.append({"role": "user", "content": question})

    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                if use_rag:
                    result = answer(question, k=k, chapter=selected_chapter)
                else:
                    result = direct_answer(question)
            except RuntimeError as e:
                # Most commonly: missing ANTHROPIC_API_KEY. Surface as a
                # chat message so the user sees what to fix.
                result = {
                    "answer": f"⚠️ {e}",
                    "sources": [],
                    "used_llm": False,
                    "invalid_citations": [],
                }
        render_assistant(result)

    st.session_state.messages.append({"role": "assistant", "result": result})


# ---------- render chat history ----------
# History renders BEFORE we handle any new question. That way, when a new
# question is being processed, we render the old turns from history and the
# new turn inline inside handle_question() -- no double-rendering.
for msg in st.session_state.messages:
    if msg["role"] == "user":
        with st.chat_message("user"):
            st.markdown(msg["content"])
    else:
        with st.chat_message("assistant"):
            render_assistant(msg["result"])


# ---------- example buttons (only when chat is empty) ----------
EXAMPLES = [
    "What does the Gita say about duty?",
    "I'm anxious about results. What does the Gita say?",
    "What is the nature of the soul?",
    "How should one meditate?",
]

new_question: str | None = None

if not st.session_state.messages:
    st.markdown("**Try one of these to get started:**")
    cols = st.columns(2)
    for i, ex in enumerate(EXAMPLES):
        if cols[i % 2].button(ex, key=f"ex_{i}", use_container_width=True):
            new_question = ex


# ---------- chat input ----------
if prompt := st.chat_input("Ask about the Bhagavad Gita..."):
    new_question = prompt


# ---------- process the new question (if any) ----------
if new_question:
    handle_question(new_question)

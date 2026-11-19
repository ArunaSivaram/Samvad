import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import "./App.css";

// ---------- type definitions ----------
type Source = {
  chapter: number;
  chapter_title: string;
  verse: string;
  speaker: string;
  text: string;
  devanagari: string;
  iast: string;
  score: number;
};

type AnswerResponse = {
  answer: string;
  sources: Source[];
  used_llm: boolean;
  invalid_citations: string[];
};

type Chapter = {
  number: number;
  title: string;
  summary: string;
  themes: string[];
};

type Message =
  | { role: "user"; content: string }
  | { role: "assistant"; result: AnswerResponse };

const API_URL = "http://localhost:8001";

// First-run example questions. Shown as clickable buttons when the chat is empty.
const EXAMPLES = [
  "What does the Gita say about duty?",
  "I'm anxious about results. What does the Gita say?",
  "What is the nature of the soul?",
  "How should one meditate?",
];


// ---------- SourcesCarousel ----------
function SourcesCarousel({ sources }: { sources: Source[] }) {
  const [i, setI] = useState(0);
  const n = sources.length;
  if (n === 0) return null;

  // Re-clamp the index if the sources list shrinks between renders.
  const idx = Math.min(i, n - 1);
  const s = sources[idx];
  const single = n === 1;

  return (
    <div className="carousel">
      <div className="carousel-header">
        <span className="carousel-label">Source verses</span>
        <span className="carousel-counter">
          {idx + 1} / {n}
        </span>
      </div>

      <div className="carousel-card">
        <div className="source-meta">
          <span className="source-ref">
            {s.chapter}.{s.verse}
          </span>
          {" · "}
          {s.speaker} · {s.chapter_title} · similarity {s.score.toFixed(2)}
        </div>
        {s.devanagari && (
          <p className="source-devanagari">{s.devanagari}</p>
        )}
        {s.iast && <p className="source-iast">{s.iast}</p>}
        <blockquote className="source-text">{s.text}</blockquote>
      </div>

      <div className="carousel-controls">
        <button
          type="button"
          className="carousel-arrow"
          onClick={() => setI((idx - 1 + n) % n)}
          disabled={single}
          aria-label="Previous verse"
        >
          ‹
        </button>
        <div className="carousel-dots">
          {sources.map((_, dotIdx) => (
            <button
              key={dotIdx}
              type="button"
              className={
                "carousel-dot" +
                (dotIdx === idx ? " carousel-dot--active" : "")
              }
              onClick={() => setI(dotIdx)}
              aria-label={`Go to verse ${dotIdx + 1}`}
            />
          ))}
        </div>
        <button
          type="button"
          className="carousel-arrow"
          onClick={() => setI((idx + 1) % n)}
          disabled={single}
          aria-label="Next verse"
        >
          ›
        </button>
      </div>
    </div>
  );
}


// ---------- AssistantMessage ----------
function AssistantMessage({ result }: { result: AnswerResponse }) {
  return (
    <>
      <div className="message-body message-body--md">
        <ReactMarkdown>{result.answer}</ReactMarkdown>
      </div>

      {result.invalid_citations.length > 0 && (
        <div className="citation-warning">
          ⚠️ Cited verse not in retrieved context:{" "}
          {result.invalid_citations.join(", ")}
        </div>
      )}

      <SourcesCarousel sources={result.sources} />
    </>
  );
}


// ---------- App ----------
export default function App() {
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const [k, setK] = useState(3);
  const [chapter, setChapter] = useState<number | null>(null);
  const [useRag, setUseRag] = useState(true);

  const [chapters, setChapters] = useState<Chapter[]>([]);

  const inputRef = useRef<HTMLInputElement>(null);

  const selectedChapter =
    chapter !== null ? chapters.find((c) => c.number === chapter) : undefined;

  function handleThemeClick(theme: string) {
    if (chapter === null) return;
    setInput(
      `What does chapter ${chapter} say about ${theme.toLowerCase()}?`,
    );
    inputRef.current?.focus();
  }

  useEffect(() => {
    fetch(`${API_URL}/chapters`)
      .then((r) => r.json())
      .then((data: Chapter[]) => setChapters(data))
      .catch(() => {});
  }, []);

  // Helper: update the trailing assistant message by applying a patch to its
  // result. The streaming path accumulates tokens by calling this on each
  // "token" event. If the last message isn't an assistant message yet (first
  // token arriving), it inserts an empty one.
  function updateLastAssistant(
    patch: (r: AnswerResponse) => AnswerResponse,
  ) {
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last && last.role === "assistant") {
        next[next.length - 1] = { role: "assistant", result: patch(last.result) };
      } else {
        next.push({
          role: "assistant",
          result: patch({
            answer: "",
            sources: [],
            used_llm: false,
            invalid_citations: [],
          }),
        });
      }
      return next;
    });
  }

  // The shared "ask a question" path. Callable from both the form submit
  // (handleSubmit) and the example question buttons. Consumes the streaming
  // /ask/stream endpoint so tokens appear as Claude generates them.
  async function ask(question: string) {
    if (!question || isLoading) return;

    setMessages((prev) => [...prev, { role: "user", content: question }]);
    setIsLoading(true);

    try {
      const response = await fetch(`${API_URL}/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question,
          k,
          chapter,
          use_rag: useRag,
        }),
      });
      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      // Each SSE event ends with "\n\n". Split on that; keep the final
      // partial chunk in `buffer` until the next read.
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        let sep = buffer.indexOf("\n\n");
        while (sep !== -1) {
          const raw = buffer.slice(0, sep);
          buffer = buffer.slice(sep + 2);
          sep = buffer.indexOf("\n\n");

          if (!raw.startsWith("data: ")) continue;
          let event: {
            type: string;
            text?: string;
            sources?: Source[];
            invalid_citations?: string[];
            used_llm?: boolean;
            error?: string;
          };
          try {
            event = JSON.parse(raw.slice(6));
          } catch {
            continue;
          }

          if (event.type === "sources" && event.sources) {
            const sources = event.sources;
            updateLastAssistant((r) => ({ ...r, sources }));
          } else if (event.type === "token" && event.text) {
            const chunk = event.text;
            updateLastAssistant((r) => ({ ...r, answer: r.answer + chunk }));
          } else if (event.type === "final" && event.text !== undefined) {
            const finalText = event.text;
            const invalid = event.invalid_citations ?? [];
            const usedLlm = event.used_llm ?? false;
            updateLastAssistant((r) => ({
              ...r,
              answer: finalText,
              invalid_citations: invalid,
              used_llm: usedLlm,
            }));
          } else if (event.type === "error" && event.error) {
            const errText = event.error;
            updateLastAssistant((r) => ({
              ...r,
              answer: `Error talking to the backend: ${errText}`,
            }));
          }
        }
      }
    } catch (err) {
      updateLastAssistant((r) => ({
        ...r,
        answer: `Error talking to the backend: ${err}`,
      }));
    } finally {
      setIsLoading(false);
    }
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const question = input.trim();
    setInput("");
    await ask(question);
  }

  return (
    <div className="app">
      <header className="app-header">
        <div className="app-mark" aria-hidden="true">ॐ</div>
        <h1 className="app-title">Samvad</h1>
        <p className="app-subtitle">
          A dialogue with the Bhagavad Gita, verse by verse.
        </p>
      </header>

      {/* Settings panel */}
      <div className="settings-bar">
        <label>
          Top-k:
          <input
            type="range"
            min={1}
            max={8}
            value={k}
            onChange={(e) => setK(Number(e.target.value))}
          />
          <span className="settings-k-value">{k}</span>
        </label>

        <label>
          Chapter:
          <select
            value={chapter ?? ""}
            onChange={(e) =>
              setChapter(e.target.value ? Number(e.target.value) : null)
            }
          >
            <option value="">All chapters</option>
            {chapters.map((c) => (
              <option key={c.number} value={c.number}>
                {c.number}. {c.title}
              </option>
            ))}
          </select>
        </label>

        <label>
          <input
            type="checkbox"
            checked={useRag}
            onChange={(e) => setUseRag(e.target.checked)}
          />
          Use RAG
        </label>

        <button
          type="button"
          className="clear-button"
          onClick={() => setMessages([])}
          disabled={messages.length === 0}
        >
          Clear chat
        </button>
      </div>

      {selectedChapter && selectedChapter.summary && (
        <div className="chapter-card">
          <h2 className="chapter-card-title">
            <span className="chapter-card-number">
              Chapter {selectedChapter.number}
            </span>
            {selectedChapter.title}
          </h2>
          <p className="chapter-card-summary">{selectedChapter.summary}</p>
          {selectedChapter.themes.length > 0 && (
            <>
              <span className="chapter-card-themes-label">Key themes</span>
              <div className="chapter-card-themes">
                {selectedChapter.themes.map((t) => (
                  <button
                    key={t}
                    type="button"
                    className="theme-chip"
                    onClick={() => handleThemeClick(t)}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </>
          )}
        </div>
      )}

      {!useRag && (
        <p className="rag-notice">
          RAG off: the model answers from its own training, with no sources.
        </p>
      )}

      {/* Example-question buttons -- only when the chat is empty */}
      {messages.length === 0 && (
        <div className="examples">
          <p className="examples-prompt">Try one of these to get started:</p>
          <div className="examples-grid">
            {EXAMPLES.map((ex) => (
              <button
                key={ex}
                type="button"
                className="example-button"
                onClick={() => ask(ex)}
                disabled={isLoading}
              >
                {ex}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Message list */}
      <div className="messages">
        {messages.map((msg, i) => (
          <div
            key={i}
            className={`message message--${msg.role}`}
          >
            <span className="message-role">
              {msg.role === "user" ? "You" : "Assistant"}
            </span>
            {msg.role === "user" ? (
              <div className="message-body">{msg.content}</div>
            ) : (
              <AssistantMessage result={msg.result} />
            )}
          </div>
        ))}
        {isLoading && messages[messages.length - 1]?.role === "user" && (
          <div className="thinking">Thinking…</div>
        )}
      </div>

      {/* Input box */}
      <form onSubmit={handleSubmit} className="input-form">
        <input
          ref={inputRef}
          type="text"
          className="input-field"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Ask about the Bhagavad Gita..."
          disabled={isLoading}
        />
        <button
          type="submit"
          className="send-button"
          disabled={isLoading || !input.trim()}
        >
          Send
        </button>
      </form>
    </div>
  );
}

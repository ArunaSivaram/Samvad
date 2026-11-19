"""
eval.py
Fixed-question regression suite for the Gita Study Assistant.

Runs a small, canned test set through rag.answer() with k=3 and prints a
results table plus a short summary. Also writes everything to
eval_results.md so you have a dated snapshot you can diff against after
future changes (prompt tweaks, chunking changes, model upgrades).

Run:
    python eval.py

This WILL call the Claude API (one call per question that passes the
retrieval confidence threshold -- expect ~8 calls total).
"""

from pathlib import Path

from rag import answer

# Test set. Each item:
#   q         -- the question to ask
#   expected  -- "any one of these counts as a retrieval hit" (chapter.verse)
#   kind      -- "retrieval"  : scored against the expected list
#                "freeform"   : no fixed answer; just print what came back
#                "decline"    : expect a polite low-confidence reply
#                "nonexistent": expect the system to recognise the ref is invalid
TEST_SET = [
    {"q": "doing your duty without attachment to results",
     "expected": ["2.47", "3.19"], "kind": "retrieval"},
    {"q": "the soul is never born and never dies",
     "expected": ["2.20", "2.19", "2.21"], "kind": "retrieval"},
    {"q": "how to sit for meditation",
     "expected": ["6.11", "6.12", "6.13"], "kind": "retrieval"},
    {"q": "staying calm in pleasure and pain",
     "expected": ["2.14", "2.38", "2.15"], "kind": "retrieval"},
    {"q": "surrendering everything to God",
     "expected": ["18.66"], "kind": "retrieval"},
    {"q": "who speaks the first verse of the Gita",
     "expected": ["1.1"], "kind": "retrieval"},
    {"q": "I'm anxious about my exam results",
     "expected": ["2.47", "2.48"], "kind": "retrieval"},
    {"q": "compare the path of action and the path of devotion",
     "expected": [], "kind": "freeform"},
    {"q": "what's the stock market outlook?",
     "expected": [], "kind": "decline"},
    {"q": "what does chapter 19 verse 5 say?",
     "expected": [], "kind": "nonexistent"},
]


def source_ids(sources: list[dict]) -> list[str]:
    """Flatten a sources list to ['2.47', '3.19', ...]."""
    return [f"{s['chapter']}.{s['verse']}" for s in sources]


def retrieved_cell(expected: list[str], retrieved: list[str]) -> str:
    """Render the 'Retrieved?' column for one row."""
    if not expected:
        # No ground truth; just show what came back.
        return (", ".join(retrieved) or "none") + " (n/a)"
    hit = next((v for v in expected if v in retrieved), None)
    if hit:
        return f"✓ {hit}"
    return f"✗ (got {', '.join(retrieved) or 'none'})"


def escape_pipes(s: str) -> str:
    """Pipes break markdown tables; backslash-escape them."""
    return s.replace("|", "\\|")


def run_eval() -> str:
    """Run every test, return a markdown report as a string."""
    rows = []
    results: list[dict] = []  # parallel to TEST_SET, for the special-case printout

    for i, item in enumerate(TEST_SET, 1):
        print(f"[{i}/{len(TEST_SET)}] {item['q']}")
        result = answer(item["q"], k=3)
        results.append(result)

        retrieved = source_ids(result["sources"])
        expected_str = ", ".join(item["expected"]) if item["expected"] else "—"
        retrieved_str = retrieved_cell(item["expected"], retrieved)
        invalid_str = ", ".join(result["invalid_citations"]) or "—"

        # First 120 chars of the answer, single-lined for the table.
        snippet = result["answer"][:120].replace("\n", " ").strip()
        if len(result["answer"]) > 120:
            snippet += "…"

        rows.append(
            f"| {i} | {escape_pipes(item['q'])} | {expected_str} | "
            f"{retrieved_str} | {invalid_str} | {escape_pipes(snippet)} |"
        )

    # Metrics -- only questions 1-7 have ground truth we score against.
    retrieval_items = [t for t in TEST_SET if t["kind"] == "retrieval"]
    retrieval_hits = sum(
        1 for t, r in zip(TEST_SET, results)
        if t["kind"] == "retrieval"
        and any(v in source_ids(r["sources"]) for v in t["expected"])
    )
    invalid_count = sum(1 for r in results if r["invalid_citations"])

    # Compose the markdown report.
    lines = [
        "# Gita Study Assistant -- eval results",
        "",
        "Run of `python eval.py` against the fixed test set. Each question "
        "is sent through `answer(q, k=3)`.",
        "",
        "| # | Question | Expected verses | Retrieved? | Invalid citations | Answer (first 120 chars) |",
        "|---|---|---|---|---|---|",
        *rows,
        "",
        "## Summary",
        "",
        f"- **Retrieval hit rate (Q1–Q7):** {retrieval_hits}/{len(retrieval_items)} "
        f"= {retrieval_hits / len(retrieval_items):.0%}",
        f"- **Answers with invalid citations:** {invalid_count} of {len(TEST_SET)}",
        "",
        "## Judge by eye -- Q9 (polite decline) and Q10 (no chapter 19)",
        "",
    ]

    for item, result in zip(TEST_SET, results):
        if item["kind"] in ("decline", "nonexistent"):
            label = (
                "**Q9 (polite decline expected)**"
                if item["kind"] == "decline"
                else "**Q10 (no chapter 19 expected)**"
            )
            lines.append(f"{label} — _{item['q']}_")
            lines.append("")
            # Blockquote each line of the answer so markdown renders it nicely.
            for line in result["answer"].splitlines():
                lines.append(f"> {line}")
            lines.append("")

    return "\n".join(lines)


def main() -> None:
    report = run_eval()
    print("\n" + "=" * 70)
    print(report)
    print("=" * 70)
    output_file = Path(__file__).parent / "eval_results.md"
    output_file.write_text(report, encoding="utf-8")
    print(f"\nWrote {output_file}")


if __name__ == "__main__":
    main()

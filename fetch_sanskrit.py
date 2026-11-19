"""
fetch_sanskrit.py
One-time build script. Downloads Sanskrit Devanagari + IAST transliteration
for every (chapter, verse) in data/gita_besant.json from vedicscriptures.github.io
and writes data/gita_sanskrit.json keyed by "chapter.verse".

Run:
    python fetch_sanskrit.py

Resumable: if data/gita_sanskrit.json already contains a verse, it is skipped.
Parallel: uses a small thread pool so 700 requests finish in a few seconds.
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

PROJECT_DIR = Path(__file__).parent
BESANT_FILE = PROJECT_DIR / "data" / "gita_besant.json"
SANSKRIT_FILE = PROJECT_DIR / "data" / "gita_sanskrit.json"
URL_TEMPLATE = "https://vedicscriptures.github.io/slok/{chapter}/{verse}"

MAX_WORKERS = 10
TIMEOUT_SECS = 15


def _remote_verse(chapter: int, verse: str) -> str:
    """
    The vedicscriptures API numbers chapter 13 starting at verse 1 (treating
    Arjuna's opening question as verse 1 and shifting everything else by one),
    while the Besant dataset numbers it starting at verse 0. Shift chapter 13
    only. Besant 13.34 has no direct Sanskrit counterpart in this edition.
    """
    if chapter == 13 and verse.isdigit():
        return str(int(verse) + 1)
    return verse


def _fetch_one(chapter: int, verse: str) -> tuple[str, dict, str]:
    """Fetch one verse. Returns (Besant key, record, status)."""
    key = f"{chapter}.{verse}"
    remote_v = _remote_verse(chapter, verse)
    url = URL_TEMPLATE.format(chapter=chapter, verse=remote_v)
    try:
        resp = requests.get(url, timeout=TIMEOUT_SECS)
        if resp.status_code == 200:
            data = resp.json()
            return key, {
                "devanagari": (data.get("slok") or "").strip(),
                "iast": (data.get("transliteration") or "").strip(),
            }, "ok"
        return key, {"devanagari": "", "iast": ""}, f"http {resp.status_code}"
    except Exception as e:
        return key, {"devanagari": "", "iast": ""}, f"err {e}"


def main() -> int:
    verses = json.loads(BESANT_FILE.read_text(encoding="utf-8"))

    out: dict[str, dict] = {}
    if SANSKRIT_FILE.exists():
        out = json.loads(SANSKRIT_FILE.read_text(encoding="utf-8"))

    todo = [
        (v["chapter"], v["verse"]) for v in verses
        if f"{v['chapter']}.{v['verse']}" not in out
        or not out[f"{v['chapter']}.{v['verse']}"].get("devanagari")
    ]
    print(f"{len(todo)} verses to fetch (of {len(verses)} total)")
    if not todo:
        print("Nothing to do.")
        return 0

    done = 0
    start = time.time()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            pool.submit(_fetch_one, c, v): (c, v) for c, v in todo
        }
        for future in as_completed(futures):
            key, record, status = future.result()
            out[key] = record
            done += 1
            if status != "ok" or done % 50 == 0 or done == len(todo):
                print(f"  [{done}/{len(todo)}] {key}: {status}")
            if done % 100 == 0:
                SANSKRIT_FILE.write_text(
                    json.dumps(out, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

    SANSKRIT_FILE.write_text(
        json.dumps(out, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    elapsed = time.time() - start
    missing = sum(1 for v in out.values() if not v.get("devanagari"))
    print(
        f"Done in {elapsed:.1f}s. Wrote {len(out)} entries to "
        f"{SANSKRIT_FILE.relative_to(PROJECT_DIR)} "
        f"({missing} without Devanagari)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""
build_index.py
Build a FAISS vector index over Annie Besant's Bhagavad Gita translation.

Run this ONCE after installing dependencies, or any time data/gita_besant.json
changes. Outputs (written to the index/ folder next to this script):

  index/gita.faiss  -- FAISS index, 701 vectors of dim 384
  index/meta.json   -- the original records in the SAME order as the vectors
                       (position i in FAISS == records[i] in meta.json)
"""

import json
from pathlib import Path

import faiss
from sentence_transformers import SentenceTransformer

# ---------- paths and config ----------
PROJECT_DIR = Path(__file__).parent
DATA_FILE = PROJECT_DIR / "data" / "gita_besant.json"
INDEX_DIR = PROJECT_DIR / "index"
INDEX_FILE = INDEX_DIR / "gita.faiss"
META_FILE = INDEX_DIR / "meta.json"

# all-MiniLM-L6-v2 is small (~90 MB), fast on CPU, and produces 384-dim embeddings.
EMBEDDING_MODEL = "all-MiniLM-L6-v2"


def build_chunk_text(record: dict) -> str:
    """
    Produce the string we will embed for one verse.

    Format (one line):
      "Chapter {chapter} ({chapter_title}), verse {verse}, {speaker}: {text}"

    Prepending the chapter number and title helps on questions like
    "what does chapter 2 say about ..." -- the verse text alone usually
    doesn't mention which chapter it is in, so the embedding wouldn't
    capture that signal otherwise.
    """
    return (
        f"Chapter {record['chapter']} ({record['chapter_title']}), "
        f"verse {record['verse']}, {record['speaker']}: {record['text']}"
    )


def main() -> None:
    # 1. Load the source JSON -- a list of 701 verse records.
    print(f"Loading {DATA_FILE} ...")
    records = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    n_records = len(records)
    print(f"  Loaded {n_records} records.")

    # 2. Build the string we embed, one per verse. Order is preserved, so
    #    chunks[i] <-> records[i] <-> FAISS row i. We'll reuse this invariant
    #    at retrieval time to map a FAISS hit back to its original record.
    chunks = [build_chunk_text(r) for r in records]

    # 3. Embed all chunks. normalize_embeddings=True makes each vector
    #    unit-length, which turns FAISS inner product into cosine similarity.
    print(f"Embedding {n_records} verses with {EMBEDDING_MODEL} ...")
    model = SentenceTransformer(EMBEDDING_MODEL)
    embeddings = model.encode(
        chunks,
        batch_size=64,
        show_progress_bar=True,
        normalize_embeddings=True,
    ).astype("float32")  # FAISS requires float32

    vector_dim = embeddings.shape[1]

    # 4. Build the FAISS index. IndexFlatIP = exact inner-product search.
    #    Combined with unit-length vectors (step 3), this gives cosine
    #    similarity. 701 vectors is tiny -- exact search is plenty fast,
    #    no need for approximate indexes like IVF or HNSW.
    index = faiss.IndexFlatIP(vector_dim)
    index.add(embeddings)

    # 5. Persist index + metadata. meta.json contains the ORIGINAL records
    #    untouched -- that's the exact text we show users and send to the LLM
    #    at retrieval time. The structural prefix we built in step 2 is ONLY
    #    for the embedding; we do not want to expose it in the UI.
    INDEX_DIR.mkdir(exist_ok=True)
    faiss.write_index(index, str(INDEX_FILE))
    META_FILE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # 6. Print the summary and confirm counts line up.
    index_size = index.ntotal
    print()
    print("Summary:")
    print(f"  Records in meta.json: {n_records}")
    print(f"  Vector dimension:     {vector_dim}")
    print(f"  FAISS index size:     {index_size}")
    if n_records == index_size:
        print(f"  OK -- records and FAISS rows match ({n_records}).")
    else:
        print(f"  MISMATCH -- records ({n_records}) != FAISS rows ({index_size}).")
    print()
    print(f"Wrote {INDEX_FILE}")
    print(f"Wrote {META_FILE}")


if __name__ == "__main__":
    main()

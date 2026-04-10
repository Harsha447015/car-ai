"""
BE6 Manual → ChromaDB Ingestion Script

Reads the Mahindra BE6 vehicle manual PDF, splits each page into
overlapping ~400-char chunks (so nothing falls outside the embedding
model's 256-token window), strips boilerplate, and stores them in a
persistent ChromaDB collection for RAG retrieval.

Usage:
    python be6_rag.py            # build/rebuild the database
    python be6_rag.py --test     # run test queries after building
"""

import argparse
import os
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

import chromadb
import fitz  # PyMuPDF
from chromadb.utils import embedding_functions

# ── Settings ──────────────────────────────────────────────────────────────────
PDF_PATH = r"C:\car_ai\Vehicle Manual_BE6_compressed.pdf"
DB_PATH  = r"C:\car_ai\be6_database"

CHUNK_SIZE    = 400   # characters per chunk (fits within 256 tokens)
CHUNK_OVERLAP = 100   # overlap between consecutive chunks


# ── Boilerplate removal ───────────────────────────────────────────────────────
def clean_page_text(text: str) -> str:
    """Remove copyright headers, page numbers, and excessive whitespace."""
    lines = text.split("\n")
    cleaned = []
    for line in lines:
        stripped = line.strip()
        # Skip common boilerplate patterns
        if not stripped:
            continue
        if re.match(r'^©.*Mahindra', stripped, re.IGNORECASE):
            continue
        if re.match(r'^\d+$', stripped):  # bare page numbers
            continue
        if re.match(r'^Page\s+\d+', stripped, re.IGNORECASE):
            continue
        if "all rights reserved" in stripped.lower():
            continue
        cleaned.append(stripped)
    return "\n".join(cleaned)


# ── Chunking ──────────────────────────────────────────────────────────────────
def chunk_text(text: str, chunk_size: int = CHUNK_SIZE,
               overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping chunks of roughly chunk_size characters."""
    if len(text) <= chunk_size:
        return [text] if text.strip() else []

    chunks = []
    start = 0
    while start < len(text):
        end = start + chunk_size

        # Try to break at a sentence boundary or newline
        if end < len(text):
            # Look for a sentence-ending punctuation near the end
            best_break = -1
            for sep in ["\n", ". ", "? ", "! ", "; "]:
                idx = text.rfind(sep, start + chunk_size // 2, end + 50)
                if idx != -1 and idx > best_break:
                    best_break = idx + len(sep)
            if best_break > start:
                end = best_break

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - overlap
        if start >= len(text):
            break

    return chunks


# ── Read PDF ──────────────────────────────────────────────────────────────────
def read_and_chunk_pdf(pdf_path: str) -> list[dict]:
    print("📖 Reading BE6 manual...")
    doc = fitz.open(pdf_path)
    all_chunks = []

    for page_num in range(len(doc)):
        page = doc[page_num]
        raw_text = page.get_text()
        cleaned = clean_page_text(raw_text)

        if len(cleaned) < 50:  # skip near-empty pages
            continue

        chunks = chunk_text(cleaned)
        for i, chunk in enumerate(chunks):
            all_chunks.append({
                "text": chunk,
                "page": page_num + 1,
                "chunk_index": i,
            })

    print(f"✅ Extracted {len(all_chunks)} chunks from {len(doc)} pages")
    return all_chunks


# ── Build ChromaDB ────────────────────────────────────────────────────────────
def build_database(chunks: list[dict]) -> chromadb.Collection:
    print("🗄️  Building searchable database...")

    embedding_fn = embedding_functions.DefaultEmbeddingFunction()
    client = chromadb.PersistentClient(path=DB_PATH)

    # Drop and recreate
    try:
        client.delete_collection("be6_manual")
    except Exception:
        pass

    collection = client.create_collection(
        name="be6_manual",
        embedding_function=embedding_fn,
    )

    # Add in batches (ChromaDB recommends ≤5000 per call)
    batch_size = 500
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        collection.add(
            documents=[c["text"] for c in batch],
            ids=[f"p{c['page']}_c{c['chunk_index']}" for c in batch],
            metadatas=[{"page": c["page"], "chunk": c["chunk_index"]} for c in batch],
        )
        print(f"   Added {min(i + batch_size, len(chunks))}/{len(chunks)} chunks")

    print(f"✅ Database built — {len(chunks)} searchable chunks")
    return collection


# ── Test queries ──────────────────────────────────────────────────────────────
def run_tests(collection: chromadb.Collection) -> None:
    test_queries = [
        "engine warning light blinking",
        "dashboard indicator lights meaning",
        "warning lights on dashboard",
        "tire pressure warning",
        "how long does it take to charge",
        "what is boost mode",
        "airbag warning light",
        "brake warning light",
        "battery low warning",
    ]

    print("\n" + "=" * 60)
    print("   RAG Test Queries")
    print("=" * 60)

    for query in test_queries:
        results = collection.query(query_texts=[query], n_results=3)
        print(f"\n🔍 Query: \"{query}\"")
        for i, doc in enumerate(results["documents"][0]):
            page = results["metadatas"][0][i].get("page", "?")
            dist = results["distances"][0][i] if results.get("distances") else "?"
            preview = doc[:150].replace("\n", " ")
            print(f"   [{i+1}] Page {page} (dist={dist:.2f}): {preview}...")
        print()


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Build BE6 manual RAG database")
    parser.add_argument("--test", action="store_true", help="Run test queries after building")
    args = parser.parse_args()

    print("=" * 60)
    print("   Mahindra BE6 — RAG Database Builder")
    print("=" * 60)

    # Always rebuild for consistency
    if not os.path.exists(PDF_PATH):
        print(f"❌ PDF not found at: {PDF_PATH}")
        sys.exit(1)

    chunks = read_and_chunk_pdf(PDF_PATH)
    collection = build_database(chunks)

    print(f"\n✅ Done! Database saved to: {DB_PATH}")
    print(f"   Total chunks: {collection.count()}")
    print(f"   Chunk size: ~{CHUNK_SIZE} chars with {CHUNK_OVERLAP} char overlap")

    if args.test:
        run_tests(collection)
    else:
        print("\nTip: run with --test to verify search quality")
        print("     python be6_rag.py --test")


if __name__ == "__main__":
    main()

"""Chunk the cached extractions in data/extracted/ and index them into Pinecone.

Usage (from the repo root):
    uv run --env-file .env python -m scripts.index_documents \
        [--namespace NAME] [--no-section] [--yes]

Needs PINECONE_API_KEY and PINECONE_INDEX. Textract is never called: the input is the
ExtractedDocument JSON saved by scripts/extract_pdf.py. Re-running replaces each document's
chunks (stale chunk IDs are deleted), so the record count does not grow.
"""

import argparse
import logging
import sys
from pathlib import Path

from src.chunking import chunk_document
from src.indexing import embedding_text, index_document
from src.models import ExtractedDocument
from src.providers.pinecone import PineconeInferenceEmbedder, PineconeStore

IN_DIR = Path("data/extracted")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--namespace", default="", help="Pinecone namespace (default: default)")
    parser.add_argument("--no-section", action="store_true", help="embed the body only")
    parser.add_argument("--yes", action="store_true", help="do not ask before writing")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    with_section = not args.no_section

    docs = [
        ExtractedDocument.model_validate_json(p.read_text()) for p in sorted(IN_DIR.glob("*.json"))
    ]
    if not docs:
        print(f"no extracted documents in {IN_DIR}")
        return 1
    chunked = [(doc, chunk_document(doc)) for doc in docs]
    embedder = PineconeInferenceEmbedder.from_env()
    # index_document embeds one document at a time, so estimate per document as well.
    estimate = sum(
        embedder.estimate_tokens([embedding_text(c, with_section) for c in chunks])
        for _, chunks in chunked
    )
    for doc, chunks in chunked:
        print(f"{doc.doc_id}  {doc.source_file}  chunks={len(chunks)}")
    print(f"namespace: {args.namespace or '(default)'}  with_section: {with_section}")
    print(f"about {estimate} embedding tokens (free plan: 5M/month)")
    if not args.yes and input("Write to Pinecone? [y/N] ").strip().lower() != "y":
        print("aborted")
        return 1

    store = PineconeStore.from_env(embedder_name=embedder.name, namespace=args.namespace)
    for doc, chunks in chunked:
        index_document(doc.doc_id, chunks, embedder, store, with_section=with_section)
    print(f"indexed {sum(len(c) for _, c in chunked)} chunks")
    print(f"embedding tokens used: {embedder.tokens_used}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

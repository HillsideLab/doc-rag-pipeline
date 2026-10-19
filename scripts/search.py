"""Ask questions against the Pinecone index and print the top chunks.

Usage (from the repo root):
    uv run --env-file .env python -m scripts.search "question" ["question" ...] \
        [--top-k 5] [--doc-id ID] [--namespace NAME] [--rerank]

Needs PINECONE_API_KEY and PINECONE_INDEX. Read-only: only embeds the question and queries.
"""

import argparse
import sys

from src.indexing import search
from src.providers.pinecone import PineconeInferenceEmbedder, PineconeReranker, PineconeStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("questions", nargs="+")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--doc-id", default=None, help="search one document only")
    parser.add_argument("--namespace", default="", help="Pinecone namespace (default: default)")
    parser.add_argument("--rerank", action="store_true", help="rerank the top 50 vector hits")
    args = parser.parse_args()

    embedder = PineconeInferenceEmbedder.from_env()
    store = PineconeStore.from_env(embedder_name=embedder.name, namespace=args.namespace)
    reranker = PineconeReranker.from_env() if args.rerank else None
    for question in args.questions:
        print(f"\nQ: {question}")
        hits = search(question, embedder, store, args.top_k, args.doc_id, reranker=reranker)
        for rank, hit in enumerate(hits, 1):
            chunk = hit.chunk
            print(
                f"{rank}. {hit.score:.4f}  {chunk.chunk_id}  p{chunk.page}  "
                f"{chunk.section or '-'}  | {chunk.text[:70].replace(chr(10), ' ')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Answer one question and print the answer, its citations and the disclaimer.

Usage (from the repo root):
    EMBEDDER=pinecone VECTOR_STORE=pinecone RERANKER=pinecone \
        uv run --env-file .env python -m scripts.ask "question" [--top-k 5] [--doc-id ID]

Providers are chosen by EMBEDDER, VECTOR_STORE, RERANKER and GENERATOR (see
src/providers/factory.py). With the defaults the in-memory store is empty, so the answer
says nothing was found. Read-only: never writes to the index.
"""

import argparse
import sys

from src.answering import answer_question
from src.models import Answer
from src.providers import factory


def print_answer(answer: Answer) -> None:
    print(answer.answer)
    print(f"\nGenerator: {answer.generator}")
    print("Citations:")
    for n, c in enumerate(answer.citations, 1):
        print(f"  [{n}] {c.product or c.file} | {c.section or '-'} | page {c.page} | {c.chunk_id}")
    print(f"\n{answer.disclaimer}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--doc-id", default=None, help="answer from one document only")
    args = parser.parse_args()

    embedder = factory.build_embedder()
    store = factory.build_store(embedder)
    answer = answer_question(
        args.question,
        embedder,
        store,
        factory.build_generator(),
        top_k=args.top_k,
        doc_id=args.doc_id,
        reranker=factory.build_reranker(),
    )
    print_answer(answer)
    return 0


if __name__ == "__main__":
    sys.exit(main())

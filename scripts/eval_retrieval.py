"""Run the retrieval question set against Pinecone and print hit@k and recall@k.

Usage (from the repo root):
    uv run --env-file .env python -m scripts.eval_retrieval [--k 5] [--namespace NAME] [--rerank]

Needs PINECONE_API_KEY and PINECONE_INDEX. Read-only: embeds the questions and queries.
With --rerank, makes one rerank request per question (free plan: 500 per month).
"""

import argparse
import sys
from pathlib import Path

from src.evaluation import load_questions, score
from src.indexing import search
from src.providers.pinecone import PineconeInferenceEmbedder, PineconeReranker, PineconeStore

QUESTIONS = Path("eval/retrieval_questions.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--namespace", default="", help="Pinecone namespace (default: default)")
    parser.add_argument("--rerank", action="store_true", help="rerank the top 50 vector hits")
    args = parser.parse_args()

    embedder = PineconeInferenceEmbedder.from_env()
    store = PineconeStore.from_env(embedder_name=embedder.name, namespace=args.namespace)
    reranker = PineconeReranker.from_env() if args.rerank else None
    results = []
    for question in load_questions(QUESTIONS):
        hits = search(
            question.question, embedder, store, args.k, question.doc_id, reranker=reranker
        )
        result = score(question, [h.chunk.chunk_id for h in hits], args.k)
        results.append(result)
        mark = "HIT " if result.hit else "miss"
        print(f"{mark} recall={result.recall:.2f}  {question.id}")
        for hit in hits:
            star = "*" if hit.chunk.chunk_id in question.expected else " "
            print(f"   {star} {hit.score:.4f}  {hit.chunk.chunk_id}  {hit.chunk.section or '-'}")
    hit_count = sum(r.hit for r in results)
    mean_recall = sum(r.recall for r in results) / len(results)
    print(f"\nhit@{args.k}: {hit_count}/{len(results)}  mean recall@{args.k}: {mean_recall:.2f}")
    if reranker:
        print(f"rerank requests: {reranker.requests_made} (free plan: 500/month)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

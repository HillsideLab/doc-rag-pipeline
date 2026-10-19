"""Answer the retrieval question set and count how many answers cite an expected chunk.

Usage (from the repo root):
    EMBEDDER=pinecone VECTOR_STORE=pinecone RERANKER=pinecone GENERATOR=stub \
        uv run --env-file .env python -m scripts.eval_answers [--top-k 5]

A question counts as cited when at least one expected chunk_id is among the answer's
citations; the cited share is the fraction of expected chunks cited. StubGenerator cites
every retrieved chunk, so with it these equal retrieval hit@k and recall@k.
Read-only. With Pinecone: one query embedding and (with RERANKER=pinecone) one rerank
request per question; usage is printed at the end.
"""

import argparse
import sys
from pathlib import Path

from scripts.ask import print_answer
from src.answering import answer_question
from src.evaluation import load_questions, score
from src.providers import factory

QUESTIONS = Path("eval/retrieval_questions.json")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    embedder = factory.build_embedder()
    store = factory.build_store(embedder)
    reranker = factory.build_reranker()
    generator = factory.build_generator()
    results = []
    for question in load_questions(QUESTIONS):
        answer = answer_question(
            question.question,
            embedder,
            store,
            generator,
            top_k=args.top_k,
            doc_id=question.doc_id,
            reranker=reranker,
        )
        cited = [c.chunk_id for c in answer.citations]
        result = score(question, cited, k=len(cited))
        results.append(result)
        print(f"\n=== {question.id}: {question.question}")
        print_answer(answer)
        mark = "CITED" if result.hit else "missed"
        print(f"-> {mark}: {result.recall:.2f} of expected chunks cited")
        for chunk_id in question.expected:
            print(f"   {'*' if chunk_id in cited else ' '} {chunk_id}")

    cited_count = sum(r.hit for r in results)
    mean_share = sum(r.recall for r in results) / len(results)
    print(
        f"\nAnswers citing an expected chunk: {cited_count}/{len(results)}  "
        f"mean share of expected chunks cited: {mean_share:.2f}  (top_k={args.top_k})"
    )
    if hasattr(embedder, "tokens_used"):
        print(f"embedding tokens: {embedder.tokens_used}")
    if reranker is not None and hasattr(reranker, "requests_made"):
        print(f"rerank requests: {reranker.requests_made} (free plan: 500/month)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

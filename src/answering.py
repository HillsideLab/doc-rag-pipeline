"""Answer a question: search (optionally reranked) -> generate -> answer with citations.

Provider-neutral, so the CLI and the API (M5) call the same function.
"""

from src.indexing import search
from src.models import Answer
from src.providers.base import Embedder, Generator, Reranker, VectorStore

# Added to every answer whatever the Generator, so it never depends on model output.
DISCLAIMER = (
    "This is a technical prototype that answers from public EMA product information. "
    "It is not medical advice and must not be used for clinical or treatment decisions."
)


def answer_question(
    question: str,
    embedder: Embedder,
    store: VectorStore,
    generator: Generator,
    top_k: int = 5,
    doc_id: str | None = None,
    reranker: Reranker | None = None,
) -> Answer:
    hits = search(question, embedder, store, top_k, doc_id, reranker=reranker)
    answer = generator.generate(question, hits)
    return answer.model_copy(update={"disclaimer": DISCLAIMER})

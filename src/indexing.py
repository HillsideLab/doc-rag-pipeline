"""Embed and index chunks, and search them. Provider-neutral: works with any Embedder/VectorStore.

The text that is embedded is "Product | section: body", because some chunks (e.g. the
continuation of 6.1 List of excipients on the next page) name neither their section nor the
product in the body, while questions usually name the product. The stored chunk keeps the
original body, which is what citations and answers show.
"""

import re

from src.models import Chunk, SearchHit
from src.providers.base import Embedder, Reranker, VectorStore

# How many vector hits the reranker reorders. One rerank request either way.
RERANK_CANDIDATES = 50

# A chunk can start with parent headings attached before its own heading (chunking rule 6),
# e.g. "6. PHARMACEUTICAL PARTICULARS 6.1 List of excipients ...", so the section is looked
# for near the start rather than only at position 0. Headings are at most 80 characters.
SECTION_SEARCH_CHARS = 200


# EMA names its product information PDFs "<product>-epar-product-information_en.pdf".
EMA_FILE_PATTERN = re.compile(r"^([a-z0-9]+)-epar-product-information", re.IGNORECASE)


def product_name(source_file: str) -> str:
    """Product name from an EMA file name ("cablivi-epar-..." -> "Cablivi"); "" otherwise.

    Other file names get no product name rather than a guess.
    """
    match = EMA_FILE_PATTERN.match(source_file)
    return match.group(1).capitalize() if match else ""


def embedding_text(chunk: Chunk, with_section: bool = True, with_product: bool = True) -> str:
    """Text sent to the embedder for one chunk: "Product | section: body"."""
    text = chunk.text
    if with_section and chunk.section and chunk.section not in text[:SECTION_SEARCH_CHARS]:
        text = f"{chunk.section}: {text}"
    product = product_name(chunk.source_file) if with_product else ""
    return f"{product} | {text}" if product else text


def index_document(
    doc_id: str,
    chunks: list[Chunk],
    embedder: Embedder,
    store: VectorStore,
    with_section: bool = True,
    with_product: bool = True,
) -> None:
    """Embed every chunk of one document and replace that document's chunks in the store."""
    if any(chunk.doc_id != doc_id for chunk in chunks):
        raise ValueError(f"all chunks must belong to doc_id={doc_id}")
    texts = [embedding_text(c, with_section, with_product) for c in chunks]
    vectors = embedder.embed_documents(texts)
    store.replace_document(doc_id, chunks, vectors)


def search(
    question: str,
    embedder: Embedder,
    store: VectorStore,
    top_k: int = 5,
    doc_id: str | None = None,
    reranker: Reranker | None = None,
    candidates: int = RERANK_CANDIDATES,
) -> list[SearchHit]:
    """Embed the question as a query and return the top_k chunks, best first.

    With a reranker, the top `candidates` vector hits are reordered by the reranker, which
    reads the question and each chunk together; the returned score is the reranker's.
    """
    vector = embedder.embed_query(question)
    if reranker is None:
        return store.query(vector, top_k=top_k, doc_id=doc_id)
    hits = store.query(vector, top_k=max(candidates, top_k), doc_id=doc_id)
    ranked = reranker.rerank(question, [embedding_text(h.chunk) for h in hits], top_n=top_k)
    return [SearchHit(chunk=hits[i].chunk, score=score) for i, score in ranked]

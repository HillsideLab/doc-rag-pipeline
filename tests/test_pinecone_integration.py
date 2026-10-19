"""Real Pinecone test. Opt-in: uv run --env-file .env pytest -m integration

Needs PINECONE_API_KEY and PINECONE_INDEX. Writes a few synthetic chunks to a separate
namespace and deletes that namespace at the end, so the main data is never touched.
Uses a few hundred embedding tokens (free plan: 5M per month).
"""

import os
import time
from collections.abc import Callable, Iterator

import pytest

from src.indexing import index_document, search
from src.models import Chunk
from src.providers.pinecone import PineconeInferenceEmbedder, PineconeStore

pytestmark = pytest.mark.integration

NAMESPACE = "integration-test"
DOC_ID = "it-doc"


def make_chunk(n: int, section: str, text: str) -> Chunk:
    return Chunk(
        chunk_id=f"{DOC_ID}:p1:c{n}",
        doc_id=DOC_ID,
        source_file="synthetic.pdf",
        page=1,
        chunk_type="text",
        section=section,
        text=text,
    )


CHUNKS = [
    make_chunk(0, "6.1 List of excipients", "Sucrose, sodium citrate, polysorbate 80."),
    make_chunk(1, "4.8 Undesirable effects", "Headache and nosebleed are very common."),
    make_chunk(2, "6.4 Special precautions for storage", "Store in a refrigerator."),
]


def wait_until(condition: Callable[[], bool], timeout_s: float = 60.0) -> None:
    """Pinecone is eventually consistent: writes can take a few seconds to be visible."""
    deadline = time.monotonic() + timeout_s
    while not condition():
        if time.monotonic() > deadline:
            raise AssertionError("Pinecone did not reach the expected state in time")
        time.sleep(2.0)


@pytest.fixture
def store_and_embedder() -> Iterator[tuple[PineconeStore, PineconeInferenceEmbedder]]:
    if not os.environ.get("PINECONE_API_KEY") or not os.environ.get("PINECONE_INDEX"):
        pytest.skip("set PINECONE_API_KEY and PINECONE_INDEX to run")
    embedder = PineconeInferenceEmbedder.from_env()
    store = PineconeStore.from_env(embedder_name=embedder.name, namespace=NAMESPACE)
    yield store, embedder
    store.index.delete_namespace(name=NAMESPACE)


def test_index_search_and_reindex_with_fewer_chunks(
    store_and_embedder: tuple[PineconeStore, PineconeInferenceEmbedder],
) -> None:
    store, embedder = store_and_embedder
    prefix = f"{DOC_ID}:"

    index_document(DOC_ID, CHUNKS, embedder, store)
    wait_until(lambda: len(store.list_ids(prefix)) == 3)
    wait_until(lambda: len(search("excipients", embedder, store, top_k=3)) == 3)

    hits = search("What are the excipients?", embedder, store, top_k=3, doc_id=DOC_ID)
    assert hits[0].chunk == CHUNKS[0]

    index_document(DOC_ID, CHUNKS[:1], embedder, store)
    wait_until(lambda: store.list_ids(prefix) == [CHUNKS[0].chunk_id])

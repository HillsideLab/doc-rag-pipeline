from pathlib import Path

import numpy as np
import pytest

from src.models import Chunk, ChunkType, SearchHit
from src.providers.base import EMBEDDING_DIM, Embedder, Extractor, Generator, VectorStore
from src.providers.fakes import (
    NO_ANSWER,
    FakeEmbedder,
    FakeExtractor,
    InMemoryStore,
    StubGenerator,
)


def make_chunk(chunk_id: str, page: int = 1, chunk_type: ChunkType = "text") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id="d",
        source_file="f.pdf",
        page=page,
        chunk_type=chunk_type,
        text=f"text of {chunk_id}",
    )


def unit(index: int, dim: int = 4) -> list[float]:
    vector = [0.0] * dim
    vector[index] = 1.0
    return vector


def test_fakes_satisfy_interfaces(sample_fixture_path: Path) -> None:
    assert isinstance(FakeExtractor(sample_fixture_path), Extractor)
    assert isinstance(FakeEmbedder(), Embedder)
    assert isinstance(InMemoryStore(), VectorStore)
    assert isinstance(StubGenerator(), Generator)


def test_fake_extractor_loads_fixture(sample_fixture_path: Path) -> None:
    doc = FakeExtractor(sample_fixture_path).extract("incoming/anything.pdf")
    assert doc.doc_id == "sample-doc"
    assert [p.page_number for p in doc.pages] == [1, 2]


def test_fake_embedder_is_deterministic_and_normalised() -> None:
    embedder = FakeEmbedder()
    first, second = embedder.embed_documents(["Headache is common", "Headache is common"])
    assert len(first) == EMBEDDING_DIM
    assert first == second
    assert np.linalg.norm(first) == pytest.approx(1.0)


def test_fake_embedder_ranks_related_text_higher() -> None:
    embedder = FakeEmbedder()
    query = np.array(embedder.embed_query("maximum daily dose"))
    related, unrelated = (
        np.array(v)
        for v in embedder.embed_documents(
            ["The maximum daily dose is eight tablets.", "Store below 25 degrees."]
        )
    )
    assert query @ related > query @ unrelated


def test_fake_embedder_handles_empty_text() -> None:
    assert FakeEmbedder().embed_query("") == [0.0] * EMBEDDING_DIM


def test_store_returns_top_k_best_first() -> None:
    store = InMemoryStore(dimension=4)
    store.upsert([make_chunk("a"), make_chunk("b"), make_chunk("c")], [unit(0), unit(1), unit(2)])
    hits = store.query([0.1, 1.0, 0.0, 0.0], top_k=2)
    assert [h.chunk.chunk_id for h in hits] == ["b", "a"]
    assert hits[0].score > hits[1].score


def test_store_upsert_replaces_same_id() -> None:
    store = InMemoryStore(dimension=4)
    store.upsert([make_chunk("a")], [unit(0)])
    store.upsert([make_chunk("a", page=2)], [unit(1)])
    hits = store.query(unit(1), top_k=10)
    assert len(hits) == 1
    assert hits[0].chunk.page == 2


def test_store_rejects_wrong_dimension() -> None:
    store = InMemoryStore(dimension=4)
    with pytest.raises(ValueError):
        store.upsert([make_chunk("a")], [[1.0, 0.0]])


def test_store_rejects_length_mismatch() -> None:
    store = InMemoryStore(dimension=4)
    with pytest.raises(ValueError):
        store.upsert([make_chunk("a"), make_chunk("b")], [unit(0)])


def test_empty_store_returns_no_hits() -> None:
    assert InMemoryStore(dimension=4).query(unit(0), top_k=3) == []


def test_stub_generator_deduplicates_citations() -> None:
    hits = [
        SearchHit(chunk=make_chunk("a", page=1), score=0.9),
        SearchHit(chunk=make_chunk("b", page=1), score=0.8),
        SearchHit(chunk=make_chunk("c", page=2, chunk_type="table"), score=0.7),
    ]
    answer = StubGenerator().generate("question", hits)
    assert [(c.page, c.chunk_type) for c in answer.citations] == [(1, "text"), (2, "table")]
    assert "text of a" in answer.answer


def test_stub_generator_without_hits() -> None:
    answer = StubGenerator().generate("question", [])
    assert answer.answer == NO_ANSWER
    assert answer.citations == []

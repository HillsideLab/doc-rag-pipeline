"""Pinecone embedder, reranker and store against small fakes of the SDK objects."""

from types import SimpleNamespace
from typing import Any

import pytest

from src.models import Chunk
from src.providers.base import Embedder, Reranker, VectorStore
from src.providers.pinecone import PineconeInferenceEmbedder, PineconeReranker, PineconeStore

DIM = 4


class FakeInference:
    """Stands in for `pc.inference`. Records every embed call."""

    def __init__(self, dimension: int = DIM) -> None:
        self.dimension = dimension
        self.calls: list[dict[str, Any]] = []

    def embed(self, model: str, inputs: list[str], parameters: dict[str, Any]) -> Any:
        self.calls.append({"model": model, "inputs": list(inputs), "parameters": parameters})
        data = [SimpleNamespace(values=[float(len(text))] * self.dimension) for text in inputs]
        return SimpleNamespace(data=data, usage=SimpleNamespace(total_tokens=len(inputs)))

    def rerank(self, **kwargs: Any) -> Any:
        """Scores each document by its length, longest first, like the real ordering."""
        self.calls.append(kwargs)
        ranked = sorted(enumerate(kwargs["documents"]), key=lambda pair: -len(pair[1]))
        data = [SimpleNamespace(index=i, score=len(doc) / 10) for i, doc in ranked]
        return SimpleNamespace(data=data[: kwargs["top_n"]])


class FakeIndex:
    """Stands in for `pc.Index(...)`: records in a dict, one namespace, call log in order."""

    def __init__(self, list_page_size: int = 2) -> None:
        self.records: dict[str, dict[str, Any]] = {}
        self.list_page_size = list_page_size
        self.log: list[str] = []
        self.query_calls: list[dict[str, Any]] = []

    def upsert(self, vectors: list[dict[str, Any]], namespace: str, show_progress: bool) -> None:
        self.log.append(f"upsert {len(vectors)}")
        for record in vectors:
            self.records[record["id"]] = record

    def delete(self, ids: list[str], namespace: str) -> None:
        self.log.append(f"delete {sorted(ids)}")
        for record_id in ids:
            self.records.pop(record_id, None)

    def list(self, prefix: str, namespace: str) -> Any:
        self.log.append(f"list {prefix}")
        ids = sorted(i for i in self.records if i.startswith(prefix))
        for start in range(0, len(ids), self.list_page_size):
            page = ids[start : start + self.list_page_size]
            yield SimpleNamespace(vectors=[SimpleNamespace(id=i) for i in page])

    def query(self, **kwargs: Any) -> Any:
        self.query_calls.append(kwargs)
        doc_filter = kwargs["filter"]
        matches = [
            SimpleNamespace(id=r["id"], score=0.5, metadata=r["metadata"])
            for r in self.records.values()
            if doc_filter is None or r["metadata"]["doc_id"] == doc_filter["doc_id"]["$eq"]
        ]
        return SimpleNamespace(matches=matches[: kwargs["top_k"]])


def make_chunk(chunk_id: str, doc_id: str = "d", page: int = 1) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        source_file="f.pdf",
        page=page,
        chunk_type="table",
        section="6.1 List of excipients",
        text=f"text of {chunk_id}",
    )


def vec(value: float = 1.0) -> list[float]:
    return [value] * DIM


def test_providers_satisfy_interfaces() -> None:
    assert isinstance(PineconeInferenceEmbedder(FakeInference()), Embedder)
    assert isinstance(PineconeStore(FakeIndex(), embedder_name="m", dimension=DIM), VectorStore)


def test_embedder_uses_passage_and_query_input_types() -> None:
    inference = FakeInference()
    embedder = PineconeInferenceEmbedder(inference, model="llama-text-embed-v2", dimension=DIM)
    embedder.embed_documents(["a"])
    embedder.embed_query("q")
    assert [c["parameters"]["input_type"] for c in inference.calls] == ["passage", "query"]
    assert inference.calls[0]["parameters"]["dimension"] == DIM
    assert inference.calls[0]["parameters"]["truncate"] == "END"
    assert inference.calls[0]["model"] == "llama-text-embed-v2"


def test_embedder_splits_into_batches_and_keeps_order() -> None:
    inference = FakeInference()
    embedder = PineconeInferenceEmbedder(inference, dimension=DIM, batch_size=2)
    vectors = embedder.embed_documents(["a", "bb", "ccc", "dddd", "eeeee"])
    assert [len(c["inputs"]) for c in inference.calls] == [2, 2, 1]
    assert [v[0] for v in vectors] == [1.0, 2.0, 3.0, 4.0, 5.0]
    assert embedder.tokens_used == 5


def test_reranker_satisfies_interface_and_maps_results() -> None:
    inference = FakeInference()
    reranker = PineconeReranker(inference)
    assert isinstance(reranker, Reranker)

    ranked = reranker.rerank("q", ["aa", "aaaa", "a"], top_n=2)

    assert ranked == [(1, 0.4), (0, 0.2)]
    call = inference.calls[-1]
    assert call["model"] == "bge-reranker-v2-m3"
    assert call["parameters"] == {"truncate": "END"}
    assert call["return_documents"] is False
    assert reranker.requests_made == 1


def test_reranker_with_no_documents_makes_no_request() -> None:
    inference = FakeInference()
    assert PineconeReranker(inference).rerank("q", [], top_n=5) == []
    assert inference.calls == []


def test_embedder_batches_by_length_but_returns_input_order() -> None:
    inference = FakeInference()
    embedder = PineconeInferenceEmbedder(inference, dimension=DIM, batch_size=2)
    vectors = embedder.embed_documents(["cccc", "a", "dddddd", "bb"])
    assert [c["inputs"] for c in inference.calls] == [["a", "bb"], ["cccc", "dddddd"]]
    assert [v[0] for v in vectors] == [4.0, 1.0, 6.0, 2.0]


def test_estimate_tokens_counts_each_batch_at_its_longest_input() -> None:
    embedder = PineconeInferenceEmbedder(FakeInference(), dimension=DIM, batch_size=2)
    # batches by length: ["one", "two words"] -> 2 x 2 words, ["three words here"] -> 1 x 3
    estimate = embedder.estimate_tokens(["three words here", "one", "two words"])
    assert estimate == int((2 * 2 + 1 * 3) * 1.7)


def test_embedder_rejects_wrong_dimension() -> None:
    embedder = PineconeInferenceEmbedder(FakeInference(dimension=3), dimension=DIM)
    with pytest.raises(ValueError):
        embedder.embed_query("q")


def test_upsert_stores_chunk_id_and_metadata() -> None:
    index = FakeIndex()
    PineconeStore(index, embedder_name="llama-text-embed-v2", dimension=DIM).upsert(
        [make_chunk("d:p10:c4")], [vec()]
    )
    record = index.records["d:p10:c4"]
    assert record["values"] == vec()
    assert record["metadata"] == {
        "doc_id": "d",
        "source_file": "f.pdf",
        "page": 1,
        "chunk_type": "table",
        "section": "6.1 List of excipients",
        "text": "text of d:p10:c4",
        "embedder": "llama-text-embed-v2",
    }


def test_upsert_rejects_wrong_dimension() -> None:
    with pytest.raises(ValueError):
        PineconeStore(FakeIndex(), embedder_name="m", dimension=DIM).upsert(
            [make_chunk("a")], [[1.0]]
        )


def test_replace_document_lists_upserts_then_deletes_only_stale_ids() -> None:
    index = FakeIndex()
    store = PineconeStore(index, embedder_name="m", dimension=DIM)
    old = [make_chunk(f"d:p1:c{i}") for i in range(3)]
    store.upsert(old + [make_chunk("e:p1:c0", doc_id="e")], [vec()] * 4)
    index.log.clear()

    store.replace_document("d", old[:1], [vec(2.0)])

    assert index.log == ["list d:", "upsert 1", "delete ['d:p1:c1', 'd:p1:c2']"]
    assert sorted(index.records) == ["d:p1:c0", "e:p1:c0"]
    assert index.records["d:p1:c0"]["values"] == vec(2.0)


def test_replace_document_with_nothing_stale_does_not_delete() -> None:
    index = FakeIndex()
    store = PineconeStore(index, embedder_name="m", dimension=DIM)
    store.replace_document("d", [make_chunk("d:p1:c0")], [vec()])
    assert index.log == ["list d:", "upsert 1"]


def test_query_filters_by_doc_id_and_rebuilds_chunks() -> None:
    index = FakeIndex()
    store = PineconeStore(index, embedder_name="m", dimension=DIM)
    store.upsert([make_chunk("d:p2:c0", page=2), make_chunk("e:p1:c0", doc_id="e")], [vec()] * 2)
    # Pinecone returns metadata numbers as floats.
    index.records["d:p2:c0"]["metadata"]["page"] = 2.0

    hits = store.query(vec(), top_k=5, doc_id="d")

    assert index.query_calls[-1]["filter"] == {"doc_id": {"$eq": "d"}}
    assert index.query_calls[-1]["include_metadata"] is True
    assert [h.chunk for h in hits] == [make_chunk("d:p2:c0", page=2)]
    assert hits[0].score == 0.5


def test_query_without_doc_id_sends_no_filter() -> None:
    index = FakeIndex()
    PineconeStore(index, embedder_name="m", dimension=DIM).query(vec(), top_k=3)
    assert index.query_calls[-1]["filter"] is None


@pytest.mark.parametrize("missing", ["PINECONE_API_KEY", "PINECONE_INDEX"])
def test_from_env_names_the_missing_variable(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.setenv("PINECONE_API_KEY", "dummy-not-a-real-key")
    monkeypatch.setenv("PINECONE_INDEX", "some-index")
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError, match=f"Set {missing} in .env"):
        PineconeStore.from_env(embedder_name="m")

import pytest

from src.chunking import chunk_document
from src.indexing import embedding_text, index_document, product_name, search
from src.models import Chunk, ExtractedDocument
from src.providers.fakes import FakeEmbedder, InMemoryStore


def make_chunk(text: str, section: str = "", chunk_id: str = "d:p1:c0") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id="d",
        source_file="f.pdf",
        page=1,
        chunk_type="text",
        section=section,
        text=text,
    )


def test_embedding_text_prefixes_section() -> None:
    chunk = make_chunk("Trisodium citrate dihydrate", section="6.1 List of excipients")
    assert embedding_text(chunk) == "6.1 List of excipients: Trisodium citrate dihydrate"


def test_embedding_text_does_not_repeat_heading_already_in_body() -> None:
    chunk = make_chunk("6.1 List of excipients\nSucrose", section="6.1 List of excipients")
    assert embedding_text(chunk) == chunk.text


def test_embedding_text_does_not_repeat_heading_after_attached_parent_heading() -> None:
    chunk = make_chunk(
        "6. PHARMACEUTICAL PARTICULARS 6.1 List of excipients Powder Sucrose",
        section="6.1 List of excipients",
    )
    assert embedding_text(chunk) == chunk.text


def test_embedding_text_without_section() -> None:
    assert embedding_text(make_chunk("Body only")) == "Body only"
    chunk = make_chunk("Sucrose", section="6.1 List of excipients")
    assert embedding_text(chunk, with_section=False) == "Sucrose"


@pytest.mark.parametrize(
    ("source_file", "expected"),
    [
        ("cablivi-epar-product-information_en.pdf", "Cablivi"),
        ("AUBAGIO-EPAR-product-information_en.pdf", "Aubagio"),
        ("leaflet.pdf", ""),
        ("f.pdf", ""),
    ],
)
def test_product_name_from_ema_file_name(source_file: str, expected: str) -> None:
    assert product_name(source_file) == expected


def test_embedding_text_prefixes_product_and_section() -> None:
    chunk = make_chunk("Trisodium citrate", section="6.1 List of excipients").model_copy(
        update={"source_file": "cablivi-epar-product-information_en.pdf"}
    )
    assert embedding_text(chunk) == "Cablivi | 6.1 List of excipients: Trisodium citrate"
    assert embedding_text(chunk, with_product=False) == "6.1 List of excipients: Trisodium citrate"
    assert embedding_text(chunk, with_section=False) == "Cablivi | Trisodium citrate"


class ReverseReranker:
    """Puts the vector hits in reverse order, so the effect of reranking is visible."""

    name = "reverse"

    def __init__(self) -> None:
        self.documents: list[str] = []

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        self.documents = documents
        order = list(reversed(range(len(documents))))[:top_n]
        return [(i, float(rank)) for rank, i in enumerate(order)]


def test_search_with_reranker_reorders_the_candidates() -> None:
    embedder, store = FakeEmbedder(), InMemoryStore()
    chunks = [make_chunk(f"dose {'x ' * i}", chunk_id=f"d:p1:c{i}") for i in range(4)]
    index_document("d", chunks, embedder, store)
    plain = search("dose", embedder, store, top_k=4)
    reranker = ReverseReranker()

    reranked = search("dose", embedder, store, top_k=2, reranker=reranker, candidates=4)

    assert len(reranker.documents) == 4
    assert [h.chunk.chunk_id for h in reranked] == [h.chunk.chunk_id for h in plain[::-1][:2]]
    assert [h.score for h in reranked] == [0.0, 1.0]


def test_reindexing_with_fewer_chunks_leaves_no_old_chunks() -> None:
    embedder, store = FakeEmbedder(), InMemoryStore()
    first = [make_chunk(f"text {i}", chunk_id=f"d:p1:c{i}") for i in range(3)]
    index_document("d", first, embedder, store)
    index_document("d", first[:1], embedder, store)
    hits = search("text", embedder, store, top_k=10)
    assert [h.chunk.chunk_id for h in hits] == ["d:p1:c0"]


def test_index_document_rejects_chunks_of_another_document() -> None:
    with pytest.raises(ValueError):
        index_document("other", [make_chunk("x")], FakeEmbedder(), InMemoryStore())


def test_search_can_filter_by_doc_id(sample_doc: ExtractedDocument) -> None:
    embedder, store = FakeEmbedder(), InMemoryStore()
    chunks = chunk_document(sample_doc)
    index_document(sample_doc.doc_id, chunks, embedder, store)
    other = make_chunk("What is the maximum daily dose?").model_copy(
        update={"doc_id": "other", "chunk_id": "other:p1:c0"}
    )
    index_document("other", [other], embedder, store)

    hits = search("maximum daily dose", embedder, store, top_k=3, doc_id=sample_doc.doc_id)

    assert hits
    assert all(h.chunk.doc_id == sample_doc.doc_id for h in hits)

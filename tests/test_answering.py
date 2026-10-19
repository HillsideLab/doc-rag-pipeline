from src.answering import DISCLAIMER, answer_question
from src.citations import citation_for, source_label
from src.models import Chunk
from src.providers.fakes import NO_ANSWER, FakeEmbedder, InMemoryStore, StubGenerator

CABLIVI = "cablivi-epar-product-information_en.pdf"


def make_chunk(chunk_id: str, text: str, doc_id: str = "d", section: str = "") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        source_file=CABLIVI,
        page=int(chunk_id.split(":p")[1].split(":")[0]),
        chunk_type="text",
        section=section,
        text=text,
    )


def make_store(chunks: list[Chunk]) -> tuple[FakeEmbedder, InMemoryStore]:
    embedder = FakeEmbedder()
    store = InMemoryStore()
    store.upsert(chunks, embedder.embed_documents([c.text for c in chunks]))
    return embedder, store


class ReverseReranker:
    """Puts the vector hits in reverse order, to show the reranker's order is used."""

    name = "reverse"

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        return [(i, 1.0) for i in reversed(range(len(documents)))][:top_n]


def test_citation_carries_product_section_page_and_chunk_id() -> None:
    chunk = make_chunk("d:p10:c4", "Sucrose", section="6.1 List of excipients")
    citation = citation_for(chunk)
    assert citation.chunk_id == "d:p10:c4"
    assert citation.product == "Cablivi"
    assert citation.section == "6.1 List of excipients"
    assert citation.page == 10
    assert citation.file == CABLIVI
    assert source_label(chunk) == "Cablivi, 6.1 List of excipients, page 10 (chunk d:p10:c4)"


def test_source_label_without_product_or_section() -> None:
    chunk = make_chunk("d:p2:c0", "Body").model_copy(update={"source_file": "f.pdf"})
    assert source_label(chunk) == "f.pdf, page 2 (chunk d:p2:c0)"


def test_answer_cites_top_k_chunks_and_adds_disclaimer() -> None:
    embedder, store = make_store(
        [
            make_chunk("d:p1:c0", "The maximum daily dose is eight tablets."),
            make_chunk("d:p2:c0", "Store below 25 degrees."),
            make_chunk("d:p3:c0", "Headache is common."),
        ]
    )
    answer = answer_question("maximum daily dose", embedder, store, StubGenerator(), top_k=2)
    assert len(answer.citations) == 2
    assert answer.citations[0].chunk_id == "d:p1:c0"
    assert answer.generator == "stub"
    assert answer.disclaimer == DISCLAIMER
    assert "not medical advice" in answer.disclaimer


def test_answer_without_hits_still_has_disclaimer() -> None:
    answer = answer_question("anything", FakeEmbedder(), InMemoryStore(), StubGenerator())
    assert answer.answer == NO_ANSWER
    assert answer.citations == []
    assert answer.disclaimer == DISCLAIMER


def test_answer_filters_by_doc_id() -> None:
    embedder, store = make_store(
        [make_chunk("x:p1:c0", "dose", doc_id="x"), make_chunk("y:p1:c0", "dose", doc_id="y")]
    )
    answer = answer_question("dose", embedder, store, StubGenerator(), doc_id="y")
    assert [c.chunk_id for c in answer.citations] == ["y:p1:c0"]


def test_answer_uses_reranker_order() -> None:
    embedder, store = make_store(
        [make_chunk("d:p1:c0", "dose dose dose"), make_chunk("d:p2:c0", "dose and storage")]
    )
    answer = answer_question(
        "dose", embedder, store, StubGenerator(), top_k=2, reranker=ReverseReranker()
    )
    assert [c.chunk_id for c in answer.citations] == ["d:p2:c0", "d:p1:c0"]

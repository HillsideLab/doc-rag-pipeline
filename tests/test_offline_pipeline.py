"""End-to-end run of extract -> chunk -> embed -> index -> query -> answer, using fakes only."""

import pytest

from src.answering import answer_question
from src.chunking import chunk_document
from src.indexing import index_document
from src.models import ExtractedDocument
from src.providers.fakes import FakeEmbedder, InMemoryStore, StubGenerator


@pytest.mark.parametrize(
    ("question", "expected_page", "expected_type"),
    [
        ("What is the maximum daily dose?", 1, "text"),
        ("How common are headache and nausea?", 2, "table"),
    ],
)
def test_question_is_answered_with_page_citation(
    sample_doc: ExtractedDocument, question: str, expected_page: int, expected_type: str
) -> None:
    embedder = FakeEmbedder()
    store = InMemoryStore()
    index_document(sample_doc.doc_id, chunk_document(sample_doc), embedder, store)

    answer = answer_question(question, embedder, store, StubGenerator(), top_k=1)

    citation = answer.citations[0]
    assert citation.file == "sample_smpc.pdf"
    assert citation.page == expected_page
    assert citation.chunk_type == expected_type
    assert citation.chunk_id.startswith(f"{sample_doc.doc_id}:p{expected_page}:")
    assert answer.disclaimer

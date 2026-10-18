"""End-to-end run of extract -> chunk -> embed -> index -> query -> answer, using fakes only."""

import pytest

from src.chunking import chunk_document
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
    chunks = chunk_document(sample_doc)
    store.upsert(chunks, embedder.embed_documents([c.text for c in chunks]))

    hits = store.query(embedder.embed_query(question), top_k=1)
    answer = StubGenerator().generate(question, hits)

    assert answer.citations[0].file == "sample_smpc.pdf"
    assert answer.citations[0].page == expected_page
    assert answer.citations[0].chunk_type == expected_type

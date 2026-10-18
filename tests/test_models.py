import pytest
from pydantic import ValidationError

from src.models import Chunk, DocumentStatus, Page


def test_page_number_starts_at_one() -> None:
    with pytest.raises(ValidationError):
        Page(page_number=0)


def test_chunk_type_must_be_text_or_table() -> None:
    with pytest.raises(ValidationError):
        Chunk(
            chunk_id="d:p1:c0",
            doc_id="d",
            source_file="f.pdf",
            page=1,
            chunk_type="image",
            text="x",
        )


def test_document_status_values_match_spec() -> None:
    assert [s.value for s in DocumentStatus] == [
        "RECEIVED",
        "EXTRACTING",
        "CHUNKED",
        "INDEXED",
        "FAILED",
    ]

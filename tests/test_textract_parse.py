import json
from pathlib import Path
from typing import Any

import pytest

from src.chunking import chunk_document
from src.models import ExtractedDocument
from src.providers.textract_parse import textract_to_document

FIXTURE = Path(__file__).parent / "fixtures" / "textract_layout_sample.json"


@pytest.fixture
def raw() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def doc(raw: dict[str, Any]) -> ExtractedDocument:
    return textract_to_document(raw, doc_id="abc", source_file="leaflet.pdf")


def line_texts(doc: ExtractedDocument, page_number: int) -> list[str]:
    return [line.text for line in doc.pages[page_number - 1].lines]


def test_every_page_is_kept_in_order(doc: ExtractedDocument) -> None:
    assert doc.doc_id == "abc"
    assert doc.source_file == "leaflet.pdf"
    assert [page.page_number for page in doc.pages] == [1, 2, 3]


def test_lines_follow_layout_reading_order_not_top(doc: ExtractedDocument) -> None:
    # The left column is read fully before the right column.
    assert line_texts(doc, 1) == [
        "Package leaflet: information for the user",
        "Read all of this leaflet carefully",
        "before you start taking this medicine.",
        "2. What you need to know",
        "Do not take Examplamol if you are allergic.",
    ]


def test_title_and_section_header_are_marked_as_headings(doc: ExtractedDocument) -> None:
    headings = [line.text for line in doc.pages[0].lines if line.is_heading]
    assert headings == ["Package leaflet: information for the user", "2. What you need to know"]


def test_header_footer_and_page_number_are_dropped(doc: ExtractedDocument) -> None:
    all_text = [line.text for page in doc.pages for line in page.lines]
    assert "Examplamol leaflet - synthetic example" not in all_text
    assert "Synthetic document for tests" not in all_text
    assert "1" not in all_text


def test_line_outside_layout_is_appended_last(doc: ExtractedDocument) -> None:
    assert line_texts(doc, 2) == ["Swallow the tablet with water.", "Stray note at the bottom"]


def test_empty_page_and_no_tables(doc: ExtractedDocument) -> None:
    assert doc.pages[2].lines == []
    assert all(page.tables == [] for page in doc.pages)


def test_geometry_is_copied(doc: ExtractedDocument) -> None:
    first = doc.pages[1].lines[0]
    assert (first.top, first.height) == (0.1, 0.02)


def test_list_children_are_not_duplicated() -> None:
    # LAYOUT_LIST points at LAYOUT_TEXT blocks, which also appear on their own.
    box = {"BoundingBox": {"Top": 0.1, "Left": 0.1, "Width": 0.5, "Height": 0.02}}
    raw = {
        "Blocks": [
            {"BlockType": "PAGE", "Id": "p", "Page": 1, "Geometry": box},
            {"BlockType": "LINE", "Id": "l", "Page": 1, "Text": "- item", "Geometry": box},
            {
                "BlockType": "LAYOUT_LIST",
                "Id": "list",
                "Page": 1,
                "Geometry": box,
                "Relationships": [{"Type": "CHILD", "Ids": ["t"]}],
            },
            {
                "BlockType": "LAYOUT_TEXT",
                "Id": "t",
                "Page": 1,
                "Geometry": box,
                "Relationships": [{"Type": "CHILD", "Ids": ["l"]}],
            },
        ]
    }
    doc = textract_to_document(raw, doc_id="d", source_file="f.pdf")
    assert line_texts(doc, 1) == ["- item"]


def test_parsed_document_chunks_with_layout_sections(doc: ExtractedDocument) -> None:
    sections = [chunk.section for chunk in chunk_document(doc) if chunk.page == 1]
    assert sections == ["Package leaflet: information for the user", "2. What you need to know"]

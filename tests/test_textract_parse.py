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
        "Examplamol leaflet - synthetic example",
        "Package leaflet: information for the user",
        "Read all of this leaflet carefully",
        "before you start taking this medicine.",
        "2. What you need to know",
        "Do not take Examplamol if you are allergic.",
    ]


def test_title_and_section_header_are_marked_as_headings(doc: ExtractedDocument) -> None:
    headings = [line.text for line in doc.pages[0].lines if line.is_heading]
    assert headings == ["Package leaflet: information for the user", "2. What you need to know"]


def test_lines_of_one_heading_block_are_joined(doc: ExtractedDocument) -> None:
    # Textract returns "2." and "What you need to know" as two LINEs in one header block.
    heading = next(line for line in doc.pages[0].lines if line.text.startswith("2."))
    assert heading.text == "2. What you need to know"
    assert heading.top == 0.15
    assert heading.height == pytest.approx(0.022)  # spans both lines (0.151 + 0.021 - 0.15)


def test_page_number_is_dropped_but_header_and_footer_are_kept(doc: ExtractedDocument) -> None:
    # Textract labels real content as LAYOUT_HEADER / LAYOUT_FOOTER (e.g. cover pages).
    all_text = [line.text for page in doc.pages for line in page.lines]
    assert "1" not in all_text
    assert "Examplamol leaflet - synthetic example" in all_text
    assert "Synthetic document for tests" in all_text


def test_line_outside_layout_is_appended_last(doc: ExtractedDocument) -> None:
    assert line_texts(doc, 2) == [
        "Swallow the tablet with water.",
        "Synthetic document for tests",
        "Stray note at the bottom",
    ]


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


def line_block(block_id: str, page: int, text: str, top: float) -> dict[str, Any]:
    box = {"BoundingBox": {"Top": top, "Left": 0.1, "Width": 0.5, "Height": 0.02}}
    return {"BlockType": "LINE", "Id": block_id, "Page": page, "Text": text, "Geometry": box}


def layout_block(block_type: str, block_id: str, page: int, ids: list[str]) -> dict[str, Any]:
    box = {"BoundingBox": {"Top": 0.1, "Left": 0.1, "Width": 0.5, "Height": 0.02}}
    return {
        "BlockType": block_type,
        "Id": block_id,
        "Page": page,
        "Geometry": box,
        "Relationships": [{"Type": "CHILD", "Ids": ids}],
    }


def page_block(page: int) -> dict[str, Any]:
    box = {"BoundingBox": {"Top": 0.0, "Left": 0.0, "Width": 1.0, "Height": 1.0}}
    return {"BlockType": "PAGE", "Id": f"page-{page}", "Page": page, "Geometry": box}


def cover_then_body() -> dict[str, Any]:
    """Page 1: a cover labelled as a footer, plus a page number. Page 2: three body lines."""
    return {
        "Blocks": [
            page_block(1),
            line_block("cover", 1, "A. LABELLING", 0.416),
            line_block("pn", 1, "17", 0.95),
            layout_block("LAYOUT_FOOTER", "y-cover", 1, ["cover"]),
            layout_block("LAYOUT_PAGE_NUMBER", "y-pn", 1, ["pn"]),
            page_block(2),
            line_block("b1", 2, "Outer carton text.", 0.1),
            line_block("b2", 2, "Store in a refrigerator.", 0.125),
            line_block("b3", 2, "Keep out of reach of children.", 0.15),
            layout_block("LAYOUT_TEXT", "y-body", 2, ["b1", "b2", "b3"]),
        ]
    }


def test_lines_on_cover_page_become_headings() -> None:
    doc = textract_to_document(cover_then_body(), doc_id="d", source_file="f.pdf")
    # The page number does not count, so page 1 has one line: a cover.
    assert [(line.text, line.is_heading) for line in doc.pages[0].lines] == [("A. LABELLING", True)]
    assert not any(line.is_heading for line in doc.pages[1].lines)


def test_page_with_three_lines_is_not_a_cover(doc: ExtractedDocument) -> None:
    # Page 2 of the fixture has three ordinary lines.
    assert not any(line.is_heading for line in doc.pages[1].lines)


def test_cover_heading_joins_next_chunk_and_sets_section() -> None:
    doc = textract_to_document(cover_then_body(), doc_id="d", source_file="f.pdf")
    chunks = chunk_document(doc)
    assert [(c.page, c.section) for c in chunks] == [(2, "A. LABELLING")]
    assert chunks[0].text.startswith("A. LABELLING Outer carton text.")


def test_parsed_document_chunks_with_layout_sections(doc: ExtractedDocument) -> None:
    sections = [chunk.section for chunk in chunk_document(doc) if chunk.page == 1]
    # The header line comes before the title, so it forms a chunk with no section.
    assert sections == ["", "Package leaflet: information for the user", "2. What you need to know"]

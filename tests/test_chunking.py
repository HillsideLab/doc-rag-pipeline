import pytest

from src.chunking import chunk_document
from src.models import ExtractedDocument, Line, Page, Table

LINE_HEIGHT = 0.02
SAME_PARAGRAPH_STEP = 0.025  # gap 0.005 < 0.5 * height
NEW_PARAGRAPH_STEP = 0.05  # gap 0.03 > 0.5 * height


def make_page(*paragraphs: list[str], page_number: int = 1) -> Page:
    """Build a page where each paragraph is a list of line texts."""
    lines: list[Line] = []
    top = 0.0
    for paragraph in paragraphs:
        for i, text in enumerate(paragraph):
            if lines:
                top += SAME_PARAGRAPH_STEP if i else NEW_PARAGRAPH_STEP
            lines.append(Line(text=text, top=top, height=LINE_HEIGHT))
    return Page(page_number=page_number, lines=lines)


def make_doc(*pages: Page) -> ExtractedDocument:
    return ExtractedDocument(doc_id="d", source_file="f.pdf", pages=list(pages))


def texts(doc: ExtractedDocument, **kwargs: int) -> list[str]:
    return [chunk.text for chunk in chunk_document(doc, **kwargs)]


def words(prefix: str, n: int) -> str:
    return " ".join(f"{prefix}{i}" for i in range(n))


def test_vertical_gap_separates_paragraphs() -> None:
    # Paragraph 1 is two lines (5 words); paragraph 2 starts after a larger gap.
    doc = make_doc(make_page(["a b c", "d e"], ["f g h"]))
    # Packing splits at the paragraph boundary, not after 6 words.
    assert texts(doc, max_tokens=6, overlap_tokens=0) == ["a b c d e", "f g h"]


def test_paragraphs_are_packed_with_overlap() -> None:
    doc = make_doc(make_page(["a b c"], ["d e f"]))
    assert texts(doc, max_tokens=5, overlap_tokens=1) == ["a b c", "c d e f"]


def test_small_paragraphs_share_one_chunk() -> None:
    doc = make_doc(make_page(["a b"], ["c d"]))
    assert texts(doc, max_tokens=10, overlap_tokens=2) == ["a b c d"]


def test_long_paragraph_is_split_by_words() -> None:
    doc = make_doc(make_page([words("w", 12)]))
    assert texts(doc, max_tokens=5, overlap_tokens=2) == [
        "w0 w1 w2 w3 w4",
        "w3 w4 w5 w6 w7",
        "w6 w7 w8 w9 w10",
        "w9 w10 w11",
    ]


def test_default_limit_is_500_words() -> None:
    doc = make_doc(make_page([words("w", 600)]))
    chunks = texts(doc)
    assert [len(c.split()) for c in chunks] == [500, 150]
    assert chunks[1].split()[:50] == chunks[0].split()[-50:]


def test_invalid_overlap_is_rejected() -> None:
    with pytest.raises(ValueError):
        chunk_document(make_doc(make_page(["a"])), max_tokens=5, overlap_tokens=5)


def test_heading_starts_new_chunk_and_sets_section() -> None:
    doc = make_doc(make_page(["Intro text"], ["4.2 Posology", "Take one tablet"], ["more"]))
    chunks = chunk_document(doc)
    assert [(c.section, c.text) for c in chunks] == [
        ("", "Intro text"),
        ("4.2 Posology", "4.2 Posology Take one tablet more"),
    ]


def test_line_marked_as_heading_starts_new_chunk_without_number() -> None:
    page = Page(
        page_number=1,
        lines=[
            Line(text="Intro text", top=0.0, height=LINE_HEIGHT),
            Line(text="Package leaflet", top=0.025, height=LINE_HEIGHT, is_heading=True),
            Line(text="Read all of this leaflet", top=0.05, height=LINE_HEIGHT),
        ],
    )
    chunks = chunk_document(make_doc(page))
    assert [(c.section, c.text) for c in chunks] == [
        ("", "Intro text"),
        ("Package leaflet", "Package leaflet Read all of this leaflet"),
    ]


def test_heading_only_chunk_is_prepended_to_next_chunk() -> None:
    doc = make_doc(make_page(["4. CLINICAL PARTICULARS"], ["4.1 Indications", "Adults only."]))
    chunks = chunk_document(doc)
    assert [(c.chunk_id, c.section, c.text) for c in chunks] == [
        ("d:p1:c0", "4.1 Indications", "4. CLINICAL PARTICULARS 4.1 Indications Adults only."),
    ]


def test_heading_only_chunk_moves_to_next_page() -> None:
    page_1 = Page(
        page_number=1,
        lines=[
            Line(text="Body text.", top=0.1, height=LINE_HEIGHT),
            Line(text="A. LABELLING", top=0.4, height=LINE_HEIGHT, is_heading=True),
        ],
    )
    doc = make_doc(page_1, make_page(["Carton text."], page_number=2))
    chunks = chunk_document(doc)
    assert [(c.chunk_id, c.page, c.section, c.text) for c in chunks] == [
        ("d:p1:c0", 1, "", "Body text."),
        ("d:p2:c0", 2, "A. LABELLING", "A. LABELLING Carton text."),
    ]


def test_heading_before_cover_page_stays_on_its_own_page() -> None:
    cover = Page(
        page_number=2,
        lines=[Line(text="A. LABELLING", top=0.4, height=LINE_HEIGHT, is_heading=True)],
    )
    doc = make_doc(
        make_page(["Body text."], ["3. To encourage reading"], page_number=1),
        cover,
        make_page(["Carton text."], page_number=3),
    )
    chunks = chunk_document(doc)
    assert [(c.chunk_id, c.section, c.text) for c in chunks] == [
        ("d:p1:c0", "", "Body text."),
        ("d:p1:c1", "3. To encourage reading", "3. To encourage reading"),
        ("d:p3:c0", "A. LABELLING", "A. LABELLING Carton text."),
    ]


def test_heading_with_short_body_stays_its_own_chunk() -> None:
    doc = make_doc(make_page(["6.2 Incompatibilities", "None known."], ["6.3 Shelf life"]))
    chunks = chunk_document(doc)
    # The last heading has nothing after it, so it is kept as it is.
    assert [c.text for c in chunks] == ["6.2 Incompatibilities None known.", "6.3 Shelf life"]


def test_lowercase_after_number_is_not_a_heading() -> None:
    doc = make_doc(make_page(["4.2 Posology"], ["2 tablets daily"]))
    chunks = chunk_document(doc)
    assert len(chunks) == 1
    assert chunks[0].section == "4.2 Posology"


def test_section_carries_over_to_next_page() -> None:
    doc = make_doc(
        make_page(["4.8 Undesirable effects", "Headache is common."], page_number=1),
        make_page(["continued text"], page_number=2),
    )
    chunks = chunk_document(doc)
    assert [(c.page, c.section) for c in chunks] == [
        (1, "4.8 Undesirable effects"),
        (2, "4.8 Undesirable effects"),
    ]


def test_chunks_never_cross_pages() -> None:
    doc = make_doc(make_page(["a b"], page_number=1), make_page(["c d"], page_number=2))
    chunks = chunk_document(doc, max_tokens=100, overlap_tokens=0)
    assert [(c.page, c.text) for c in chunks] == [(1, "a b"), (2, "c d")]


def test_table_is_one_markdown_chunk() -> None:
    page = make_page(["Some text"])
    page.tables.append(Table(rows=[["Reaction", "Frequency"], ["Head|ache", "Common"], ["Rash"]]))
    chunks = chunk_document(make_doc(page))
    table = chunks[-1]
    assert table.chunk_type == "table"
    assert table.text == (
        "| Reaction | Frequency |\n| --- | --- |\n| Head\\|ache | Common |\n| Rash |  |"
    )


def test_table_section_comes_from_heading_above_it(sample_doc: ExtractedDocument) -> None:
    tables = [c for c in chunk_document(sample_doc) if c.chunk_type == "table"]
    assert len(tables) == 1
    assert tables[0].page == 2
    assert tables[0].section == "4.8 Undesirable effects"


def test_chunk_ids_are_deterministic(sample_doc: ExtractedDocument) -> None:
    first = [c.chunk_id for c in chunk_document(sample_doc)]
    second = [c.chunk_id for c in chunk_document(sample_doc)]
    assert first == second
    assert first == [
        "sample-doc:p1:c0",
        "sample-doc:p1:c1",
        "sample-doc:p1:c2",
        "sample-doc:p2:c0",
        "sample-doc:p2:c1",
        "sample-doc:p2:c2",
        "sample-doc:p2:c3",
    ]


def test_empty_page_has_no_chunks() -> None:
    doc = make_doc(Page(page_number=1), make_page(["text"], page_number=2))
    assert [c.page for c in chunk_document(doc)] == [2]

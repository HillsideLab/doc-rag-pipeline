"""Convert a Textract AnalyzeDocument (LAYOUT) response into an ExtractedDocument.

Pure functions only (no boto3), so the conversion is unit-tested with small JSON fixtures.

Rules (see docs/ARCHITECTURE.md):
- Lines are ordered by LAYOUT blocks, which Textract returns in reading order. This keeps
  two-column pages readable. Lines outside every LAYOUT block are appended by `top`.
- The lines of one LAYOUT_TITLE / LAYOUT_SECTION_HEADER block are joined into one line with
  `is_heading=True`. Textract often splits "4.8 Undesirable effects" into "4.8" and
  "Undesirable effects"; joined, the heading becomes one chunk boundary and one `section`.
- Page numbers are dropped. Headers and footers are kept: Textract labelled real content as
  LAYOUT_HEADER / LAYOUT_FOOTER in the EMA documents (cover pages, list items near page edges).
- On a page with only one or two lines (page number excluded), those lines are headings.
  Such pages are covers like "A. LABELLING", which Textract tends to label as footers.
- Every PAGE block becomes a Page, even when empty, so page numbers never shift.
"""

from typing import Any

from src.models import ExtractedDocument, Line, Page

Block = dict[str, Any]

HEADING_LAYOUTS = {"LAYOUT_TITLE", "LAYOUT_SECTION_HEADER"}
DROPPED_LAYOUTS = {"LAYOUT_PAGE_NUMBER"}
# A page with at most this many lines (page number excluded) is a cover page.
COVER_PAGE_MAX_LINES = 2


def textract_to_document(raw: dict[str, Any], doc_id: str, source_file: str) -> ExtractedDocument:
    blocks: list[Block] = raw["Blocks"]
    by_id = {block["Id"]: block for block in blocks}
    page_numbers = sorted({_page_of(block) for block in blocks if block["BlockType"] == "PAGE"})
    pages = [_build_page(blocks, by_id, number) for number in page_numbers]
    return ExtractedDocument(doc_id=doc_id, source_file=source_file, pages=pages)


def _page_of(block: Block) -> int:
    # Async responses put "Page" on every block; single-page sync responses omit it.
    return block.get("Page", 1)


def _child_ids(block: Block) -> list[str]:
    ids: list[str] = []
    for relationship in block.get("Relationships", []):
        if relationship["Type"] == "CHILD":
            ids.extend(relationship["Ids"])
    return ids


def _to_line(block: Block, is_heading: bool) -> Line:
    box = block["Geometry"]["BoundingBox"]
    return Line(text=block["Text"], top=box["Top"], height=box["Height"], is_heading=is_heading)


def _merge_heading(children: list[Block]) -> Line:
    """Join a heading block's lines into one, e.g. "4.8" + "Undesirable effects"."""
    lines = [_to_line(child, is_heading=True) for child in children]
    top = min(line.top for line in lines)
    bottom = max(line.top + line.height for line in lines)
    text = " ".join(line.text for line in lines)
    return Line(text=text, top=top, height=bottom - top, is_heading=True)


def _build_page(blocks: list[Block], by_id: dict[str, Block], number: int) -> Page:
    on_page = [block for block in blocks if _page_of(block) == number]
    placed: set[str] = set()  # LINE ids already used (or dropped)
    lines: list[Line] = []

    for layout in on_page:
        layout_type = layout["BlockType"]
        if not layout_type.startswith("LAYOUT_"):
            continue
        children: list[Block] = []
        for child_id in _child_ids(layout):
            child = by_id.get(child_id)
            # LAYOUT_LIST points at LAYOUT_TEXT blocks, which are visited on their own.
            if child is None or child["BlockType"] != "LINE" or child_id in placed:
                continue
            placed.add(child_id)
            children.append(child)
        if not children or layout_type in DROPPED_LAYOUTS:
            continue
        if layout_type in HEADING_LAYOUTS:
            lines.append(_merge_heading(children))
        else:
            lines.extend(_to_line(child, is_heading=False) for child in children)

    orphans = [b for b in on_page if b["BlockType"] == "LINE" and b["Id"] not in placed]
    orphans.sort(key=lambda b: b["Geometry"]["BoundingBox"]["Top"])
    lines.extend(_to_line(block, is_heading=False) for block in orphans)

    if len(lines) <= COVER_PAGE_MAX_LINES:
        lines = [line.model_copy(update={"is_heading": True}) for line in lines]
    return Page(page_number=number, lines=lines)

"""Split an ExtractedDocument into chunks for embedding.

Rules (see docs/ARCHITECTURE.md):
- Chunks never cross pages, so every citation has an exact page number.
- Lines are grouped into paragraphs by vertical gap.
- A heading starts a new chunk and sets `section`: a line the extractor marked as a heading,
  or a numbered line such as "4.8 Undesirable effects".
- Paragraphs are packed up to `max_tokens` words, with `overlap_tokens` words repeated
  at the start of the next chunk. Tokens are approximated by whitespace-separated words.
- Each table is one chunk, rendered as Markdown, never split.
- A chunk that would hold only a heading is prepended to the next chunk instead. This is
  the one case where text from one page can end up in a chunk cited with the next page.
  It never happens across a cover page (a page that holds only headings).
"""

import re
from typing import NamedTuple

from src.models import Chunk, ChunkType, ExtractedDocument, Line, Table

HEADING_PATTERN = re.compile(r"^\d+(\.\d+)*\.?\s+[A-Z]")
MAX_HEADING_CHARS = 80
# A gap larger than this fraction of the previous line's height starts a new paragraph.
PARAGRAPH_GAP_RATIO = 0.5


class Piece(NamedTuple):
    """A chunk before its chunk_id is assigned."""

    page: int
    chunk_type: ChunkType
    section: str
    text: str
    on_cover: bool = False  # from a page that holds only headings, e.g. "A. LABELLING"


def chunk_document(
    doc: ExtractedDocument, max_tokens: int = 500, overlap_tokens: int = 50
) -> list[Chunk]:
    if max_tokens <= 0 or not 0 <= overlap_tokens < max_tokens:
        raise ValueError("need max_tokens > 0 and 0 <= overlap_tokens < max_tokens")

    pieces: list[Piece] = []
    section = ""  # carried over from previous pages until a new heading appears
    for page in doc.pages:
        page_start_section = section
        on_cover = bool(page.lines) and all(_is_heading(line) for line in page.lines)

        groups, section = _section_groups(page.lines, section)
        for group_section, paragraphs in groups:
            for text in _pack(paragraphs, max_tokens, overlap_tokens):
                pieces.append(Piece(page.page_number, "text", group_section, text, on_cover))

        for table in page.tables:
            if table.rows:
                table_section = _section_at(page.lines, table.top, page_start_section)
                pieces.append(
                    Piece(page.page_number, "table", table_section, _table_to_markdown(table))
                )

    chunks: list[Chunk] = []
    next_index: dict[int, int] = {}  # page -> next chunk number on that page
    for piece in _attach_lone_headings(pieces):
        index = next_index.get(piece.page, 0)
        next_index[piece.page] = index + 1
        chunks.append(
            Chunk(
                chunk_id=f"{doc.doc_id}:p{piece.page}:c{index}",
                doc_id=doc.doc_id,
                source_file=doc.source_file,
                page=piece.page,
                chunk_type=piece.chunk_type,
                section=piece.section,
                text=piece.text,
            )
        )
    return chunks


def _attach_lone_headings(pieces: list[Piece]) -> list[Piece]:
    """Prepend each heading-only piece to the next piece, even when that is on the next page.

    A heading directly followed by a sub-heading ("4. CLINICAL PARTICULARS" then "4.1 ...")
    would otherwise become a chunk with no content. The merged chunk keeps the page and
    section of the next piece, where the body text is.

    Headings never travel across a cover page: when a cover heading arrives, headings still
    waiting from an ordinary page stay on their own page as separate chunks. Otherwise the
    last heading of one part would be cited as the start of the next part.
    """
    result: list[Piece] = []
    waiting: list[Piece] = []
    for piece in pieces:
        if piece.chunk_type == "text" and piece.section and piece.text == piece.section:
            if piece.on_cover and any(not heading.on_cover for heading in waiting):
                result.extend(waiting)
                waiting = []
            waiting.append(piece)
            continue
        if waiting:
            headings = " ".join(heading.text for heading in waiting)
            separator = "\n\n" if piece.chunk_type == "table" else " "
            piece = piece._replace(text=headings + separator + piece.text)
            waiting = []
        result.append(piece)
    return result + waiting  # headings at the very end of the document stay on their own


def _is_heading(line: Line) -> bool:
    if line.is_heading:
        return True
    text = line.text.strip()
    return len(text) <= MAX_HEADING_CHARS and HEADING_PATTERN.match(text) is not None


def _starts_paragraph(previous: Line, line: Line) -> bool:
    gap = line.top - (previous.top + previous.height)
    return gap > PARAGRAPH_GAP_RATIO * previous.height


def _section_groups(lines: list[Line], section: str) -> tuple[list[tuple[str, list[str]]], str]:
    """Group a page's lines into paragraphs, and paragraphs into sections.

    Returns ([(section, paragraphs), ...], section in effect at the end of the page).
    """
    groups: list[tuple[str, list[str]]] = [(section, [])]
    paragraph: list[str] = []
    previous: Line | None = None
    for line in lines:
        if not line.text.strip():
            continue
        heading = _is_heading(line)
        new_paragraph = previous is not None and _starts_paragraph(previous, line)
        if paragraph and (heading or new_paragraph):
            groups[-1][1].append(" ".join(paragraph))
            paragraph = []
        if heading:
            groups.append((line.text.strip(), []))
        paragraph.append(line.text.strip())
        previous = line
    if paragraph:
        groups[-1][1].append(" ".join(paragraph))
    last_section = groups[-1][0]
    return [group for group in groups if group[1]], last_section


def _pack(paragraphs: list[str], max_tokens: int, overlap_tokens: int) -> list[str]:
    """Pack paragraphs into chunks of at most max_tokens words, with overlap."""
    chunks: list[str] = []
    current: list[str] = []
    fresh = 0  # words in `current` not already emitted in a previous chunk

    def overlap_tail(words: list[str]) -> list[str]:
        return words[-overlap_tokens:] if overlap_tokens else []

    for paragraph in paragraphs:
        words = paragraph.split()
        if fresh and len(current) + len(words) > max_tokens:
            chunks.append(" ".join(current))
            current = overlap_tail(current)
            fresh = 0
        current.extend(words)
        fresh += len(words)
        # A single paragraph longer than max_tokens is split by words.
        while len(current) > max_tokens:
            chunks.append(" ".join(current[:max_tokens]))
            current = current[max_tokens - overlap_tokens :]
            fresh = len(current) - overlap_tokens
    if fresh:
        chunks.append(" ".join(current))
    return chunks


def _section_at(lines: list[Line], top: float, section: str) -> str:
    """Section of the last heading above `top` on the page, else the carried-over section."""
    for line in lines:
        if line.top <= top and _is_heading(line):
            section = line.text.strip()
    return section


def _table_to_markdown(table: Table) -> str:
    rows = [[cell.strip().replace("|", "\\|") for cell in row] for row in table.rows]
    width = max(len(row) for row in rows)
    rows = [row + [""] * (width - len(row)) for row in rows]
    header, *body = rows
    lines = ["| " + " | ".join(header) + " |", "|" + " --- |" * width]
    lines += ["| " + " | ".join(row) + " |" for row in body]
    return "\n".join(lines)

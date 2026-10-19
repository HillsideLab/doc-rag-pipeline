"""Turn a retrieved chunk into a citation. Shared by every Generator so citations look the same."""

from src.indexing import product_name
from src.models import Chunk, Citation


def citation_for(chunk: Chunk) -> Citation:
    return Citation(
        chunk_id=chunk.chunk_id,
        file=chunk.source_file,
        product=product_name(chunk.source_file),
        section=chunk.section,
        page=chunk.page,
        chunk_type=chunk.chunk_type,
    )


def source_label(chunk: Chunk) -> str:
    """One-line label used in answers and prompts, e.g.
    "Cablivi, 6.1 List of excipients, page 10 (chunk d:p10:c4)"."""
    parts = [product_name(chunk.source_file) or chunk.source_file]
    if chunk.section:
        parts.append(chunk.section)
    parts.append(f"page {chunk.page}")
    return f"{', '.join(parts)} (chunk {chunk.chunk_id})"

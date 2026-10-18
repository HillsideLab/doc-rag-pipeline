"""Data models shared by every pipeline stage."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, Field

ChunkType = Literal["text", "table"]


class DocumentStatus(StrEnum):
    RECEIVED = "RECEIVED"
    EXTRACTING = "EXTRACTING"
    CHUNKED = "CHUNKED"
    INDEXED = "INDEXED"
    FAILED = "FAILED"


# --- Extraction output (provider-neutral; Textract JSON is converted into this) ---


class Line(BaseModel):
    """One line of text. `top` and `height` are relative to the page (0..1), as in Textract."""

    text: str
    top: float = Field(ge=0)
    height: float = Field(ge=0)


class Table(BaseModel):
    rows: list[list[str]]
    top: float = Field(default=0.0, ge=0)


class Page(BaseModel):
    page_number: int = Field(ge=1)
    lines: list[Line] = Field(default_factory=list)
    tables: list[Table] = Field(default_factory=list)


class ExtractedDocument(BaseModel):
    doc_id: str
    source_file: str
    pages: list[Page]


# --- Indexing and query ---


class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    source_file: str
    page: int = Field(ge=1)
    chunk_type: ChunkType
    section: str = ""
    text: str


class SearchHit(BaseModel):
    chunk: Chunk
    score: float


class Citation(BaseModel):
    file: str
    page: int
    chunk_type: ChunkType


class Answer(BaseModel):
    answer: str
    citations: list[Citation]

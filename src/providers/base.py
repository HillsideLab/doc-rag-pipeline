"""Interfaces for every external dependency (SPEC section 5).

Protocols use structural typing: a class satisfies an interface by having the right
methods, without inheriting from it. Fakes and real providers are interchangeable.
"""

from typing import Protocol, runtime_checkable

from src.models import Answer, Chunk, ExtractedDocument, SearchHit

# One index uses one embedder, and every embedder in this project outputs this size.
EMBEDDING_DIM = 1024


@runtime_checkable
class Extractor(Protocol):
    def extract(self, source: str) -> ExtractedDocument:
        """Extract text and tables from the document at `source` (an S3 key)."""
        ...


@runtime_checkable
class Embedder(Protocol):
    name: str
    dimension: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed chunks for indexing."""
        ...

    def embed_query(self, text: str) -> list[float]:
        """Embed a search question. Some providers embed queries differently from passages."""
        ...


@runtime_checkable
class VectorStore(Protocol):
    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        """Insert or replace chunks by chunk_id."""
        ...

    def query(self, vector: list[float], top_k: int) -> list[SearchHit]:
        """Return the top_k most similar chunks, best first."""
        ...


@runtime_checkable
class Generator(Protocol):
    def generate(self, question: str, hits: list[SearchHit]) -> Answer:
        """Answer the question from the retrieved chunks, with citations."""
        ...

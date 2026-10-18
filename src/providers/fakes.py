"""Offline implementations of the provider interfaces. Default in tests and local runs."""

import hashlib
import re
from pathlib import Path

import numpy as np

from src.models import Answer, Chunk, Citation, ExtractedDocument, SearchHit
from src.providers.base import EMBEDDING_DIM

NO_ANSWER = "No relevant passages were found."


class FakeExtractor:
    """Returns a fixed ExtractedDocument loaded from a JSON fixture, whatever the source."""

    def __init__(self, fixture_path: Path) -> None:
        self.fixture_path = fixture_path

    def extract(self, source: str) -> ExtractedDocument:
        return ExtractedDocument.model_validate_json(self.fixture_path.read_text())


class FakeEmbedder:
    """Deterministic bag-of-words embedder.

    Each word is hashed (sha256, stable across runs) into one of `dimension` buckets and
    counted; the vector is then L2-normalised. Texts sharing words get higher cosine
    similarity, which is enough to test retrieval without a model.
    """

    name = "fake-hash"

    def __init__(self, dimension: int = EMBEDDING_DIM) -> None:
        self.dimension = dimension

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)

    def _embed(self, text: str) -> list[float]:
        vector = np.zeros(self.dimension)
        for word in re.findall(r"\w+", text.lower()):
            digest = hashlib.sha256(word.encode()).digest()
            vector[int.from_bytes(digest[:8], "big") % self.dimension] += 1.0
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector /= norm
        return vector.tolist()


class InMemoryStore:
    """Vector store kept in a dict; search is brute-force cosine similarity with numpy."""

    def __init__(self, dimension: int = EMBEDDING_DIM) -> None:
        self.dimension = dimension
        self._chunks: dict[str, Chunk] = {}
        self._vectors: dict[str, np.ndarray] = {}

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        for chunk, vector in zip(chunks, vectors, strict=True):
            self._chunks[chunk.chunk_id] = chunk
            self._vectors[chunk.chunk_id] = self._as_array(vector)

    def query(self, vector: list[float], top_k: int) -> list[SearchHit]:
        if not self._vectors:
            return []
        query = self._as_array(vector)
        ids = list(self._vectors)
        matrix = np.stack([self._vectors[chunk_id] for chunk_id in ids])
        norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(query)
        scores = (matrix @ query) / np.where(norms == 0, 1.0, norms)
        best = np.argsort(-scores, kind="stable")[:top_k]
        return [SearchHit(chunk=self._chunks[ids[i]], score=float(scores[i])) for i in best]

    def _as_array(self, vector: list[float]) -> np.ndarray:
        array = np.asarray(vector, dtype=float)
        if array.shape != (self.dimension,):
            raise ValueError(f"expected vector of size {self.dimension}, got {array.shape}")
        return array


class StubGenerator:
    """Extractive answer: returns the top chunks' text with their citations. No LLM."""

    def __init__(self, max_chunks: int = 3, max_chars: int = 400) -> None:
        self.max_chunks = max_chunks
        self.max_chars = max_chars

    def generate(self, question: str, hits: list[SearchHit]) -> Answer:
        top = hits[: self.max_chunks]
        if not top:
            return Answer(answer=NO_ANSWER, citations=[])
        citations: list[Citation] = []
        for hit in top:
            citation = Citation(
                file=hit.chunk.source_file, page=hit.chunk.page, chunk_type=hit.chunk.chunk_type
            )
            if citation not in citations:
                citations.append(citation)
        answer = "\n\n".join(hit.chunk.text[: self.max_chars] for hit in top)
        return Answer(answer=answer, citations=citations)

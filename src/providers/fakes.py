"""Offline implementations of the provider interfaces. Default in tests and local runs."""

import hashlib
import re
from pathlib import Path

import numpy as np

from src.citations import citation_for, source_label
from src.models import Answer, Chunk, ExtractedDocument, SearchHit
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

    def replace_document(
        self, doc_id: str, chunks: list[Chunk], vectors: list[list[float]]
    ) -> None:
        new_ids = {chunk.chunk_id for chunk in chunks}
        stale = [
            chunk_id
            for chunk_id, chunk in self._chunks.items()
            if chunk.doc_id == doc_id and chunk_id not in new_ids
        ]
        self.upsert(chunks, vectors)
        for chunk_id in stale:
            del self._chunks[chunk_id]
            del self._vectors[chunk_id]

    def query(self, vector: list[float], top_k: int, doc_id: str | None = None) -> list[SearchHit]:
        query = self._as_array(vector)
        ids = [
            chunk_id
            for chunk_id, chunk in self._chunks.items()
            if doc_id is None or chunk.doc_id == doc_id
        ]
        if not ids:
            return []
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
    """Extractive answer with no generative model: every retrieved chunk is listed, best
    first, as "[n] source label" plus the start of its text. Citation n is passage [n].

    It lists all hits it receives (the caller's top_k decides how many), so the answer
    cites exactly the chunks that retrieval returned. It cannot judge whether the chunks
    answer the question; it says it found nothing only when there are no hits.
    """

    name = "stub"

    def __init__(self, max_chars: int = 400) -> None:
        self.max_chars = max_chars

    def generate(self, question: str, hits: list[SearchHit]) -> Answer:
        if not hits:
            return Answer(answer=NO_ANSWER, citations=[], generator=self.name)
        lines = [
            "No generative model was used. The passages below are copied from the "
            f"{len(hits)} retrieved chunks, best match first."
        ]
        for n, hit in enumerate(hits, 1):
            text = hit.chunk.text
            if len(text) > self.max_chars:
                text = text[: self.max_chars] + " ..."
            lines.append(f"[{n}] {source_label(hit.chunk)}\n{text}")
        return Answer(
            answer="\n\n".join(lines),
            citations=[citation_for(hit.chunk) for hit in hits],
            generator=self.name,
        )

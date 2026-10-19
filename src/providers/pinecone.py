"""Pinecone implementations of Embedder and Reranker (Inference API) and VectorStore (dense
serverless index).

The index doc-rag-mock is a plain dense index (1024 dimensions, cosine, no integrated
embedding model), so vectors are created with the Inference API and upserted as vectors.

The SDK objects (`pc.inference` and `pc.Index(...)`) are passed in, so tests use small fakes
and never touch the network. The API key is read only in `from_env` and is never stored,
logged, or put in an error message.
"""

import logging
import os
from typing import Any

from src.models import Chunk, SearchHit
from src.providers.base import EMBEDDING_DIM

logger = logging.getLogger(__name__)

# The embedding model has no default in code: one index uses one model, so the model name
# must come from PINECONE_EMBED_MODEL, like the index name (the index uses llama-text-embed-v2).
# Limits reported by the API for llama-text-embed-v2 (inference.get_model): 96 inputs per
# request, 2048 tokens per input. Upserts allow 1000 records / 2 MB; one chunk is ~15 KB.
EMBED_BATCH_SIZE = 96
# Measured on the SmPC chunks: the longest chunk is 497 words and 826 tokens. Estimate only.
TOKENS_PER_WORD = 1.7
UPSERT_BATCH_SIZE = 100
DELETE_BATCH_SIZE = 1000
# The rerank model has no default in code either: it comes from PINECONE_RERANK_MODEL.
# bge-reranker-v2-m3 (inference.get_model): 100 documents per request, 1024 tokens per
# question + document pair. Starter plan: 500 rerank requests per month, 60 per minute.


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Set {name} in .env")
    return value


def _client_from_env() -> Any:
    from pinecone import Pinecone  # imported here so unit tests never need the SDK client

    return Pinecone(api_key=_require_env("PINECONE_API_KEY"))


class PineconeInferenceEmbedder:
    """Embedder backed by Pinecone's hosted models. Passages and queries are embedded with
    different `input_type` values, as the model expects."""

    def __init__(
        self,
        inference: Any,
        model: str,
        dimension: int = EMBEDDING_DIM,
        batch_size: int = EMBED_BATCH_SIZE,
    ) -> None:
        self.inference = inference
        self.name = model
        self.dimension = dimension
        self.batch_size = batch_size
        self.tokens_used = 0  # for reporting usage against the free-plan token limit

    @classmethod
    def from_env(cls) -> "PineconeInferenceEmbedder":
        model = _require_env("PINECONE_EMBED_MODEL")  # checked before any client is created
        return cls(_client_from_env().inference, model=model)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Embed in batches of similar length, then return the vectors in the input order.

        Pinecone counts every input in a request as long as the longest one (measured:
        a 9-token and an 826-token input together cost 1652 tokens), so sorting by length
        before batching cuts the token usage.
        """
        vectors: list[list[float]] = [[] for _ in texts]
        for batch in self._batches_by_length(texts):
            batch_vectors = self._embed([texts[i] for i in batch], "passage")
            for i, vector in zip(batch, batch_vectors, strict=True):
                vectors[i] = vector
        return vectors

    def estimate_tokens(self, texts: list[str]) -> int:
        """Rough token count for embed_documents, using the same batching (no API call)."""
        return int(
            sum(
                len(batch) * max(len(texts[i].split()) for i in batch) * TOKENS_PER_WORD
                for batch in self._batches_by_length(texts)
            )
        )

    def _batches_by_length(self, texts: list[str]) -> list[list[int]]:
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        return [order[i : i + self.batch_size] for i in range(0, len(order), self.batch_size)]

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text], "query")[0]

    def _embed(self, texts: list[str], input_type: str) -> list[list[float]]:
        result = self.inference.embed(
            model=self.name,
            inputs=texts,
            parameters={"input_type": input_type, "truncate": "END", "dimension": self.dimension},
        )
        self.tokens_used += result.usage.total_tokens
        vectors = [list(item.values) for item in result.data]
        if len(vectors) != len(texts) or any(len(v) != self.dimension for v in vectors):
            raise ValueError(f"{self.name} did not return {len(texts)} x {self.dimension} vectors")
        return vectors


class PineconeReranker:
    """Reranker backed by Pinecone's hosted rerank models. One API request per call."""

    def __init__(self, inference: Any, model: str) -> None:
        self.inference = inference
        self.name = model
        self.requests_made = 0  # for reporting usage against the free-plan request limit

    @classmethod
    def from_env(cls) -> "PineconeReranker":
        model = _require_env("PINECONE_RERANK_MODEL")  # checked before any client is created
        return cls(_client_from_env().inference, model=model)

    def rerank(self, query: str, documents: list[str], top_n: int) -> list[tuple[int, float]]:
        if not documents:
            return []
        result = self.inference.rerank(
            model=self.name,
            query=query,
            documents=documents,
            top_n=top_n,
            return_documents=False,
            # The model's default is NONE, which rejects pairs over 1024 tokens.
            parameters={"truncate": "END"},
        )
        self.requests_made += 1
        return [(item.index, float(item.score)) for item in result.data]


class PineconeStore:
    """VectorStore on a Pinecone dense index. The record ID is the chunk_id."""

    def __init__(
        self,
        index: Any,
        embedder_name: str,
        namespace: str = "",
        dimension: int = EMBEDDING_DIM,
    ) -> None:
        self.index = index
        self.embedder_name = embedder_name
        self.namespace = namespace  # "" is the index's default namespace
        self.dimension = dimension

    @classmethod
    def from_env(cls, embedder_name: str, namespace: str = "") -> "PineconeStore":
        index_name = _require_env("PINECONE_INDEX")  # no default, like S3_BUCKET in M2
        index = _client_from_env().Index(name=index_name)
        return cls(index, embedder_name=embedder_name, namespace=namespace)

    # --- VectorStore interface ---

    def upsert(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        records = [
            {
                "id": chunk.chunk_id,
                "values": self._checked(vector),
                "metadata": self._metadata(chunk),
            }
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        for start in range(0, len(records), UPSERT_BATCH_SIZE):
            self.index.upsert(
                vectors=records[start : start + UPSERT_BATCH_SIZE],
                namespace=self.namespace,
                show_progress=False,
            )

    def replace_document(
        self, doc_id: str, chunks: list[Chunk], vectors: list[list[float]]
    ) -> None:
        """List the document's IDs by prefix, upsert the new chunks, then delete the IDs that
        are no longer produced. Upserting first means the document is never missing."""
        existing = self.list_ids(prefix=f"{doc_id}:")
        self.upsert(chunks, vectors)
        new_ids = {chunk.chunk_id for chunk in chunks}
        stale = [chunk_id for chunk_id in existing if chunk_id not in new_ids]
        for start in range(0, len(stale), DELETE_BATCH_SIZE):
            self.index.delete(
                ids=stale[start : start + DELETE_BATCH_SIZE], namespace=self.namespace
            )
        logger.info(
            "replaced doc_id=%s upserted=%d deleted_stale=%d", doc_id, len(chunks), len(stale)
        )

    def query(self, vector: list[float], top_k: int, doc_id: str | None = None) -> list[SearchHit]:
        response = self.index.query(
            vector=self._checked(vector),
            top_k=top_k,
            namespace=self.namespace,
            filter={"doc_id": {"$eq": doc_id}} if doc_id else None,
            include_metadata=True,
        )
        return [
            SearchHit(chunk=self._chunk(match.id, match.metadata), score=float(match.score))
            for match in response.matches
        ]

    # --- helpers ---

    def list_ids(self, prefix: str) -> list[str]:
        """Every record ID starting with `prefix` (the SDK follows the pagination tokens)."""
        pages = self.index.list(prefix=prefix, namespace=self.namespace)
        return [item.id for page in pages for item in page.vectors]

    def _metadata(self, chunk: Chunk) -> dict[str, Any]:
        return {
            "doc_id": chunk.doc_id,
            "source_file": chunk.source_file,
            "page": chunk.page,
            "chunk_type": chunk.chunk_type,
            "section": chunk.section,
            "text": chunk.text,
            "embedder": self.embedder_name,
        }

    @staticmethod
    def _chunk(chunk_id: str, metadata: dict[str, Any]) -> Chunk:
        # Pinecone returns numbers in metadata as floats, so the page is converted back.
        return Chunk(
            chunk_id=chunk_id,
            doc_id=metadata["doc_id"],
            source_file=metadata["source_file"],
            page=int(metadata["page"]),
            chunk_type=metadata["chunk_type"],
            section=metadata.get("section", ""),
            text=metadata["text"],
        )

    def _checked(self, vector: list[float]) -> list[float]:
        if len(vector) != self.dimension:
            raise ValueError(f"expected vector of size {self.dimension}, got {len(vector)}")
        return list(vector)

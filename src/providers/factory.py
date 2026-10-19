"""Choose provider implementations from environment variables (SPEC section 5).

    EMBEDDER      fake | pinecone   (default fake)
    VECTOR_STORE  memory | pinecone (default memory)
    RERANKER      none | pinecone   (default none)
    GENERATOR     stub | bedrock    (default stub)

The defaults need no network and no keys. Real providers are imported only when chosen,
and their names, indexes and keys come from their own `from_env` (never from this code).
"""

import os

from src.providers.base import Embedder, Generator, Reranker, VectorStore
from src.providers.fakes import FakeEmbedder, InMemoryStore, StubGenerator


def _choice(variable: str, allowed: tuple[str, ...]) -> str:
    """The variable's value (first allowed value when unset); error on anything else."""
    value = (os.environ.get(variable) or allowed[0]).strip().lower()
    if value not in allowed:
        raise ValueError(f"{variable}={value!r} is not supported; use one of {', '.join(allowed)}")
    return value


def build_embedder() -> Embedder:
    if _choice("EMBEDDER", ("fake", "pinecone")) == "pinecone":
        from src.providers.pinecone import PineconeInferenceEmbedder

        return PineconeInferenceEmbedder.from_env()
    return FakeEmbedder()


def build_store(embedder: Embedder) -> VectorStore:
    if _choice("VECTOR_STORE", ("memory", "pinecone")) == "pinecone":
        from src.providers.pinecone import PineconeInferenceEmbedder, PineconeStore

        # The index was built with the Pinecone embedder; one index uses one embedder only.
        if not isinstance(embedder, PineconeInferenceEmbedder):
            raise ValueError(
                "VECTOR_STORE=pinecone needs EMBEDDER=pinecone (one index, one embedder)"
            )
        return PineconeStore.from_env(embedder_name=embedder.name)
    return InMemoryStore(dimension=embedder.dimension)


def build_reranker() -> Reranker | None:
    if _choice("RERANKER", ("none", "pinecone")) == "pinecone":
        from src.providers.pinecone import PineconeReranker

        return PineconeReranker.from_env()
    return None


def build_generator() -> Generator:
    if _choice("GENERATOR", ("stub", "bedrock")) == "bedrock":
        from src.providers.bedrock import BedrockClaudeGenerator

        return BedrockClaudeGenerator.from_env()
    return StubGenerator()

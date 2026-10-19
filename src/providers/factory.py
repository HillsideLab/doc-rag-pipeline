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

# Allowed values per variable; the first one is the default.
EMBEDDERS = ("fake", "pinecone")
VECTOR_STORES = ("memory", "pinecone")
RERANKERS = ("none", "pinecone")
GENERATORS = ("stub", "bedrock")


def _choice(variable: str, allowed: tuple[str, ...]) -> str:
    """The variable's value (first allowed value when unset); error on anything else."""
    value = (os.environ.get(variable) or allowed[0]).strip().lower()
    if value not in allowed:
        raise ValueError(f"{variable}={value!r} is not supported; use one of {', '.join(allowed)}")
    return value


def selected() -> dict[str, str]:
    """The chosen embedder, vector store and reranker by name, e.g. {"embedder": "pinecone"}.
    Only names: safe to log and to show in /health."""
    return {
        "embedder": _choice("EMBEDDER", EMBEDDERS),
        "vector_store": _choice("VECTOR_STORE", VECTOR_STORES),
        "reranker": _choice("RERANKER", RERANKERS),
    }


def pinecone_namespace() -> str:
    """PINECONE_NAMESPACE, required (no default in code). `__default__`, the name the Pinecone
    console shows for the default namespace, means "" in the SDK."""
    value = (os.environ.get("PINECONE_NAMESPACE") or "").strip()
    if not value:
        raise RuntimeError(
            "PINECONE_NAMESPACE is not set. Set it in .env (__default__ for the default namespace)"
        )
    return "" if value == "__default__" else value


def build_embedder() -> Embedder:
    if _choice("EMBEDDER", EMBEDDERS) == "pinecone":
        from src.providers.pinecone import PineconeInferenceEmbedder

        return PineconeInferenceEmbedder.from_env()
    return FakeEmbedder()


def build_store(embedder: Embedder, namespace: str = "") -> VectorStore:
    """`namespace` is the Pinecone namespace ("" is the default); the memory store ignores it."""
    if _choice("VECTOR_STORE", VECTOR_STORES) == "pinecone":
        from src.providers.pinecone import PineconeInferenceEmbedder, PineconeStore

        # The index was built with the Pinecone embedder; one index uses one embedder only.
        if not isinstance(embedder, PineconeInferenceEmbedder):
            raise ValueError(
                "VECTOR_STORE=pinecone needs EMBEDDER=pinecone (one index, one embedder)"
            )
        return PineconeStore.from_env(embedder_name=embedder.name, namespace=namespace)
    return InMemoryStore(dimension=embedder.dimension)


def build_reranker() -> Reranker | None:
    if _choice("RERANKER", RERANKERS) == "pinecone":
        from src.providers.pinecone import PineconeReranker

        return PineconeReranker.from_env()
    return None


def build_generator() -> Generator:
    if _choice("GENERATOR", GENERATORS) == "bedrock":
        from src.providers.bedrock import BedrockClaudeGenerator

        return BedrockClaudeGenerator.from_env()
    return StubGenerator()

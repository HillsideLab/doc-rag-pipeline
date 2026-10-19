"""Provider selection from environment variables. No real client is ever created here."""

import pytest

from src.providers import factory
from src.providers.fakes import FakeEmbedder, InMemoryStore, StubGenerator

VARIABLES = (
    "EMBEDDER",
    "VECTOR_STORE",
    "RERANKER",
    "GENERATOR",
    "PINECONE_API_KEY",
    "PINECONE_INDEX",
    "BEDROCK_INFERENCE_PROFILE_ID",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in VARIABLES:
        monkeypatch.delenv(name, raising=False)


def test_defaults_are_offline_fakes() -> None:
    embedder = factory.build_embedder()
    assert isinstance(embedder, FakeEmbedder)
    assert isinstance(factory.build_store(embedder), InMemoryStore)
    assert factory.build_reranker() is None
    assert isinstance(factory.build_generator(), StubGenerator)


def test_values_are_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENERATOR", " Stub ")
    assert isinstance(factory.build_generator(), StubGenerator)


@pytest.mark.parametrize(
    ("variable", "build"),
    [
        ("EMBEDDER", factory.build_embedder),
        ("RERANKER", factory.build_reranker),
        ("GENERATOR", factory.build_generator),
    ],
)
def test_unknown_value_is_rejected(monkeypatch: pytest.MonkeyPatch, variable: str, build) -> None:
    monkeypatch.setenv(variable, "openai")
    with pytest.raises(ValueError, match=variable):
        build()


def test_unknown_vector_store_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VECTOR_STORE", "opensearch")
    with pytest.raises(ValueError, match="VECTOR_STORE"):
        factory.build_store(FakeEmbedder())


def test_pinecone_store_needs_pinecone_embedder(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VECTOR_STORE", "pinecone")
    with pytest.raises(ValueError, match="EMBEDDER=pinecone"):
        factory.build_store(FakeEmbedder())


@pytest.mark.parametrize(
    ("variable", "build"),
    [("EMBEDDER", factory.build_embedder), ("RERANKER", factory.build_reranker)],
)
def test_pinecone_without_key_fails_before_any_call(
    monkeypatch: pytest.MonkeyPatch, variable: str, build
) -> None:
    monkeypatch.setenv(variable, "pinecone")
    with pytest.raises(RuntimeError, match="PINECONE_API_KEY"):
        build()


def test_bedrock_without_profile_id_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENERATOR", "bedrock")
    with pytest.raises(RuntimeError, match="BEDROCK_INFERENCE_PROFILE_ID"):
        factory.build_generator()

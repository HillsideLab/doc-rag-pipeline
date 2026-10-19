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
    "PINECONE_NAMESPACE",
    "BEDROCK_INFERENCE_PROFILE_ID",
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
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
    monkeypatch.setenv("PINECONE_EMBED_MODEL", "m")  # so the missing key is what fails
    monkeypatch.setenv("PINECONE_RERANK_MODEL", "m")
    monkeypatch.delenv("PINECONE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="PINECONE_API_KEY"):
        build()


def test_bedrock_without_profile_id_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENERATOR", "bedrock")
    with pytest.raises(RuntimeError, match="BEDROCK_INFERENCE_PROFILE_ID"):
        factory.build_generator()


def test_anthropic_without_key_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENERATOR", "anthropic")
    monkeypatch.setenv("ANTHROPIC_MODEL", "m")  # so the missing key is what fails
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        factory.build_generator()


def test_anthropic_without_model_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GENERATOR", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with pytest.raises(RuntimeError, match="ANTHROPIC_MODEL"):
        factory.build_generator()


def test_anthropic_generator_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.providers.anthropic_api import AnthropicApiGenerator

    monkeypatch.setenv("GENERATOR", "Anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "m")
    assert isinstance(factory.build_generator(), AnthropicApiGenerator)


def test_selected_names_follow_the_variables(monkeypatch: pytest.MonkeyPatch) -> None:
    assert factory.selected() == {"embedder": "fake", "vector_store": "memory", "reranker": "none"}
    monkeypatch.setenv("RERANKER", "Pinecone")
    assert factory.selected()["reranker"] == "pinecone"


@pytest.mark.parametrize(("value", "namespace"), [("__default__", ""), (" pipeline ", "pipeline")])
def test_pinecone_namespace(monkeypatch: pytest.MonkeyPatch, value: str, namespace: str) -> None:
    monkeypatch.setenv("PINECONE_NAMESPACE", value)
    assert factory.pinecone_namespace() == namespace


def test_pinecone_namespace_has_no_default() -> None:
    with pytest.raises(RuntimeError, match="PINECONE_NAMESPACE"):
        factory.pinecone_namespace()


def test_build_store_passes_the_namespace(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.providers.pinecone import PineconeInferenceEmbedder, PineconeStore

    calls: list[dict[str, str]] = []
    monkeypatch.setattr(PineconeStore, "from_env", classmethod(lambda cls, **kw: calls.append(kw)))
    monkeypatch.setenv("VECTOR_STORE", "pinecone")
    factory.build_store(PineconeInferenceEmbedder(object(), model="m"), namespace="pipeline")
    assert calls == [{"embedder_name": "m", "namespace": "pipeline"}]

"""HTTP API with FastAPI's TestClient and fakes only: no network, no environment needed."""

import logging

import pytest
from fastapi.testclient import TestClient

from scripts import export_openapi
from src.answering import DISCLAIMER
from src.api.main import UPSTREAM_ERROR, Services, create_app
from src.models import Chunk, SearchHit
from src.pipeline.logging_json import JsonFormatter
from src.providers.fakes import FakeEmbedder, InMemoryStore, StubGenerator

CABLIVI = "cablivi-epar-product-information_en.pdf"
QUESTION = "What are the excipients of Cablivi?"
NAMES = {"embedder": "fake", "vector_store": "memory", "reranker": "none"}


def make_chunks() -> list[Chunk]:
    texts = [
        "Sucrose, citric acid anhydrous, trisodium citrate dihydrate, polysorbate 80.",
        "Cablivi is used to treat acquired thrombotic thrombocytopenic purpura.",
        "Do not store above 25 C. Do not freeze.",
    ]
    return [
        Chunk(
            chunk_id=f"d:p{page}:c0",
            doc_id="d",
            source_file=CABLIVI,
            page=page,
            chunk_type="text",
            section="6.1 List of excipients" if page == 10 else "",
            text=text,
        )
        for page, text in zip((10, 2, 11), texts, strict=True)
    ]


def fake_services(store: object | None = None) -> Services:
    embedder = FakeEmbedder()
    if store is None:
        memory = InMemoryStore()
        chunks = make_chunks()
        memory.upsert(chunks, embedder.embed_documents([c.text for c in chunks]))
        store = memory
    return Services(
        embedder=embedder,
        store=store,  # type: ignore[arg-type]
        reranker=None,
        generator=StubGenerator(),
        names=NAMES,
    )


class FailingStore:
    """A store whose SDK error message contains something that must never reach the client."""

    def query(self, vector: list[float], top_k: int, doc_id: str | None = None) -> list[SearchHit]:
        raise ConnectionError("secret-key-123 index doc-rag-mock unreachable")


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(fake_services()))


def test_ask_returns_answer_citations_and_disclaimer(client: TestClient) -> None:
    response = client.post("/ask", json={"question": QUESTION, "top_k": 3})
    assert response.status_code == 200
    body = response.json()
    assert body["generator"] == "stub"
    assert body["disclaimer"] == DISCLAIMER
    assert body["answer"]
    assert len(body["citations"]) == 3
    citation = body["citations"][0]
    assert set(citation) >= {"chunk_id", "product", "section", "page"}
    assert citation["product"] == "Cablivi"
    assert response.headers["X-Request-ID"]


def test_top_k_sets_the_number_of_citations(client: TestClient) -> None:
    response = client.post("/ask", json={"question": QUESTION, "top_k": 1})
    assert len(response.json()["citations"]) == 1


def test_top_k_defaults_to_5(client: TestClient) -> None:
    # Only 3 chunks are stored, so all of them are cited.
    response = client.post("/ask", json={"question": QUESTION})
    assert len(response.json()["citations"]) == 3


@pytest.mark.parametrize(
    "payload",
    [
        {"question": ""},
        {"question": "   "},
        {"question": "x" * 1001},
        {"question": QUESTION, "top_k": 0},
        {"question": QUESTION, "top_k": 21},
        {},
    ],
)
def test_invalid_input_is_422(client: TestClient, payload: dict[str, object]) -> None:
    assert client.post("/ask", json=payload).status_code == 422


def test_upstream_error_is_502_without_internal_details() -> None:
    client = TestClient(create_app(fake_services(store=FailingStore())))
    response = client.post("/ask", json={"question": QUESTION})
    assert response.status_code == 502
    body = response.json()
    assert body == {"detail": UPSTREAM_ERROR, "request_id": response.headers["X-Request-ID"]}
    assert "secret-key-123" not in response.text
    assert "doc-rag-mock" not in response.text


def test_logs_never_contain_the_question_or_error_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    with TestClient(create_app(fake_services())) as client:
        client.post("/ask", json={"question": QUESTION})
    TestClient(create_app(fake_services(store=FailingStore()))).post(
        "/ask", json={"question": QUESTION}
    )
    lines = [JsonFormatter().format(r) for r in caplog.records]
    assert lines
    assert not any("excipients" in line for line in lines)
    assert not any("secret-key-123" in line for line in lines)
    requests = [r for r in caplog.records if r.getMessage() == "request"]
    assert {r.status_code for r in requests} == {200, 502}  # type: ignore[attr-defined]
    assert all(r.request_id for r in requests)  # type: ignore[attr-defined]
    failed = [r for r in caplog.records if r.getMessage() == "answer failed"]
    assert failed[0].error_type == "ConnectionError"  # type: ignore[attr-defined]


def test_startup_logs_provider_names_only(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    with TestClient(create_app(fake_services())):
        pass
    started = [r for r in caplog.records if r.getMessage() == "api started"]
    assert len(started) == 1
    line = JsonFormatter().format(started[0])
    assert '"embedder": "fake"' in line
    assert '"vector_store": "memory"' in line
    assert '"reranker": "none"' in line
    assert '"generator": "stub"' in line


def test_health_shows_provider_names(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", **NAMES, "generator": "stub"}


def test_ask_schema_has_the_example_question(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()["components"]["schemas"]["AskRequest"]
    assert schema["properties"]["question"]["examples"] == [QUESTION]


def test_committed_openapi_matches_the_code() -> None:
    # Same check as the CI step; regenerate with: uv run python -m scripts.export_openapi
    assert export_openapi.OUTPUT.read_text() == export_openapi.render()

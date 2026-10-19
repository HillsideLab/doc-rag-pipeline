"""Lambda handlers with fake clients: settings, forced failures, and what reaches the logs."""

import hashlib
import io
import json
import logging
from pathlib import Path
from typing import Any

import pytest

from src.pipeline import handlers, logging_json, steps
from src.providers.fakes import FakeEmbedder, InMemoryStore
from src.providers.textract import TextractExtractor
from tests.aws_fakes import FakeS3, FakeSecrets, FakeTable, FakeTextract

FIXTURE = Path(__file__).parent / "fixtures" / "textract_layout_sample.json"
BUCKET = "test-bucket"
KEY = "incoming/leaflet.pdf"
PDF_BYTES = b"%PDF-1.7 synthetic test bytes"
SHA256 = hashlib.sha256(PDF_BYTES).hexdigest()
CACHE_KEY = f"textract-cache/{SHA256}.json"
SECRET_VALUE = "pcsk-fake-secret-value"


@pytest.fixture
def fakes(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("S3_BUCKET", BUCKET)
    monkeypatch.delenv("FORCE_FAIL_STEP", raising=False)
    s3 = FakeS3({KEY: PDF_BYTES, CACHE_KEY: FIXTURE.read_bytes()})
    extractor = TextractExtractor(BUCKET, s3, FakeTextract())
    table = FakeTable()
    embedder = FakeEmbedder()
    store = InMemoryStore(dimension=embedder.dimension)
    monkeypatch.setattr(handlers, "_extractor", lambda: extractor)
    monkeypatch.setattr(handlers, "_table", lambda: table)
    monkeypatch.setattr(handlers, "_embedder_and_store", lambda: (embedder, store))
    return {"s3": s3, "table": table, "store": store}


def event(**state: Any) -> dict[str, Any]:
    return {"state": {"bucket": BUCKET, "key": KEY, **state}, "execution_arn": "arn:exec:1"}


def test_register_then_index_on_a_cache_hit(fakes: dict[str, Any]) -> None:
    doc = handlers.register(event(), None)
    assert doc["cached"] is True

    result = handlers.index(event(doc=doc), None)

    assert result["chunk_count"] > 0
    assert fakes["table"].updates[0]["Key"] == {"doc_id": doc["doc_id"]}


def test_event_from_another_bucket_is_rejected(fakes: dict[str, Any]) -> None:
    bad = event()
    bad["state"]["bucket"] = "other-bucket"

    with pytest.raises(ValueError, match="S3_BUCKET"):
        handlers.register(bad, None)

    assert fakes["table"].updates == []


def test_force_fail_step_raises_transient_error(
    fakes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FORCE_FAIL_STEP", "index")
    doc = handlers.register(event(), None)  # other steps are unaffected

    with pytest.raises(steps.TransientError):
        handlers.index(event(doc=doc), None)


def test_logs_are_json_with_ids_and_no_secret_or_text(
    fakes: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    # Formatted while each step runs, as in Lambda, so the step context is still set.
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(logging_json.JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        monkeypatch.setenv("FORCE_FAIL_STEP", "index")
        doc = handlers.register(event(), None)
        with pytest.raises(steps.TransientError):
            handlers.index(event(doc=doc), None)
    finally:
        root.removeHandler(handler)
    output = buffer.getvalue()
    lines = [json.loads(line) for line in output.splitlines()]

    steps_seen = [(line["step"], line["status"]) for line in lines if "status" in line]
    assert steps_seen == [
        ("register", "STARTED"),
        ("register", "SUCCEEDED"),
        ("index", "STARTED"),
        ("index", "FAILED"),
    ]
    assert all(line["execution_arn"] == "arn:exec:1" for line in lines)
    # The document ID is known once register has hashed the PDF.
    step_ids = [line.get("document_id") for line in lines if "status" in line]
    assert step_ids[1:] == [doc["doc_id"]] * 3
    assert lines[-1]["error_type"] == "TransientError"
    # Nothing from the document body or the secret.
    longest_line = max(
        (b["Text"] for b in json.loads(FIXTURE.read_text())["Blocks"] if b["BlockType"] == "LINE"),
        key=len,
    )
    assert longest_line not in output
    assert SECRET_VALUE not in output


def test_api_key_is_read_from_secrets_manager_once(monkeypatch: pytest.MonkeyPatch) -> None:
    secrets = FakeSecrets(SECRET_VALUE)

    class Session:
        def client(self, name: str) -> Any:
            assert name == "secretsmanager"
            return secrets

    monkeypatch.setenv("PINECONE_SECRET_ARN", "arn:secret")
    monkeypatch.setattr(handlers, "_session", lambda: Session())
    handlers._pinecone_api_key.cache_clear()
    try:
        assert handlers._pinecone_api_key() == SECRET_VALUE
        assert handlers._pinecone_api_key() == SECRET_VALUE
        assert secrets.calls == 1
    finally:
        handlers._pinecone_api_key.cache_clear()


@pytest.mark.parametrize("name", ["S3_BUCKET", "PINECONE_SECRET_ARN"])
def test_missing_setting_names_the_variable(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(name, raising=False)

    with pytest.raises(RuntimeError, match=name):
        handlers.require_env(name)

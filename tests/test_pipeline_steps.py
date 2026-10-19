"""The Step Functions steps, against fakes of S3, Textract and DynamoDB (no network)."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from src.models import DocumentStatus
from src.pipeline import steps
from src.providers.fakes import FakeEmbedder, InMemoryStore
from src.providers.textract import TextractExtractor, TextractJobError
from tests.aws_fakes import FakeS3, FakeTable, FakeTextract

FIXTURE = Path(__file__).parent / "fixtures" / "textract_layout_sample.json"
BUCKET = "test-bucket"
KEY = "incoming/cablivi-epar-product-information_en.pdf"
PDF_BYTES = b"%PDF-1.7 synthetic test bytes"
SHA256 = hashlib.sha256(PDF_BYTES).hexdigest()
DOC_ID = SHA256[:16]
CACHE_KEY = f"textract-cache/{SHA256}.json"


def raw() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def extractor(s3: FakeS3, textract: FakeTextract | None = None) -> TextractExtractor:
    return TextractExtractor(BUCKET, s3, textract or FakeTextract())


@pytest.mark.parametrize("cached", [True, False])
def test_register_marks_received_and_reports_cache(cached: bool) -> None:
    objects = {KEY: PDF_BYTES}
    if cached:
        objects[CACHE_KEY] = b"{}"
    table = FakeTable()

    result = steps.register(extractor(FakeS3(objects)), table, KEY, "arn:exec", now=lambda: "T")

    assert result == {"doc_id": DOC_ID, "sha256": SHA256, "cached": cached}
    [update] = table.updates
    assert update["Key"] == {"doc_id": DOC_ID}
    values = update["ExpressionAttributeValues"]
    assert values[":status"] == DocumentStatus.RECEIVED.value
    assert values[":key"] == KEY and values[":execution_arn"] == "arn:exec"
    assert values[":cached"] is cached
    assert "ADD attempts :one" in update["UpdateExpression"]
    assert "REMOVE #error, cause" in update["UpdateExpression"]


def test_start_extraction_returns_job_and_start_time() -> None:
    textract = FakeTextract()

    result = steps.start_extraction(extractor(FakeS3(), textract), KEY, clock=lambda: 100.0)

    assert result == {"job_id": "job-1", "started_at": 100.0}
    assert textract.start_calls[0]["DocumentLocation"]["S3Object"]["Name"] == KEY


def test_check_extraction_reports_status() -> None:
    textract = FakeTextract([{"JobStatus": "IN_PROGRESS"}, {"JobStatus": "SUCCEEDED"}])
    ex = extractor(FakeS3(), textract)

    assert steps.check_extraction(ex, "job-1", 0.0, clock=lambda: 10.0) == {"status": "IN_PROGRESS"}
    assert steps.check_extraction(ex, "job-1", 0.0, clock=lambda: 20.0) == {"status": "SUCCEEDED"}


def test_check_extraction_times_out_after_limit() -> None:
    ex = extractor(FakeS3(), FakeTextract([{"JobStatus": "IN_PROGRESS"}]))

    with pytest.raises(TimeoutError):
        steps.check_extraction(ex, "job-1", 0.0, clock=lambda: 601.0, timeout_s=600)


def test_check_extraction_raises_on_failed_job() -> None:
    ex = extractor(FakeS3(), FakeTextract([{"JobStatus": "FAILED", "StatusMessage": "bad"}]))

    with pytest.raises(TextractJobError):
        steps.check_extraction(ex, "job-1", 0.0)


def test_save_extraction_writes_the_cache() -> None:
    s3 = FakeS3()
    blocks = raw()["Blocks"]
    textract = FakeTextract(
        [{"JobStatus": "SUCCEEDED", "DocumentMetadata": {"Pages": 3}, "Blocks": blocks}]
    )

    result = steps.save_extraction(extractor(s3, textract), "job-1", SHA256)

    assert result == {"blocks": len(blocks)}
    assert json.loads(s3.objects[CACHE_KEY])["Blocks"] == blocks


def test_index_chunks_and_stores_the_cached_document() -> None:
    s3 = FakeS3({CACHE_KEY: json.dumps(raw()).encode()})
    embedder = FakeEmbedder()
    store = InMemoryStore(dimension=embedder.dimension)

    result = steps.index(extractor(s3), embedder, store, KEY, SHA256)

    assert result["page_count"] == 3 and result["chunk_count"] > 0
    hits = store.query(embedder.embed_query("dose"), top_k=100, doc_id=DOC_ID)
    assert len(hits) == result["chunk_count"]
    assert {hit.chunk.source_file for hit in hits} == {KEY.removeprefix("incoming/")}


def test_index_without_cache_fails_and_writes_nothing() -> None:
    embedder = FakeEmbedder()
    store = InMemoryStore(dimension=embedder.dimension)

    with pytest.raises(RuntimeError, match="no Textract cache"):
        steps.index(extractor(FakeS3()), embedder, store, KEY, SHA256)

    assert store.query(embedder.embed_query("dose"), top_k=10) == []

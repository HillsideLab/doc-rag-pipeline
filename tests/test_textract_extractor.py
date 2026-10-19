import hashlib
import json
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

from src.providers.base import Extractor
from src.providers.textract import TextractExtractor, TextractJobError
from tests.aws_fakes import DeniedS3, FakeS3, FakeTextract

FIXTURE = Path(__file__).parent / "fixtures" / "textract_layout_sample.json"
BUCKET = "test-bucket"
PDF_KEY = "raw/leaflet.pdf"
PDF_BYTES = b"%PDF-1.7 synthetic test bytes"
SHA256 = hashlib.sha256(PDF_BYTES).hexdigest()
CACHE_KEY = f"textract-cache/{SHA256}.json"


def fixture_raw() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text())


def succeeded(blocks: list[dict[str, Any]], next_token: str | None = None) -> dict[str, Any]:
    response: dict[str, Any] = {
        "JobStatus": "SUCCEEDED",
        "DocumentMetadata": {"Pages": 3},
        "Blocks": blocks,
    }
    if next_token:
        response["NextToken"] = next_token
    return response


IN_PROGRESS = {"JobStatus": "IN_PROGRESS"}


def make(s3: FakeS3, textract: FakeTextract, **kwargs: Any) -> tuple[TextractExtractor, list]:
    sleeps: list[float] = []
    extractor = TextractExtractor(BUCKET, s3, textract, sleep=sleeps.append, **kwargs)
    return extractor, sleeps


def test_satisfies_extractor_interface() -> None:
    extractor, _ = make(FakeS3(), FakeTextract([]))
    assert isinstance(extractor, Extractor)


def test_cache_hit_never_calls_textract() -> None:
    s3 = FakeS3({PDF_KEY: PDF_BYTES, CACHE_KEY: json.dumps(fixture_raw()).encode()})
    textract = FakeTextract([])
    extractor, _ = make(s3, textract)

    doc = extractor.extract(PDF_KEY)

    assert textract.start_calls == [] and textract.get_calls == []
    assert doc.doc_id == SHA256[:16]
    assert doc.source_file == "leaflet.pdf"
    assert len(doc.pages) == 3


def test_cache_miss_runs_textract_once_and_writes_cache() -> None:
    s3 = FakeS3({PDF_KEY: PDF_BYTES})
    textract = FakeTextract([IN_PROGRESS, succeeded(fixture_raw()["Blocks"])])
    extractor, sleeps = make(s3, textract)

    doc = extractor.extract(PDF_KEY)

    assert textract.start_calls == [
        {
            "DocumentLocation": {"S3Object": {"Bucket": BUCKET, "Name": PDF_KEY}},
            "FeatureTypes": ["LAYOUT"],
        }
    ]
    assert sleeps == [2.0]
    cached = json.loads(s3.objects[CACHE_KEY])
    assert cached["FeatureTypes"] == ["LAYOUT"]
    assert cached["Blocks"] == fixture_raw()["Blocks"]
    assert [page.page_number for page in doc.pages] == [1, 2, 3]

    # Second run with the same PDF: served from the cache, Textract untouched.
    extractor.extract(PDF_KEY)
    assert len(textract.start_calls) == 1


def test_result_pages_are_joined_with_next_token() -> None:
    blocks = fixture_raw()["Blocks"]
    third = len(blocks) // 3
    textract = FakeTextract(
        [
            succeeded(blocks[:third], next_token="t1"),
            succeeded(blocks[third : 2 * third], next_token="t2"),
            succeeded(blocks[2 * third :]),
        ]
    )
    extractor, _ = make(FakeS3({PDF_KEY: PDF_BYTES}), textract)

    raw = extractor.analyze(PDF_KEY)

    assert raw["Blocks"] == blocks
    assert [call.get("NextToken") for call in textract.get_calls] == [None, "t1", "t2"]


def test_backoff_doubles_up_to_cap_then_times_out() -> None:
    textract = FakeTextract([IN_PROGRESS] * 20)
    extractor, sleeps = make(FakeS3({PDF_KEY: PDF_BYTES}), textract, timeout_s=100)

    with pytest.raises(TimeoutError):
        extractor.analyze(PDF_KEY)

    assert sleeps == [2.0, 4.0, 8.0, 16.0, 30.0, 30.0]  # 90s waited; one more would pass 100


@pytest.mark.parametrize("status", ["FAILED", "PARTIAL_SUCCESS"])
def test_unsuccessful_job_raises_and_is_not_cached(status: str) -> None:
    s3 = FakeS3({PDF_KEY: PDF_BYTES})
    textract = FakeTextract([{"JobStatus": status, "StatusMessage": "bad pdf"}])
    extractor, _ = make(s3, textract)

    with pytest.raises(TextractJobError, match=status):
        extractor.extract(PDF_KEY)

    assert CACHE_KEY not in s3.objects


def test_access_denied_on_cache_is_not_treated_as_miss() -> None:
    textract = FakeTextract([])
    extractor, _ = make(DeniedS3({PDF_KEY: PDF_BYTES}), textract)

    with pytest.raises(ClientError):
        extractor.extract(PDF_KEY)

    assert textract.start_calls == []


def test_has_cache_and_upload(tmp_path: Path) -> None:
    s3 = FakeS3()
    extractor, _ = make(s3, FakeTextract([]))
    pdf = tmp_path / "leaflet.pdf"
    pdf.write_bytes(PDF_BYTES)

    assert extractor.has_cache(SHA256) is False
    assert extractor.upload(pdf) == PDF_KEY
    assert s3.objects[PDF_KEY] == PDF_BYTES

    s3.objects[CACHE_KEY] = b"{}"
    assert extractor.has_cache(SHA256) is True


def test_job_status_asks_for_one_result_only() -> None:
    textract = FakeTextract([IN_PROGRESS, succeeded(fixture_raw()["Blocks"])])
    extractor, _ = make(FakeS3(), textract)

    assert extractor.job_status("job-1") == "IN_PROGRESS"
    assert extractor.job_status("job-1") == "SUCCEEDED"
    assert textract.get_calls == [{"JobId": "job-1", "MaxResults": 1}] * 2


@pytest.mark.parametrize("status", ["FAILED", "PARTIAL_SUCCESS"])
def test_job_status_raises_on_unsuccessful_job(status: str) -> None:
    extractor, _ = make(FakeS3(), FakeTextract([{"JobStatus": status}]))

    with pytest.raises(TextractJobError, match=status):
        extractor.job_status("job-1")


def test_fetch_result_joins_pages_without_waiting() -> None:
    blocks = fixture_raw()["Blocks"]
    half = len(blocks) // 2
    textract = FakeTextract([succeeded(blocks[:half], next_token="t1"), succeeded(blocks[half:])])
    extractor, sleeps = make(FakeS3(), textract)

    raw = extractor.fetch_result("job-1")

    assert raw["Blocks"] == blocks and raw["FeatureTypes"] == ["LAYOUT"]
    assert sleeps == []


def test_fetch_result_refuses_unfinished_job() -> None:
    extractor, _ = make(FakeS3(), FakeTextract([IN_PROGRESS]))

    with pytest.raises(TextractJobError, match="IN_PROGRESS"):
        extractor.fetch_result("job-1")

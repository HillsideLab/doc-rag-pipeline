"""One plain function per Step Functions step. Lambda handlers (handlers.py) only call these.

Only small values (IDs, flags, counts) are returned, because Step Functions passes at most
256 KB between states. The Textract result itself travels through the S3 cache
(textract-cache/<sha256>.json), which also keeps the same PDF from being paid for twice.

Clients are passed in, so tests use fakes and never touch the network.
"""

import hashlib
import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import PurePosixPath
from typing import Any

from src.chunking import chunk_document
from src.indexing import index_document
from src.models import DocumentStatus
from src.providers.base import Embedder, VectorStore
from src.providers.textract import DEFAULT_TIMEOUT_S, TextractExtractor, doc_id_for
from src.providers.textract_parse import textract_to_document


class TransientError(RuntimeError):
    """A failure worth retrying. Step Functions retries it by this class name."""


def utc_now() -> str:
    """UTC time in the format Step Functions writes ($$.State.EnteredTime), e.g.
    2026-10-19T04:55:34.746Z, so every updated_at in the table looks the same."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def register(
    extractor: TextractExtractor,
    table: Any,
    key: str,
    execution_arn: str,
    now: Callable[[], str] = utc_now,
) -> dict[str, Any]:
    """Hash the PDF, mark the document RECEIVED, and report whether Textract can be skipped."""
    sha256 = hashlib.sha256(extractor.read(key)).hexdigest()
    doc_id = doc_id_for(sha256)
    cached = extractor.has_cache(sha256)
    timestamp = now()
    table.update_item(
        Key={"doc_id": doc_id},
        # An earlier failure's error is removed, so a re-run does not show a stale error.
        UpdateExpression=(
            "SET #status = :status, s3_key = :key, sha256 = :sha256,"
            " execution_arn = :execution_arn, textract_cached = :cached,"
            " created_at = if_not_exists(created_at, :now), updated_at = :now"
            " ADD attempts :one REMOVE #error, cause"
        ),
        ExpressionAttributeNames={"#status": "status", "#error": "error"},
        ExpressionAttributeValues={
            ":status": DocumentStatus.RECEIVED.value,
            ":key": key,
            ":sha256": sha256,
            ":execution_arn": execution_arn,
            ":cached": cached,
            ":now": timestamp,
            ":one": 1,
        },
    )
    return {"doc_id": doc_id, "sha256": sha256, "cached": cached}


def start_extraction(
    extractor: TextractExtractor, key: str, clock: Callable[[], float] = time.time
) -> dict[str, Any]:
    return {"job_id": extractor.start_job(key), "started_at": clock()}


def check_extraction(
    extractor: TextractExtractor,
    job_id: str,
    started_at: float,
    clock: Callable[[], float] = time.time,
    timeout_s: float = DEFAULT_TIMEOUT_S,
) -> dict[str, Any]:
    """SUCCEEDED or IN_PROGRESS. A failed job raises TextractJobError (not retried)."""
    status = extractor.job_status(job_id)
    if status == "IN_PROGRESS" and clock() - started_at > timeout_s:
        raise TimeoutError(f"job {job_id} still running after {timeout_s:.0f}s")
    return {"status": status}


def save_extraction(extractor: TextractExtractor, job_id: str, sha256: str) -> dict[str, Any]:
    raw = extractor.fetch_result(job_id)
    extractor.write_cache(sha256, raw)
    return {"blocks": len(raw["Blocks"])}


def index(
    extractor: TextractExtractor,
    embedder: Embedder,
    store: VectorStore,
    key: str,
    sha256: str,
) -> dict[str, Any]:
    """Cached Textract JSON -> ExtractedDocument -> chunks -> embeddings -> vector store."""
    raw = extractor.load_cache(sha256)
    if raw is None:
        raise RuntimeError(f"no Textract cache for sha256={sha256}")
    doc_id = doc_id_for(sha256)
    doc = textract_to_document(raw, doc_id=doc_id, source_file=PurePosixPath(key).name)
    chunks = chunk_document(doc)
    index_document(doc_id, chunks, embedder, store)
    return {"page_count": len(doc.pages), "chunk_count": len(chunks)}

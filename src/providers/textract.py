"""Textract implementation of the Extractor interface, with the raw JSON cached in S3.

Flow for `extract(s3_key)`:
1. Read the PDF from S3 and hash it (sha256).
2. If textract-cache/<sha256>.json exists, use it and do not call Textract (no cost).
3. Otherwise start an async LAYOUT analysis, poll with exponential backoff, collect every
   result page (NextToken), and write the merged JSON to the cache.
4. Convert the JSON with the pure function in textract_parse.py.

The boto3 clients are passed in, so tests use small fakes and never touch the network.
"""

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from pathlib import Path, PurePosixPath
from typing import Any

from botocore.exceptions import ClientError

from src.models import ExtractedDocument
from src.providers.textract_parse import textract_to_document

logger = logging.getLogger(__name__)

RAW_PREFIX = "raw/"
CACHE_PREFIX = "textract-cache/"
FEATURE_TYPES = ["LAYOUT"]
FIRST_DELAY_S = 2.0
MAX_DELAY_S = 30.0
DEFAULT_TIMEOUT_S = 600.0
# Approximate price of AnalyzeDocument LAYOUT in us-east-1; check the AWS pricing page.
LAYOUT_USD_PER_PAGE = 0.004


class TextractJobError(RuntimeError):
    """The Textract job ended in a state other than SUCCEEDED."""


def doc_id_for(sha256: str) -> str:
    """The document ID: the first 16 hex characters of the PDF's sha256."""
    return sha256[:16]


def _is_not_found(error: ClientError) -> bool:
    # GetObject reports "NoSuchKey"; HeadObject has no body, so only the HTTP code "404".
    return error.response["Error"]["Code"] in {"NoSuchKey", "404"}


class TextractExtractor:
    def __init__(
        self,
        bucket: str,
        s3_client: Any,
        textract_client: Any,
        sleep: Callable[[float], None] = time.sleep,
        timeout_s: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.bucket = bucket
        self.s3 = s3_client
        self.textract = textract_client
        self.sleep = sleep
        self.timeout_s = timeout_s

    @classmethod
    def from_env(cls) -> "TextractExtractor":
        """Build real clients. Credentials come from AWS_PROFILE via boto3, never from code."""
        import boto3  # imported here so unit tests never need AWS configuration

        bucket = os.environ.get("S3_BUCKET")
        if not bucket:
            raise RuntimeError("S3_BUCKET is not set")
        session = boto3.Session(region_name=os.environ.get("AWS_REGION", "us-east-1"))
        return cls(bucket, session.client("s3"), session.client("textract"))

    # --- Extractor interface ---

    def extract(self, source: str) -> ExtractedDocument:
        sha256 = hashlib.sha256(self.read(source)).hexdigest()
        raw = self.load_cache(sha256)
        if raw is None:
            logger.info("textract cache miss sha256=%s", sha256)
            raw = self.analyze(source)
            self.write_cache(sha256, raw)
        else:
            logger.info("textract cache hit sha256=%s", sha256)
        return textract_to_document(
            raw, doc_id=doc_id_for(sha256), source_file=PurePosixPath(source).name
        )

    def read(self, key: str) -> bytes:
        return self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    # --- Helpers used by the CLI ---

    def upload(self, path: Path) -> str:
        """Upload a local PDF to raw/<file name> and return its S3 key."""
        key = RAW_PREFIX + path.name
        self.s3.put_object(
            Bucket=self.bucket, Key=key, Body=path.read_bytes(), ContentType="application/pdf"
        )
        return key

    def has_cache(self, sha256: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=self._cache_key(sha256))
        except ClientError as error:
            if _is_not_found(error):
                return False
            raise
        return True

    def load_cache(self, sha256: str) -> dict[str, Any] | None:
        try:
            response = self.s3.get_object(Bucket=self.bucket, Key=self._cache_key(sha256))
        except ClientError as error:
            if _is_not_found(error):
                return None
            raise  # e.g. AccessDenied: do not treat it as a miss and pay for Textract
        return json.loads(response["Body"].read())

    def write_cache(self, sha256: str, raw: dict[str, Any]) -> None:
        self.s3.put_object(
            Bucket=self.bucket,
            Key=self._cache_key(sha256),
            Body=json.dumps(raw).encode(),
            ContentType="application/json",
        )

    # --- Textract async job (split so M6 Step Functions can reuse each step) ---

    def analyze(self, source: str) -> dict[str, Any]:
        job_id = self.start_job(source)
        return self.collect_results(job_id, self.wait_for_job(job_id))

    def job_status(self, job_id: str) -> str:
        """One status check for Step Functions polling: SUCCEEDED or IN_PROGRESS.

        MaxResults=1 keeps the response small while the job is checked repeatedly.
        """
        response = self.textract.get_document_analysis(JobId=job_id, MaxResults=1)
        status: str = response["JobStatus"]
        if status not in {"SUCCEEDED", "IN_PROGRESS"}:
            message = response.get("StatusMessage", "")
            raise TextractJobError(f"job {job_id} ended with {status}: {message}")
        return status

    def fetch_result(self, job_id: str) -> dict[str, Any]:
        """The merged result of a job that has already succeeded (no waiting)."""
        first_page = self.textract.get_document_analysis(JobId=job_id)
        if first_page["JobStatus"] != "SUCCEEDED":
            raise TextractJobError(f"job {job_id} is {first_page['JobStatus']}, not SUCCEEDED")
        return self.collect_results(job_id, first_page)

    def collect_results(self, job_id: str, first_page: dict[str, Any]) -> dict[str, Any]:
        return {
            "DocumentMetadata": first_page["DocumentMetadata"],
            "FeatureTypes": FEATURE_TYPES,
            "Blocks": self.fetch_blocks(job_id, first_page),
        }

    def start_job(self, source: str) -> str:
        response = self.textract.start_document_analysis(
            DocumentLocation={"S3Object": {"Bucket": self.bucket, "Name": source}},
            FeatureTypes=FEATURE_TYPES,
        )
        job_id: str = response["JobId"]
        logger.info("textract job started job_id=%s", job_id)
        return job_id

    def wait_for_job(self, job_id: str) -> dict[str, Any]:
        """Poll until the job succeeds. Returns the first page of results."""
        delay = FIRST_DELAY_S
        waited = 0.0
        while True:
            response = self.textract.get_document_analysis(JobId=job_id)
            status = response["JobStatus"]
            if status == "SUCCEEDED":
                logger.info("textract job succeeded job_id=%s waited_s=%.0f", job_id, waited)
                return response
            if status != "IN_PROGRESS":
                # FAILED, or PARTIAL_SUCCESS: never cache an incomplete result.
                message = response.get("StatusMessage", "")
                raise TextractJobError(f"job {job_id} ended with {status}: {message}")
            if waited + delay > self.timeout_s:
                raise TimeoutError(f"job {job_id} still running after {waited:.0f}s")
            self.sleep(delay)
            waited += delay
            delay = min(delay * 2, MAX_DELAY_S)

    def fetch_blocks(self, job_id: str, first_page: dict[str, Any]) -> list[dict[str, Any]]:
        """Collect Blocks from every result page by following NextToken."""
        blocks = list(first_page["Blocks"])
        token = first_page.get("NextToken")
        while token:
            response = self.textract.get_document_analysis(JobId=job_id, NextToken=token)
            blocks.extend(response["Blocks"])
            token = response.get("NextToken")
        logger.info("textract results collected job_id=%s blocks=%d", job_id, len(blocks))
        return blocks

    # --- private ---

    def _cache_key(self, sha256: str) -> str:
        return f"{CACHE_PREFIX}{sha256}.json"

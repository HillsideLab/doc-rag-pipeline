"""Lambda entry points, one per Step Functions step. Each handler reads its settings, builds
its clients (once per container), and calls one function in steps.py.

Every event is {"state": <the state machine's current state>, "execution_arn": "..."}.
The state holds `key` from EventBridge and the results of earlier steps (`doc`, `job`).

Settings come from environment variables set by Terraform; none has a default in code.
FORCE_FAIL_STEP=<step> makes that step raise TransientError, to test retries and FAILED.
"""

import os
from functools import cache
from typing import Any

import boto3

from src.pipeline import logging_json, steps
from src.providers.textract import TextractExtractor

logging_json.configure()


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


# --- clients, built on first use and reused while the container stays warm ---


@cache
def _session() -> boto3.Session:
    return boto3.Session(region_name=require_env("AWS_REGION"))


@cache
def _extractor() -> TextractExtractor:
    session = _session()
    return TextractExtractor(
        require_env("S3_BUCKET"), session.client("s3"), session.client("textract")
    )


@cache
def _table() -> Any:
    return _session().resource("dynamodb").Table(require_env("TABLE_NAME"))


@cache
def _pinecone_api_key() -> str:
    secret = _session().client("secretsmanager")
    value: str = secret.get_secret_value(SecretId=require_env("PINECONE_SECRET_ARN"))[
        "SecretString"
    ]
    return value


@cache
def _embedder_and_store() -> tuple[Any, Any]:
    from pinecone import Pinecone  # imported only by the index step

    from src.providers.pinecone import PineconeInferenceEmbedder, PineconeStore

    client = Pinecone(api_key=_pinecone_api_key())
    embedder = PineconeInferenceEmbedder(
        client.inference, model=require_env("PINECONE_EMBED_MODEL")
    )
    store = PineconeStore(
        client.Index(name=require_env("PINECONE_INDEX")),
        embedder_name=embedder.name,
        namespace=require_env("PINECONE_NAMESPACE"),
    )
    return embedder, store


# --- helpers ---


def _checked_key(state: dict[str, Any]) -> str:
    """The S3 key, after checking the event came from the configured bucket."""
    if state["bucket"] != require_env("S3_BUCKET"):
        raise ValueError("event bucket is not the configured S3_BUCKET")
    return str(state["key"])


def _maybe_force_fail(step: str) -> None:
    if os.environ.get("FORCE_FAIL_STEP") == step:
        raise steps.TransientError(f"forced failure in step {step} (FORCE_FAIL_STEP)")


# --- handlers ---


def register(event: dict[str, Any], context: Any) -> dict[str, Any]:
    with logging_json.step_context("register", event["execution_arn"]):
        _maybe_force_fail("register")
        result = steps.register(
            _extractor(), _table(), _checked_key(event["state"]), event["execution_arn"]
        )
        logging_json.set_document(result["doc_id"])
        return result


def start_extraction(event: dict[str, Any], context: Any) -> dict[str, Any]:
    state, doc = event["state"], event["state"]["doc"]
    with logging_json.step_context("start_extraction", event["execution_arn"], doc["doc_id"]):
        _maybe_force_fail("start_extraction")
        return steps.start_extraction(_extractor(), _checked_key(state))


def check_extraction(event: dict[str, Any], context: Any) -> dict[str, Any]:
    doc, job = event["state"]["doc"], event["state"]["job"]
    with logging_json.step_context("check_extraction", event["execution_arn"], doc["doc_id"]):
        _maybe_force_fail("check_extraction")
        return steps.check_extraction(_extractor(), job["job_id"], job["started_at"])


def save_extraction(event: dict[str, Any], context: Any) -> dict[str, Any]:
    doc, job = event["state"]["doc"], event["state"]["job"]
    with logging_json.step_context("save_extraction", event["execution_arn"], doc["doc_id"]):
        _maybe_force_fail("save_extraction")
        return steps.save_extraction(_extractor(), job["job_id"], doc["sha256"])


def index(event: dict[str, Any], context: Any) -> dict[str, Any]:
    state, doc = event["state"], event["state"]["doc"]
    with logging_json.step_context("index", event["execution_arn"], doc["doc_id"]):
        _maybe_force_fail("index")
        embedder, store = _embedder_and_store()
        return steps.index(_extractor(), embedder, store, _checked_key(state), doc["sha256"])

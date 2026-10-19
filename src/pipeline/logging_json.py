"""JSON logs for the Lambda handlers and the local API: one JSON object per line.

Every Lambda line carries document_id, execution_arn, step and status, so one document can be
followed through CloudWatch Logs. API lines carry request_id, method, path, status_code and
duration_ms; the startup line carries the provider names. Only the message and these named
fields are written: never the event, the question, the API key, document text, or exception
arguments.
"""

import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

FIELDS = (
    "document_id",
    "execution_arn",
    "step",
    "status",
    "error_type",
    # API (src/api/main.py): one line per request, and provider names at startup
    "request_id",
    "method",
    "path",
    "status_code",
    "duration_ms",
    "embedder",
    "vector_store",
    "reranker",
    "generator",
)
QUIET_LOGGERS = ("botocore", "boto3", "urllib3", "httpx", "httpcore", "pinecone")

logger = logging.getLogger("pipeline")

# Lambda runs one invocation at a time per container, so a module-level dict is enough.
_context: dict[str, str] = {}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, Any] = {
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for field in FIELDS:
            value = getattr(record, field, None) or _context.get(field)
            if value:
                entry[field] = value
        return json.dumps(entry)


def configure() -> None:
    """Use JSON on the root handlers (Lambda installs one), or add one when running locally."""
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    for handler in root.handlers:
        handler.setFormatter(JsonFormatter())
    root.setLevel(logging.INFO)
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)


def set_document(document_id: str) -> None:
    """Add the document ID once it is known (RegisterDocument computes it)."""
    _context["document_id"] = document_id


@contextmanager
def step_context(step: str, execution_arn: str, document_id: str = "") -> Iterator[None]:
    """Log STARTED, then SUCCEEDED or FAILED (with the error class name only) for one step."""
    _context.clear()
    _context.update(step=step, execution_arn=execution_arn, document_id=document_id)
    logger.info("step started", extra={"status": "STARTED"})
    try:
        yield
    except Exception as error:
        logger.error("step failed", extra={"status": "FAILED", "error_type": type(error).__name__})
        raise
    else:
        logger.info("step succeeded", extra={"status": "SUCCEEDED"})
    finally:
        _context.clear()

"""Real Textract + S3 test. Opt-in: uv run --env-file .env pytest -m integration

Needs S3_BUCKET and TEXTRACT_TEST_PDF (path to a local public PDF). The first run costs
about 0.004 USD per page; later runs hit the S3 cache and do not call Textract.
"""

import hashlib
import os
from pathlib import Path
from typing import Any

import pytest

from src.providers.textract import TextractExtractor

pytestmark = pytest.mark.integration


class NoTextract:
    """Fails the test if Textract is called."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"Textract was called ({name}) although the cache should hit")


@pytest.fixture
def pdf() -> Path:
    if not os.environ.get("S3_BUCKET") or not os.environ.get("TEXTRACT_TEST_PDF"):
        pytest.skip("set S3_BUCKET and TEXTRACT_TEST_PDF to run")
    return Path(os.environ["TEXTRACT_TEST_PDF"])


def test_real_extraction_then_cache_hit(pdf: Path) -> None:
    extractor = TextractExtractor.from_env()
    key = extractor.upload(pdf)

    doc = extractor.extract(key)

    assert len(doc.pages) > 0
    assert any(page.lines for page in doc.pages)
    assert extractor.has_cache(hashlib.sha256(pdf.read_bytes()).hexdigest())

    cached_only = TextractExtractor(extractor.bucket, extractor.s3, NoTextract())
    assert cached_only.extract(key) == doc

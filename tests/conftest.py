from pathlib import Path

import pytest

from src.models import ExtractedDocument
from src.providers.fakes import FakeExtractor

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_fixture_path() -> Path:
    return FIXTURES / "extracted_sample.json"


@pytest.fixture
def sample_doc(sample_fixture_path: Path) -> ExtractedDocument:
    return FakeExtractor(sample_fixture_path).extract("incoming/sample_smpc.pdf")

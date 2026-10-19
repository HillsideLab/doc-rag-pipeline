"""AnthropicApiGenerator against a fake SDK client. The Anthropic API is never called."""

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from src.models import Chunk, SearchHit
from src.pipeline.logging_json import JsonFormatter
from src.prompting import DONT_KNOW, SYSTEM_PROMPT
from src.providers import anthropic_api
from src.providers.anthropic_api import MAX_RETRIES, AnthropicApiGenerator, GenerationError
from src.providers.base import Generator
from src.providers.fakes import NO_ANSWER

MODEL = "test-model"
QUESTION = "What are the excipients?"


class FakeMessages:
    """Stands in for `client.messages`. Records requests, returns a fixed reply."""

    def __init__(self, reply: str, stop_reason: str) -> None:
        self.reply = reply
        self.stop_reason = stop_reason
        self.requests: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        return SimpleNamespace(
            model=kwargs["model"],
            # Thinking is on by default, so a thinking block comes before the text.
            content=[
                SimpleNamespace(type="thinking", thinking="thinking text"),
                SimpleNamespace(type="text", text=self.reply),
            ],
            stop_reason=self.stop_reason,
            usage=SimpleNamespace(input_tokens=1234, output_tokens=56),
        )


class FakeAnthropic:
    def __init__(self, reply: str, stop_reason: str = "end_turn") -> None:
        self.messages = FakeMessages(reply, stop_reason)


def hits() -> list[SearchHit]:
    return [
        SearchHit(
            chunk=Chunk(
                chunk_id=f"d:p{page}:c0",
                doc_id="d",
                source_file="cablivi-epar-product-information_en.pdf",
                page=page,
                chunk_type="text",
                section="6.1 List of excipients",
                text=f"passage text {page}",
            ),
            score=1.0,
        )
        for page in (10, 11, 12)
    ]


def generate(reply: str, stop_reason: str = "end_turn") -> tuple[FakeAnthropic, Any]:
    client = FakeAnthropic(reply, stop_reason)
    answer = AnthropicApiGenerator(client, MODEL).generate(QUESTION, hits())
    return client, answer


def test_satisfies_generator_interface() -> None:
    assert isinstance(AnthropicApiGenerator(FakeAnthropic(""), MODEL), Generator)


def test_request_uses_model_and_grounding_prompt() -> None:
    client, _ = generate("Sucrose [1].")
    request = client.messages.requests[0]
    assert request["model"] == MODEL
    assert request["max_tokens"] == anthropic_api.MAX_TOKENS
    assert request["system"] == SYSTEM_PROMPT
    assert "temperature" not in request  # current models reject non-default sampling
    user = request["messages"][0]["content"]
    assert "[1] Cablivi, 6.1 List of excipients, page 10 (chunk d:p10:c0)" in user
    assert "passage text 12" in user
    assert user.endswith(f"Question: {QUESTION}")


def test_prompt_rules() -> None:
    assert "Do not use outside knowledge" in SYSTEM_PROMPT
    assert DONT_KNOW in SYSTEM_PROMPT
    assert "square brackets" in SYSTEM_PROMPT
    assert "Do not give medical advice" in SYSTEM_PROMPT


def test_answer_is_the_text_block_only() -> None:
    _, answer = generate("  Sucrose [1].  ")
    assert answer.answer == "Sucrose [1]."
    assert answer.generator == "anthropic"


def test_citations_are_every_passage_in_order() -> None:
    # Only [2] is cited, but the list stays aligned so that [n] is citations[n-1].
    _, answer = generate("Polysorbate 80 [2].")
    assert [c.chunk_id for c in answer.citations] == ["d:p10:c0", "d:p11:c0", "d:p12:c0"]


def test_dont_know_keeps_the_searched_passages() -> None:
    _, answer = generate(DONT_KNOW)
    assert answer.answer == DONT_KNOW
    assert len(answer.citations) == 3


def test_no_hits_does_not_call_the_api() -> None:
    client = FakeAnthropic("unused")
    answer = AnthropicApiGenerator(client, MODEL).generate(QUESTION, [])
    assert answer.answer == NO_ANSWER
    assert client.messages.requests == []


@pytest.mark.parametrize(
    ("reply", "stop_reason"), [("Sucrose [1", "max_tokens"), ("", "refusal"), ("", "end_turn")]
)
def test_unusable_reply_raises(reply: str, stop_reason: str) -> None:
    with pytest.raises(GenerationError, match="stop_reason"):
        generate(reply, stop_reason)


def test_log_has_model_and_tokens_but_no_text(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    generate("Sucrose and polysorbate 80 [1][2].")
    records = [r for r in caplog.records if r.getMessage() == "generation"]
    assert len(records) == 1
    record: Any = records[0]
    assert (record.model, record.input_tokens, record.output_tokens) == (MODEL, 1234, 56)
    assert record.stop_reason == "end_turn"
    assert record.cited_passages == 2
    line = JsonFormatter().format(record)
    for text in (QUESTION, "excipients", "passage text", "Sucrose", "thinking text"):
        assert text not in line


@pytest.mark.parametrize("missing", ["ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"])
def test_from_env_requires_key_and_model(monkeypatch: pytest.MonkeyPatch, missing: str) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", MODEL)
    monkeypatch.delenv(missing)
    with pytest.raises(RuntimeError, match=missing):
        AnthropicApiGenerator.from_env()


def test_from_env_builds_client_with_retry_and_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    # Creating the SDK client makes no network call.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", MODEL)
    generator = AnthropicApiGenerator.from_env()
    assert generator.model == MODEL
    assert generator.client.max_retries == MAX_RETRIES
    assert generator.client.timeout == anthropic_api.TIMEOUT_SECONDS

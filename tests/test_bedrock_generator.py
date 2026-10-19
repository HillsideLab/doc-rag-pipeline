"""BedrockClaudeGenerator against a fake bedrock-runtime client. Bedrock is never called."""

from typing import Any

from src.models import Chunk, SearchHit
from src.providers.base import Generator
from src.providers.bedrock import (
    DONT_KNOW,
    SYSTEM_PROMPT,
    BedrockClaudeGenerator,
    cited_positions,
)
from src.providers.fakes import NO_ANSWER

PROFILE_ID = "test-inference-profile"


class FakeBedrockRuntime:
    """Stands in for boto3's bedrock-runtime client. Records requests, returns a fixed reply."""

    def __init__(self, reply: str) -> None:
        self.reply = reply
        self.requests: list[dict[str, Any]] = []

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        return {"output": {"message": {"role": "assistant", "content": [{"text": self.reply}]}}}


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


def generate(reply: str) -> tuple[FakeBedrockRuntime, Any]:
    client = FakeBedrockRuntime(reply)
    answer = BedrockClaudeGenerator(client, PROFILE_ID).generate("What are the excipients?", hits())
    return client, answer


def test_satisfies_generator_interface() -> None:
    assert isinstance(BedrockClaudeGenerator(FakeBedrockRuntime(""), PROFILE_ID), Generator)


def test_request_uses_inference_profile_and_grounding_prompt() -> None:
    client, _ = generate("Sucrose [1].")
    request = client.requests[0]
    assert request["modelId"] == PROFILE_ID
    assert request["inferenceConfig"]["temperature"] == 0
    system = request["system"][0]["text"]
    assert system == SYSTEM_PROMPT
    assert "only the given passages" in system
    assert DONT_KNOW in system
    assert "square brackets" in system
    user = request["messages"][0]["content"][0]["text"]
    assert "[1] Cablivi, 6.1 List of excipients, page 10 (chunk d:p10:c0)" in user
    assert "passage text 12" in user
    assert user.endswith("Question: What are the excipients?")


def test_citations_follow_the_cited_passages() -> None:
    _, answer = generate("Sucrose [2] and polysorbate [3][2]. See also [9].")
    assert [c.chunk_id for c in answer.citations] == ["d:p11:c0", "d:p12:c0"]
    assert answer.generator == "bedrock"


def test_answer_without_marks_cites_every_passage() -> None:
    _, answer = generate("Sucrose and polysorbate.")
    assert len(answer.citations) == 3


def test_dont_know_has_no_citations() -> None:
    _, answer = generate(DONT_KNOW)
    assert answer.answer == DONT_KNOW
    assert answer.citations == []


def test_no_hits_does_not_call_bedrock() -> None:
    client = FakeBedrockRuntime("unused")
    answer = BedrockClaudeGenerator(client, PROFILE_ID).generate("question", [])
    assert answer.answer == NO_ANSWER
    assert client.requests == []


def test_cited_positions_ignores_out_of_range_and_repeats() -> None:
    assert cited_positions("[0] [1] [3] [1] [4]", count=3) == [0, 2]

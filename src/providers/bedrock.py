"""Generator backed by Claude on Amazon Bedrock (Converse API). NOT VERIFIED: Bedrock is
blocked by an account restriction, so this has only been run against a fake client.

Claude is called with an inference profile ID (from `aws bedrock list-inference-profiles`),
not a bare model ID. The ID comes from BEDROCK_INFERENCE_PROFILE_ID and has no default here.
The boto3 client is passed in, so tests use a small fake and never touch the network.
"""

import os
import re
from typing import Any

from src.citations import citation_for, source_label
from src.models import Answer, SearchHit
from src.providers.fakes import NO_ANSWER

DONT_KNOW = "I don't know based on the provided documents."

SYSTEM_PROMPT = f"""You answer questions about medicines using only the numbered passages \
from public product information documents that are given to you.
Rules:
1. Use only the given passages as evidence. Do not use outside knowledge.
2. If the passages do not contain the answer, reply exactly: {DONT_KNOW}
3. Cite every statement with the passage number in square brackets, for example [1] or [2][3].
Keep the answer short and factual."""

CITATION_MARK = re.compile(r"\[(\d+)\]")


def build_prompt(question: str, hits: list[SearchHit]) -> str:
    """User message: numbered passages with their source, then the question."""
    passages = "\n\n".join(
        f"[{n}] {source_label(hit.chunk)}\n{hit.chunk.text}" for n, hit in enumerate(hits, 1)
    )
    return f"Passages:\n\n{passages}\n\nQuestion: {question}"


def cited_positions(text: str, count: int) -> list[int]:
    """0-based positions of the passages cited as [n] in `text`, in first-cited order.
    Numbers outside 1..count are ignored."""
    positions: list[int] = []
    for mark in CITATION_MARK.findall(text):
        position = int(mark) - 1
        if 0 <= position < count and position not in positions:
            positions.append(position)
    return positions


class BedrockClaudeGenerator:
    name = "bedrock"  # the profile ID is not shown, since a profile ARN contains the account ID

    def __init__(self, client: Any, inference_profile_id: str, max_tokens: int = 512) -> None:
        self.client = client
        self.inference_profile_id = inference_profile_id
        self.max_tokens = max_tokens

    @classmethod
    def from_env(cls) -> "BedrockClaudeGenerator":
        """Build the real client. Credentials come from AWS_PROFILE via boto3, never from code."""
        import boto3  # imported here so unit tests never need AWS configuration

        profile_id = os.environ.get("BEDROCK_INFERENCE_PROFILE_ID")
        if not profile_id:
            raise RuntimeError(
                "BEDROCK_INFERENCE_PROFILE_ID is not set. Set it in .env "
                "(see aws bedrock list-inference-profiles)"
            )
        session = boto3.Session(region_name=os.environ.get("AWS_REGION", "us-east-1"))
        return cls(session.client("bedrock-runtime"), profile_id)

    def generate(self, question: str, hits: list[SearchHit]) -> Answer:
        if not hits:
            return Answer(answer=NO_ANSWER, citations=[], generator=self.name)
        response = self.client.converse(
            modelId=self.inference_profile_id,
            system=[{"text": SYSTEM_PROMPT}],
            messages=[{"role": "user", "content": [{"text": build_prompt(question, hits)}]}],
            inferenceConfig={"maxTokens": self.max_tokens, "temperature": 0},
        )
        text = response["output"]["message"]["content"][0]["text"].strip()
        if text.startswith(DONT_KNOW):
            return Answer(answer=text, citations=[], generator=self.name)
        # Every other answer carries citations: the cited passages, or all of them if the
        # model cited none.
        positions = cited_positions(text, len(hits)) or list(range(len(hits)))
        return Answer(
            answer=text,
            citations=[citation_for(hits[i].chunk) for i in positions],
            generator=self.name,
        )

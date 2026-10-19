"""Generator backed by Claude through the Anthropic API (official `anthropic` SDK).

Used because Bedrock is blocked by an account restriction: same prompt as the Bedrock
generator (src/prompting.py), different transport. The key comes from ANTHROPIC_API_KEY and
the model from ANTHROPIC_MODEL; neither has a default in code. The SDK client is passed in,
so tests use a small fake and never touch the network.

Logs carry the model name and token counts only: never the question, passages, answer or key.
"""

import logging
import os
import time
from typing import Any

from src.citations import citation_for
from src.models import Answer, SearchHit
from src.prompting import SYSTEM_PROMPT, build_prompt, cited_positions
from src.providers.fakes import NO_ANSWER

logger = logging.getLogger(__name__)

# Fixed in code, not read from the environment (only names and keys are settings).
# Thinking tokens count toward max_tokens; the answer itself is a few hundred tokens, so 2048
# leaves room for both. Hitting it is an error (see generate), never a cut-off answer.
MAX_TOKENS = 2048
# One /ask waits at most about TIMEOUT_SECONDS * (MAX_RETRIES + 1).
TIMEOUT_SECONDS = 30.0
# The SDK retries only 408/409/429/5xx and connection errors (not auth or credit-balance
# errors). One retry absorbs a short hiccup; failed requests are not billed.
MAX_RETRIES = 1
# Short, grounded extraction does not need deep thinking; low effort keeps tokens down.
EFFORT = "low"


class GenerationError(RuntimeError):
    """The model returned no usable answer (cut off at max_tokens, or refused)."""


class AnthropicApiGenerator:
    name = "anthropic"  # the model name goes to the log, not to Answer.generator

    def __init__(self, client: Any, model: str, max_tokens: int = MAX_TOKENS) -> None:
        self.client = client
        self.model = model
        self.max_tokens = max_tokens

    @classmethod
    def from_env(cls) -> "AnthropicApiGenerator":
        """Build the real client. Both variables are checked before the client is created."""
        import anthropic  # imported here so unit tests never need the SDK client

        api_key = _require_env("ANTHROPIC_API_KEY")
        model = _require_env("ANTHROPIC_MODEL")
        # api_key is passed explicitly so the SDK never falls back to another credential source.
        client = anthropic.Anthropic(
            api_key=api_key, timeout=TIMEOUT_SECONDS, max_retries=MAX_RETRIES
        )
        return cls(client, model)

    def generate(self, question: str, hits: list[SearchHit]) -> Answer:
        if not hits:
            return Answer(answer=NO_ANSWER, citations=[], generator=self.name)
        start = time.perf_counter()
        # No temperature: current models reject non-default sampling values with a 400.
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": build_prompt(question, hits)}],
            output_config={"effort": EFFORT},
        )
        # Thinking is on by default, so the content can hold thinking blocks; keep text only.
        text = "".join(block.text for block in response.content if block.type == "text").strip()
        logger.info(
            "generation",
            extra={
                "model": response.model,
                "input_tokens": response.usage.input_tokens,
                "output_tokens": response.usage.output_tokens,
                "stop_reason": response.stop_reason,
                "cited_passages": len(cited_positions(text, len(hits))),
                "duration_ms": round((time.perf_counter() - start) * 1000, 1),
            },
        )
        if response.stop_reason in ("max_tokens", "refusal") or not text:
            raise GenerationError(f"no usable answer (stop_reason={response.stop_reason})")
        # Citations come from retrieval, never from the model: every passage it was given, in
        # the same order, so [n] in the answer is always citations[n-1].
        return Answer(
            answer=text,
            citations=[citation_for(hit.chunk) for hit in hits],
            generator=self.name,
        )


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. Set {name} in .env")
    return value

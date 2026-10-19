"""The grounding prompt shared by every model-backed Generator (Bedrock, Anthropic API).

One prompt, several transports: the passages are numbered [1]..[n] in retrieval order, and
the model must answer only from them and cite them by number.
"""

import re

from src.citations import source_label
from src.models import SearchHit

DONT_KNOW = "I don't know based on the provided documents."

SYSTEM_PROMPT = f"""You answer questions about medicines using only the numbered passages \
from public product information documents that are given to you.
Rules:
1. Use only the given passages as evidence. Do not use outside knowledge.
2. If the passages do not contain the answer, reply exactly: {DONT_KNOW}
3. Cite every statement with the passage number in square brackets, for example [1] or [2][3].
Use only the numbers of the passages given.
4. Do not give medical advice or recommendations. Only state what the passages say.
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

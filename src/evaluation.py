"""Retrieval evaluation: did the expected chunks appear in the top k results?

A question is a hit@k when at least one expected chunk_id is in the top k. Recall@k is the
share of expected chunk_ids found in the top k (stricter, e.g. both halves of 6.1).
"""

import json
from pathlib import Path

from pydantic import BaseModel


class EvalQuestion(BaseModel):
    id: str
    question: str
    doc_id: str | None = None
    expected: list[str]
    note: str = ""


class EvalResult(BaseModel):
    question: EvalQuestion
    top_ids: list[str]
    hit: bool
    recall: float


def load_questions(path: Path) -> list[EvalQuestion]:
    return [EvalQuestion.model_validate(item) for item in json.loads(path.read_text())]


def score(question: EvalQuestion, ranked_ids: list[str], k: int) -> EvalResult:
    top = ranked_ids[:k]
    found = [chunk_id for chunk_id in question.expected if chunk_id in top]
    return EvalResult(
        question=question,
        top_ids=top,
        hit=bool(found),
        recall=len(found) / len(question.expected),
    )

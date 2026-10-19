from pathlib import Path

from src.evaluation import EvalQuestion, load_questions, score

QUESTIONS = Path(__file__).parent.parent / "eval" / "retrieval_questions.json"


def question(expected: list[str]) -> EvalQuestion:
    return EvalQuestion(id="q", question="?", expected=expected)


def test_hit_when_any_expected_chunk_is_in_top_k() -> None:
    result = score(question(["a", "b"]), ["x", "a", "y", "b"], k=2)
    assert result.hit
    assert result.recall == 0.5
    assert result.top_ids == ["x", "a"]


def test_miss_when_expected_chunk_is_below_top_k() -> None:
    result = score(question(["b"]), ["x", "y", "b"], k=2)
    assert not result.hit
    assert result.recall == 0.0


def test_question_set_file_is_valid() -> None:
    questions = load_questions(QUESTIONS)
    assert len(questions) == 5
    assert all(q.expected for q in questions)
    assert len({q.id for q in questions}) == len(questions)

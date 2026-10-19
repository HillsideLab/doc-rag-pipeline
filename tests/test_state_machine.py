"""Structure of infra/statemachine.asl.json: retries, failure paths and transitions.

Terraform fills in the ${...} placeholders; here they are replaced with dummy values.
"""

import json
import re
from pathlib import Path
from typing import Any

import pytest

ASL = Path(__file__).parent.parent / "infra" / "statemachine.asl.json"
TRANSIENT = {
    "Lambda.ServiceException",
    "Lambda.AWSLambdaException",
    "Lambda.SdkClientException",
    "Lambda.TooManyRequestsException",
    "TransientError",
}


@pytest.fixture(scope="module")
def states() -> dict[str, dict[str, Any]]:
    text = re.sub(r"\$\{(\w+)\}", r"dummy-\1", ASL.read_text())
    return json.loads(text)["States"]


def lambda_tasks(states: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        name: state
        for name, state in states.items()
        if state.get("Resource") == "arn:aws:states:::lambda:invoke"
    }


def test_every_lambda_retries_only_transient_errors_three_attempts_in_total(states) -> None:
    tasks = lambda_tasks(states)
    assert set(tasks) == {
        "RegisterDocument",
        "StartExtraction",
        "CheckExtraction",
        "SaveExtraction",
        "IndexDocument",
    }
    for name, task in tasks.items():
        [retry] = task["Retry"]
        assert set(retry["ErrorEquals"]) == TRANSIENT, name
        assert retry["MaxAttempts"] == 2, name  # first try + 2 retries = 3 attempts (SPEC 11)


def test_every_task_after_register_ends_in_mark_failed(states) -> None:
    for name, state in states.items():
        if state["Type"] != "Task" or name in {"RegisterDocument", "MarkFailed"}:
            continue
        [catch] = state["Catch"]
        assert catch["ErrorEquals"] == ["States.ALL"] and catch["Next"] == "MarkFailed", name
        assert catch["ResultPath"] == "$.error", name
    assert states["MarkFailed"]["Next"] == "Failed"
    assert states["RegisterDocument"]["Catch"][0]["Next"] == "RegisterFailed"


def test_mark_failed_records_failed_status_and_error(states) -> None:
    values = states["MarkFailed"]["Parameters"]["ExpressionAttributeValues"]
    assert values[":status"] == {"S": "FAILED"}
    assert values[":error"] == {"S.$": "$.error.Error"}


def test_cache_hit_skips_textract(states) -> None:
    [choice] = states["CacheHit"]["Choices"]
    assert choice["Variable"] == "$.doc.cached" and choice["Next"] == "IndexDocument"
    assert states["CacheHit"]["Default"] == "StartExtraction"


def test_textract_is_polled_by_wait_and_choice(states) -> None:
    assert states["StartExtraction"]["Next"] == "WaitForTextract"
    assert states["WaitForTextract"]["Type"] == "Wait"
    assert states["CheckExtraction"]["Next"] == "JobDone"
    assert states["JobDone"]["Default"] == "WaitForTextract"
    assert states["JobDone"]["Choices"][0]["Next"] == "SaveExtraction"


def test_every_transition_target_exists(states) -> None:
    targets = set()
    for state in states.values():
        targets.add(state.get("Next"))
        targets.add(state.get("Default"))
        targets.update(c["Next"] for c in state.get("Choices", []) + state.get("Catch", []))
    targets.discard(None)
    assert targets <= set(states)

"""Direct Collaboration Driver v1 (Issue #14.B) — reviewer client + strict output schema."""
from __future__ import annotations

import pytest

import json

from core.collaboration.reviewer_client import (
    FixtureReviewerClient,
    OpenAIReviewerClient,
    ReviewerSchemaError,
    load_openai_key,
    validate_reviewer_output,
)

_SHA = "a" * 40


def test_checkpoint_output_must_be_a_decision_with_verdict_and_echoed_sha():
    ok = validate_reviewer_output(
        {"decision_type": "DECISION", "verdict": "GO", "reviewed_sha": _SHA, "message": "scope ok"},
        request_kind="CHECKPOINT", expected_sha=_SHA)
    assert ok.decision_type == "DECISION"
    assert ok.verdict == "GO"
    assert ok.reviewed_sha == _SHA


def test_checkpoint_output_rejects_mismatched_reviewed_sha():
    with pytest.raises(ReviewerSchemaError, match="reviewed_sha"):
        validate_reviewer_output(
            {"decision_type": "DECISION", "verdict": "GO", "reviewed_sha": "b" * 40,
             "message": "x"}, request_kind="CHECKPOINT", expected_sha=_SHA)


def test_checkpoint_output_rejects_missing_or_bad_verdict():
    with pytest.raises(ReviewerSchemaError, match="verdict"):
        validate_reviewer_output(
            {"decision_type": "DECISION", "reviewed_sha": _SHA, "message": "x"},
            request_kind="CHECKPOINT", expected_sha=_SHA)


def test_question_output_must_be_a_response():
    ok = validate_reviewer_output(
        {"decision_type": "RESPONSE", "message": "use exponential backoff"},
        request_kind="QUESTION", expected_sha=_SHA)
    assert ok.decision_type == "RESPONSE"
    with pytest.raises(ReviewerSchemaError, match="decision_type"):
        validate_reviewer_output({"decision_type": "DECISION", "verdict": "GO", "reviewed_sha": _SHA,
                                  "message": "x"}, request_kind="QUESTION", expected_sha=_SHA)


def test_proposal_output_must_be_critique_or_recommendation():
    for dt in ("CRITIQUE", "RECOMMENDATION"):
        ok = validate_reviewer_output({"decision_type": dt, "message": "consider X"},
                                      request_kind="PROPOSAL", expected_sha=_SHA)
        assert ok.decision_type == dt
    with pytest.raises(ReviewerSchemaError):
        validate_reviewer_output({"decision_type": "RESPONSE", "message": "x"},
                                 request_kind="PROPOSAL", expected_sha=_SHA)


def test_empty_message_is_rejected():
    with pytest.raises(ReviewerSchemaError, match="message"):
        validate_reviewer_output({"decision_type": "RESPONSE", "message": "   "},
                                 request_kind="QUESTION", expected_sha=_SHA)


def test_fixture_client_returns_scripted_output_and_records_calls():
    client = FixtureReviewerClient(lambda msg: {"decision_type": "DECISION", "verdict": "NO-GO",
                                                "reviewed_sha": msg["head_sha"],
                                                "message": "fix the failing test first"})
    out = client.review(system_contract="be an independent reviewer",
                        evidence={"diff_stat": "1 file changed"},
                        message={"kind": "CHECKPOINT", "head_sha": _SHA, "thread_id": "t"})
    assert out["verdict"] == "NO-GO"
    assert client.calls == 1
    assert client.last_system_contract.startswith("be an independent")


def test_openai_client_shapes_request_and_parses_json_without_network():
    seen = {}

    def fake_create(model, messages):
        seen["model"] = model
        seen["system"] = messages[0]["content"]
        seen["user"] = messages[1]["content"]
        return json.dumps({"decision_type": "DECISION", "verdict": "GO", "reviewed_sha": _SHA,
                           "message": "scope ok"})

    client = OpenAIReviewerClient(model="test-model", api_key="x", create=fake_create)
    out = client.review(system_contract="reviewer contract",
                        evidence={"diff_stat": "1 file"}, message={"kind": "CHECKPOINT",
                        "head_sha": _SHA, "branch": "feat/x", "body": "please review"})
    assert out["verdict"] == "GO"
    assert seen["model"] == "test-model"
    payload = json.loads(seen["user"])
    assert payload["request_kind"] == "CHECKPOINT"
    assert payload["head_sha"] == _SHA
    assert "evidence" in payload


def test_openai_client_rejects_non_json_output():
    client = OpenAIReviewerClient(api_key="x", create=lambda m, msgs: "not json at all")
    try:
        client.review(system_contract="c", evidence={}, message={"kind": "QUESTION", "head_sha": _SHA})
        raise AssertionError("expected ReviewerSchemaError")
    except ReviewerSchemaError:
        pass


def test_load_openai_key_prefers_env():
    assert load_openai_key({"OPENAI_API_KEY": "sk-abc"}) == "sk-abc"
    assert load_openai_key({"AIQA_HOME": "/nonexistent-dir-xyz"}) == ""

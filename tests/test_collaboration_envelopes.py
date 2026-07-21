"""Direct Collaboration Driver v1 (Issue #14.A) — bounded, SHA-bound collaboration envelopes."""
from __future__ import annotations

import pytest

from core.collaboration.envelopes import (
    CODE_BOUND_KINDS,
    EnvelopeError,
    make_envelope,
)

_SHA = "a" * 40
_OTHER_SHA = "b" * 40


def test_question_envelope_binds_full_sha_branch_thread_and_next_action():
    env = make_envelope(kind="QUESTION", thread_id="t-1", actor="claude-worker",
                        body="Which retry policy should the driver use?", head_sha=_SHA,
                        branch="feat/x", pr_number=14, evidence_refs=["diff:1", "ci:run/123"],
                        requested_next_action="RESPONSE")
    assert env["kind"] == "QUESTION"
    assert env["thread_id"] == "t-1"
    assert env["head_sha"] == _SHA
    assert env["branch"] == "feat/x"
    assert env["pr_number"] == 14
    assert env["evidence_refs"] == ["diff:1", "ci:run/123"]
    assert env["requested_next_action"] == "RESPONSE"
    assert env["idempotency_key"]           # present and non-empty
    assert env["created_at"]                # timestamp bound


def test_code_bound_kinds_require_exact_full_40_char_sha():
    # Issue #14 requires the EXACT full head SHA; the relay's 7-64 hex is too loose here.
    for kind in ("QUESTION", "PROPOSAL", "CHECKPOINT"):
        assert kind in CODE_BOUND_KINDS
        with pytest.raises(EnvelopeError, match="40"):
            make_envelope(kind=kind, thread_id="t", actor="claude-worker",
                          head_sha="abc1234", branch="feat/x")  # 7 hex -> rejected


def test_decision_requires_verdict_and_full_reviewed_sha():
    with pytest.raises(EnvelopeError, match="verdict"):
        make_envelope(kind="DECISION", thread_id="t", actor="gpt-reviewer",
                      head_sha=_SHA, branch="feat/x", reviewed_sha=_SHA)  # no verdict
    ok = make_envelope(kind="DECISION", thread_id="t", actor="gpt-reviewer", head_sha=_SHA,
                       branch="feat/x", verdict="GO", reviewed_sha=_SHA, in_reply_to="cp-1")
    assert ok["verdict"] == "GO"
    assert ok["reviewed_sha"] == _SHA
    with pytest.raises(EnvelopeError, match="verdict"):
        make_envelope(kind="DECISION", thread_id="t", actor="gpt-reviewer", head_sha=_SHA,
                      branch="feat/x", verdict="MAYBE", reviewed_sha=_SHA)


def test_idempotency_key_is_stable_across_attempts_but_changes_with_sha():
    a1 = make_envelope(kind="CHECKPOINT", thread_id="t", actor="claude-worker", body="ready",
                       head_sha=_SHA, branch="feat/x", attempt=1)
    a2 = make_envelope(kind="CHECKPOINT", thread_id="t", actor="claude-worker", body="ready",
                       head_sha=_SHA, branch="feat/x", attempt=5)
    other = make_envelope(kind="CHECKPOINT", thread_id="t", actor="claude-worker", body="ready",
                          head_sha=_OTHER_SHA, branch="feat/x", attempt=1)
    assert a1["idempotency_key"] == a2["idempotency_key"]      # retries dedupe
    assert a1["idempotency_key"] != other["idempotency_key"]   # different SHA -> different key


def test_body_is_redacted_before_it_ever_leaves_the_constructor():
    env = make_envelope(kind="PROPOSAL", thread_id="t", actor="claude-worker",
                        body="use Authorization: Bearer abcdefghijklmnopqrstuvwxyz here",
                        head_sha=_SHA, branch="feat/x")
    assert "abcdefghijklmnopqrstuvwxyz" not in env["body"]
    assert "REDACT" in env["body"]


def test_unknown_kind_is_rejected():
    with pytest.raises(EnvelopeError, match="kind"):
        make_envelope(kind="SHIP_IT", thread_id="t", actor="claude-worker", head_sha=_SHA,
                      branch="feat/x")


def test_needs_owner_and_ack_do_not_require_a_sha():
    ack = make_envelope(kind="ACKNOWLEDGEMENT", thread_id="t", actor="claude-worker",
                        body="received", in_reply_to="dec-1")
    assert ack["kind"] == "ACKNOWLEDGEMENT"
    esc = make_envelope(kind="NEEDS_OWNER", thread_id="t", actor="driver",
                        body="daily budget cap reached")
    assert esc["kind"] == "NEEDS_OWNER"

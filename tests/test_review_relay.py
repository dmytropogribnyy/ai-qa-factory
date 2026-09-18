"""Review Relay MCP — role separation, immutable SHA-bound decisions, and secret redaction."""
from __future__ import annotations

import json

import pytest

from core.review_relay import ReviewRelay, ReviewRelayError


def _checkpoint(relay: ReviewRelay):
    return relay.submit_checkpoint(slice_name="Slice 3", branch="slice-3-budget",
                                   head_sha="a" * 40, base_sha="b" * 40, pr_number=11,
                                   summary="Budget ledger complete", question="Review please",
                                   evidence="42 focused tests passed")


def test_checkpoint_decision_ack_round_trip(tmp_path):
    relay = ReviewRelay(str(tmp_path))
    cp = _checkpoint(relay)
    assert relay.list_checkpoints()["total"] == 1
    decision = relay.post_decision(checkpoint_id=cp["checkpoint_id"], decision="GO",
                                   reviewed_sha="a" * 40, message="Scope verified")
    assert decision["next_slice_authorized"] is True
    assert decision["merge_authorized"] is False
    assert relay.get_decision(cp["checkpoint_id"])["status"] == "decided"
    relay.acknowledge_decision(checkpoint_id=cp["checkpoint_id"], note="received")
    assert relay.get_checkpoint(cp["checkpoint_id"])["status"] == "acked"


def test_go_or_no_go_is_bound_to_exact_checkpoint_sha(tmp_path):
    relay = ReviewRelay(str(tmp_path))
    cp = _checkpoint(relay)
    with pytest.raises(ReviewRelayError, match="does not match"):
        relay.post_decision(checkpoint_id=cp["checkpoint_id"], decision="NO-GO",
                            reviewed_sha="c" * 40, message="wrong head")


def test_decisions_are_immutable(tmp_path):
    relay = ReviewRelay(str(tmp_path))
    cp = _checkpoint(relay)
    relay.post_decision(checkpoint_id=cp["checkpoint_id"], decision="COMMENT",
                        reviewed_sha="a" * 40, message="first")
    with pytest.raises(ReviewRelayError, match="already exists"):
        relay.post_decision(checkpoint_id=cp["checkpoint_id"], decision="GO",
                            reviewed_sha="a" * 40, message="second")


def test_relay_redacts_secrets_before_persistence(tmp_path):
    relay = ReviewRelay(str(tmp_path))
    cp = relay.submit_checkpoint(slice_name="Slice", branch="branch", head_sha="a" * 40,
                                 summary="Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
                                 evidence="password=supersecret")
    raw = json.dumps(relay.get_checkpoint(cp["checkpoint_id"]))
    assert "abcdefghijklmnopqrstuvwxyz" not in raw
    assert "supersecret" not in raw
    assert "REDACTED" in raw


def test_checkpoint_id_is_path_confined(tmp_path):
    relay = ReviewRelay(str(tmp_path))
    with pytest.raises(ReviewRelayError, match="invalid checkpoint_id"):
        relay.get_checkpoint("../../etc/passwd")


def test_mcp_role_catalog_and_gate(tmp_path, monkeypatch):
    monkeypatch.setenv("AIQA_OUTPUT_ROOT", str(tmp_path))
    monkeypatch.setenv("AIQA_REVIEW_RELAY_ROLE", "worker")
    from integrations.mcp.review_relay_server import call_handler, tool_names
    assert "relay_submit_checkpoint" in tool_names()
    assert "relay_post_decision" not in tool_names()
    blocked = json.loads(call_handler("relay_post_decision", {}))
    assert blocked["status"] == "blocked"


def test_text_redacts_before_truncating_at_the_limit_boundary():
    # A Bearer token needs >=16 chars to match the redactor. If length were truncated FIRST, the
    # limit would slice the token below 16 chars so the pattern no longer matched, leaking the
    # fragment. Redacting first removes the whole secret regardless of the limit.
    from core.review_relay import _text
    token = "abcdefghijklmnopqrstuvwxyz"          # 26 chars
    out = _text("Bearer " + token, limit=17)      # truncate-first would keep only ~10 token chars
    assert "abcdefghij" not in out                # no leaked token fragment
    assert "REDACT" in out


def test_runtime_role_both_is_rejected(monkeypatch):
    # A production process is strictly one role; there is no runtime "both".
    # (A4.5: the wording changed when the environment stopped being able to grant `reviewer`.
    # The property under test is unchanged - an unrecognised role is refused, never defaulted.)
    from integrations.mcp.review_relay_server import relay_role, set_relay_role
    set_relay_role(None)
    monkeypatch.setenv("AIQA_REVIEW_RELAY_ROLE", "both")
    with pytest.raises(RuntimeError):
        relay_role()


def test_reviewer_identity_is_server_side_not_client(tmp_path, monkeypatch):
    monkeypatch.setenv("AIQA_OUTPUT_ROOT", str(tmp_path))
    # A4.5: `reviewer` is DECLARED, never inherited - an inherited environment would let one actor
    # review its own checkpoints. This test is about the reviewer IDENTITY being server-side, which
    # is unchanged; only how the role is selected moved from the environment to an explicit call.
    from integrations.mcp import review_relay_server as relay
    # monkeypatch, not `set_relay_role`, so the declaration is restored when this test ends - a
    # module global left set would silently grant `reviewer` to every later test in the session.
    monkeypatch.setattr(relay, "_DECLARED_ROLE", "reviewer")
    monkeypatch.delenv("AIQA_REVIEW_RELAY_ROLE", raising=False)
    monkeypatch.setenv("AIQA_RELAY_REVIEWER_ID", "gpt-5-reviewer")
    cp = ReviewRelay(str(tmp_path)).submit_checkpoint(
        slice_name="s", branch="b", head_sha="a" * 40, summary="x")
    from integrations.mcp.review_relay_server import call_handler
    out = json.loads(call_handler("relay_post_decision", {
        "checkpoint_id": cp["checkpoint_id"], "decision": "GO", "reviewed_sha": "a" * 40,
        "message": "ok", "reviewer": "attacker-forged-id"}))
    assert out["reviewer"] == "gpt-5-reviewer"    # server-side config wins; client value ignored

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

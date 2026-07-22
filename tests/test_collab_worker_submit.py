"""Issue #17 — worker-side Direct-Driver submission CLI a fresh session-independent writer uses to
submit its canonical-protocol messages (PROPOSAL / CHECKPOINT / QUESTION) and ACK a decision."""
from __future__ import annotations

from core.collaboration.store import CollaborationStore
from tools.collab_worker_submit import main

_TID = "pkt-20260722T000000Z-abcdef01"
_SHA = "a" * 40


def test_submit_proposal_appends_sha_bound_envelope(tmp_path):
    out = str(tmp_path)
    rc = main(["--output-root", out, "--thread", _TID, "--kind", "PROPOSAL",
               "--branch", "feat/scout-target-confidence", "--head-sha", _SHA, "--body", "my plan"])
    assert rc == 0
    msgs = CollaborationStore(out).thread(_TID)["messages"]
    proposal = next(m for m in msgs if m["kind"] == "PROPOSAL")
    assert "my plan" in proposal["body"]
    assert proposal["head_sha"] == _SHA and proposal["branch"] == "feat/scout-target-confidence"


def test_submit_checkpoint_from_body_file(tmp_path):
    out = str(tmp_path)
    body = tmp_path / "cp.md"
    body.write_text("checkpoint: tests green", encoding="utf-8")
    rc = main(["--output-root", out, "--thread", _TID, "--kind", "CHECKPOINT",
               "--branch", "feat/x", "--head-sha", _SHA, "--body-file", str(body), "--pr", "19"])
    assert rc == 0
    cp = next(m for m in CollaborationStore(out).thread(_TID)["messages"] if m["kind"] == "CHECKPOINT")
    assert "checkpoint: tests green" in cp["body"] and cp["pr_number"] == 19


def test_submit_ack_records_acknowledgement(tmp_path):
    out = str(tmp_path)
    rc = main(["--output-root", out, "--thread", _TID, "--kind", "ACKNOWLEDGEMENT",
               "--in-reply-to", "decisionkey123", "--body", "understood"])
    assert rc == 0
    acks = [m for m in CollaborationStore(out).thread(_TID)["messages"] if m["kind"] == "ACKNOWLEDGEMENT"]
    assert acks and acks[-1]["in_reply_to"] == "decisionkey123"


def test_ack_without_in_reply_to_is_rejected(tmp_path):
    rc = main(["--output-root", str(tmp_path), "--thread", _TID, "--kind", "ACKNOWLEDGEMENT",
               "--body", "oops"])
    assert rc == 2                                          # cannot ACK nothing


def test_code_bound_kind_requires_a_valid_head_sha(tmp_path):
    # A PROPOSAL is SHA-bound: an invalid/missing head must fail closed, not persist a bad envelope.
    rc = main(["--output-root", str(tmp_path), "--thread", _TID, "--kind", "PROPOSAL",
               "--branch", "feat/x", "--head-sha", "not-a-sha", "--body", "x"])
    assert rc == 2
    assert CollaborationStore(str(tmp_path)).thread(_TID)["messages"] == []

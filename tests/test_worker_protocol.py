"""Issue #17 — pull-first worker reply path (GPT direction, PR #19 comment 5043429613).

The session-independent writer submits a request, waits (free, no spend) on the local Direct-Driver
store for the reply correlated by exact ``in_reply_to``, ACKs, implements, checkpoints — and a restart
must never duplicate a GPT request or repeat a completed phase.
"""
from __future__ import annotations

from core.collaboration.envelopes import make_envelope
from core.collaboration.store import CollaborationStore
from core.collaboration.worker_protocol import (
    ack,
    find_reply,
    submit_request,
    wait_for_reply,
    worker_status,
)
from tools.collab_worker import main as worker_cli

_TID = "pkt-20260722T000000Z-abcdef01"
_SHA = "a" * 40
_SHA2 = "b" * 40


def _reply(store, in_reply_to, kind="RECOMMENDATION"):
    store.append(make_envelope(kind=kind, thread_id=_TID, actor="gpt-reviewer", body="looks ok",
                               head_sha=_SHA, branch="feat/x", in_reply_to=in_reply_to))


def test_submit_proposal_is_phase_idempotent_on_restart(tmp_path):
    out = str(tmp_path)
    first = submit_request(out, thread_id=_TID, kind="PROPOSAL", body="plan v1",
                           branch="feat/x", head_sha=_SHA)
    assert first["duplicate"] is False
    # A restarted writer resubmitting (even with a different body) must NOT create a second request.
    again = submit_request(out, thread_id=_TID, kind="PROPOSAL", body="plan v2 after restart",
                           branch="feat/x", head_sha=_SHA)
    assert again["duplicate"] is True
    assert again["idempotency_key"] == first["idempotency_key"]
    proposals = [m for m in CollaborationStore(out).thread(_TID)["messages"] if m["kind"] == "PROPOSAL"]
    assert len(proposals) == 1                                  # no duplicate GPT request
    assert len(CollaborationStore(out).open_requests()) == 1    # reviewer reviews exactly once


def test_wait_returns_only_the_correlated_reply(tmp_path):
    out = str(tmp_path)
    store = CollaborationStore(out)
    sub = submit_request(out, thread_id=_TID, kind="PROPOSAL", body="plan", branch="feat/x", head_sha=_SHA)
    _reply(store, in_reply_to="someone-elses-request-key")      # a reply to a DIFFERENT request
    assert find_reply(out, thread_id=_TID, in_reply_to=sub["idempotency_key"]) is None
    _reply(store, in_reply_to=sub["idempotency_key"])           # the correlated reply
    got = find_reply(out, thread_id=_TID, in_reply_to=sub["idempotency_key"])
    assert got is not None and got["kind"] == "RECOMMENDATION"


def test_wait_timeout_is_a_free_no_spend_state(tmp_path):
    out = str(tmp_path)
    clock = iter([0.0, 0.0, 10.0])                              # deadline calc, check, past deadline
    res = wait_for_reply(out, thread_id=_TID, in_reply_to="k", timeout_s=5.0, poll_s=1.0,
                         clock=lambda: next(clock), sleep=lambda _s: None)
    assert res is None
    assert CollaborationStore(out).thread(_TID)["messages"] == []   # waiting wrote nothing, spent nothing


def test_checkpoint_is_idempotent_per_exact_head_sha(tmp_path):
    out = str(tmp_path)
    a = submit_request(out, thread_id=_TID, kind="CHECKPOINT", body="cp", branch="feat/x", head_sha=_SHA)
    a2 = submit_request(out, thread_id=_TID, kind="CHECKPOINT", body="cp restart", branch="feat/x",
                        head_sha=_SHA)
    assert a["duplicate"] is False and a2["duplicate"] is True
    b = submit_request(out, thread_id=_TID, kind="CHECKPOINT", body="cp new head", branch="feat/x",
                       head_sha=_SHA2)
    assert b["duplicate"] is False                              # a different exact head is a new checkpoint


def test_ack_is_idempotent_on_restart(tmp_path):
    out = str(tmp_path)
    ack(out, thread_id=_TID, decision_key="dkey", note="ok")
    ack(out, thread_id=_TID, decision_key="dkey", note="ok")    # a restarted worker replays the same ACK
    acks = [m for m in CollaborationStore(out).thread(_TID)["messages"] if m["kind"] == "ACKNOWLEDGEMENT"]
    assert len(acks) == 1


def test_status_next_derives_phase_for_a_resumed_worker(tmp_path):
    out = str(tmp_path)
    packet = {"packet_id": _TID, "head_sha": _SHA}
    assert worker_status(out, packet)["phase"] == "new"
    submit_request(out, thread_id=_TID, kind="PROPOSAL", body="plan", branch="feat/x", head_sha=_SHA)
    st = worker_status(out, packet)
    assert st["phase"] == "proposed" and "ACK" in st["next_action"].upper()


def test_cli_proposal_is_idempotent_and_wait_times_out_free(tmp_path):
    out = str(tmp_path)
    a = ["--output-root", out, "--thread", _TID, "proposal", "--branch", "feat/x", "--head-sha", _SHA]
    assert worker_cli([*a, "--body", "plan"]) == 0
    assert worker_cli([*a, "--body", "plan after restart"]) == 0        # idempotent, no second request
    proposals = [m for m in CollaborationStore(out).thread(_TID)["messages"] if m["kind"] == "PROPOSAL"]
    assert len(proposals) == 1
    # wait with no correlated reply times out with the free-retry exit code 3, spending nothing.
    rc = worker_cli(["--output-root", out, "--thread", _TID, "wait", "--in-reply-to", "nope",
                     "--timeout", "0", "--poll", "0"])
    assert rc == 3


def test_reply_from_another_thread_is_ignored(tmp_path):
    out = str(tmp_path)
    sub = submit_request(out, thread_id=_TID, kind="PROPOSAL", body="plan", branch="feat/x", head_sha=_SHA)
    other = CollaborationStore(out)
    other.append(make_envelope(kind="RECOMMENDATION", thread_id="pkt-other-000000-deadbeef",
                               actor="gpt-reviewer", body="x", head_sha=_SHA, branch="feat/x",
                               in_reply_to=sub["idempotency_key"]))
    assert find_reply(out, thread_id=_TID, in_reply_to=sub["idempotency_key"]) is None  # no cross-talk

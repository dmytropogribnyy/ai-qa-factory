"""Direct Collaboration Driver v1 (Issue #14.A2) — immutable, deduped collaboration thread store."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.collaboration.envelopes import make_envelope
from core.collaboration.store import CollaborationStore, CollaborationStoreError

_SHA = "a" * 40
_MOVED = "c" * 40


def _q(thread="t-1", body="which retry policy?"):
    return make_envelope(kind="QUESTION", thread_id=thread, actor="claude-worker", body=body,
                         head_sha=_SHA, branch="feat/x", pr_number=14, requested_next_action="RESPONSE")


def test_store_lives_under_the_shared_review_relay_base(tmp_path):
    store = CollaborationStore(str(tmp_path))
    store.append(_q())
    # One canonical store: envelopes persist under the SAME _review_relay base the relay uses.
    assert (Path(tmp_path) / "_review_relay").is_dir()
    assert any((Path(tmp_path) / "_review_relay").rglob("*.json"))


def test_append_is_immutable_and_dedupes_by_idempotency_key(tmp_path):
    store = CollaborationStore(str(tmp_path))
    env = _q()
    first = store.append(env)
    second = store.append(env)                      # restart/retry replays the same logical message
    assert first["message_id"] == second["message_id"]
    assert store.thread("t-1")["count"] == 1        # not duplicated


def test_thread_order_is_stable_under_a_coarse_clock(tmp_path):
    # Windows' coarse clock can stamp rapid appends with the SAME microsecond timestamp; the thread
    # order must still follow real insertion order (regression: RESPONSE sorted before QUESTION).
    store = CollaborationStore(str(tmp_path), clock=lambda: "2026-07-21T20:00:00.000000+00:00")
    q = store.append(_q())
    store.append(make_envelope(kind="RESPONSE", thread_id="t-1", actor="gpt-reviewer", body="a",
                               head_sha=_SHA, branch="feat/x", in_reply_to=q["idempotency_key"]))
    store.append(make_envelope(kind="ACKNOWLEDGEMENT", thread_id="t-1", actor="claude-worker",
                               body="ok", in_reply_to=q["idempotency_key"]))
    assert [m["kind"] for m in store.thread("t-1")["messages"]] == ["QUESTION", "RESPONSE",
                                                                    "ACKNOWLEDGEMENT"]


def test_thread_returns_messages_in_stored_order(tmp_path):
    store = CollaborationStore(str(tmp_path))
    q = store.append(_q())
    r = store.append(make_envelope(kind="RESPONSE", thread_id="t-1", actor="gpt-reviewer",
                                   body="use exponential backoff", head_sha=_SHA, branch="feat/x",
                                   in_reply_to=q["idempotency_key"]))
    msgs = store.thread("t-1")["messages"]
    assert [m["kind"] for m in msgs] == ["QUESTION", "RESPONSE"]
    assert msgs[1]["in_reply_to"] == q["idempotency_key"]
    assert r["message_id"] == msgs[1]["message_id"]


def test_open_requests_excludes_answered_ones(tmp_path):
    store = CollaborationStore(str(tmp_path))
    q = store.append(_q())
    assert [m["idempotency_key"] for m in store.open_requests()] == [q["idempotency_key"]]
    store.append(make_envelope(kind="RESPONSE", thread_id="t-1", actor="gpt-reviewer",
                               body="answer", head_sha=_SHA, branch="feat/x",
                               in_reply_to=q["idempotency_key"]))
    assert store.open_requests() == []              # answered -> no longer open


def test_decision_reviewed_sha_must_match_referenced_checkpoint(tmp_path):
    store = CollaborationStore(str(tmp_path))
    cp = store.append(make_envelope(kind="CHECKPOINT", thread_id="t-2", actor="claude-worker",
                                    body="slice ready", head_sha=_SHA, branch="feat/x"))
    # A decision on a MOVED head must be rejected at persistence time (stale-SHA safety).
    stale = make_envelope(kind="DECISION", thread_id="t-2", actor="gpt-reviewer", head_sha=_MOVED,
                          branch="feat/x", verdict="GO", reviewed_sha=_MOVED,
                          in_reply_to=cp["idempotency_key"])
    with pytest.raises(CollaborationStoreError, match="stale|match"):
        store.append(stale)
    good = make_envelope(kind="DECISION", thread_id="t-2", actor="gpt-reviewer", head_sha=_SHA,
                         branch="feat/x", verdict="GO", reviewed_sha=_SHA,
                         in_reply_to=cp["idempotency_key"])
    assert store.append(good)["verdict"] == "GO"


def test_persisted_record_carries_no_secret(tmp_path):
    store = CollaborationStore(str(tmp_path))
    store.append(make_envelope(kind="PROPOSAL", thread_id="t-3", actor="claude-worker",
                               body="token Authorization: Bearer abcdefghijklmnopqrstuvwxyz",
                               head_sha=_SHA, branch="feat/x"))
    raw = "".join(p.read_text(encoding="utf-8") for p in
                  (Path(tmp_path) / "_review_relay").rglob("*.json"))
    assert "abcdefghijklmnopqrstuvwxyz" not in raw
    assert "REDACT" in raw


def test_invalid_envelope_is_rejected(tmp_path):
    store = CollaborationStore(str(tmp_path))
    with pytest.raises(CollaborationStoreError):
        store.append({"kind": "QUESTION"})          # missing thread_id / idempotency_key

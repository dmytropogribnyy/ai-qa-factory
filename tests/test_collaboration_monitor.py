"""Direct Collaboration Driver v1 (Issue #14.D) — owner-visible collaboration monitor read model."""
from __future__ import annotations

import json
from pathlib import Path

from core.collaboration.envelopes import make_envelope
from core.collaboration.monitor import CollaborationMonitor
from core.collaboration.store import CollaborationStore

_SHA = "a" * 40
_MOVED = "d" * 40


def _driver_state(tmp_path, **fields):
    path = Path(tmp_path) / "_review_relay" / "collab_driver" / "state.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    base = {"stage": "IDLE", "processed": 0, "last_error": "", "updated_at": "2026-07-21T20:00:00+00:00"}
    path.write_text(json.dumps({**base, **fields}), encoding="utf-8")


def _monitor(tmp_path, head=_SHA, now="2026-07-21T20:00:30+00:00"):
    return CollaborationMonitor(str(tmp_path), head_resolver=lambda: head, clock=lambda: now,
                                stale_seconds=120)


def _checkpoint(store, thread="t-1"):
    return store.append(make_envelope(kind="CHECKPOINT", thread_id=thread, actor="claude-worker",
                                      body="ready", head_sha=_SHA, branch="feat/x", pr_number=14,
                                      evidence_refs=["ci:run/999"]))


def test_open_checkpoint_is_reviewing(tmp_path):
    store = CollaborationStore(str(tmp_path))
    _checkpoint(store)
    _driver_state(tmp_path, stage="REVIEWING")
    snap = _monitor(tmp_path).snapshot()
    t = snap["threads"][0]
    assert t["state"] == "REVIEWING"
    assert t["branch"] == "feat/x"
    assert t["pr_number"] == 14
    assert t["head_sha"] == _SHA
    assert "ci:run/999" in t["ci_refs"]


def test_driver_heartbeat_stale_is_detected(tmp_path):
    _checkpoint(CollaborationStore(str(tmp_path)))
    _driver_state(tmp_path, updated_at="2026-07-21T19:00:00+00:00")     # 1h old
    snap = _monitor(tmp_path, now="2026-07-21T20:00:30+00:00").snapshot()
    assert snap["driver"]["stale"] is True


def test_no_go_decision_is_fixing(tmp_path):
    store = CollaborationStore(str(tmp_path))
    cp = _checkpoint(store)
    store.append(make_envelope(kind="DECISION", thread_id="t-1", actor="gpt-reviewer",
                               body="fix tests", head_sha=_SHA, branch="feat/x", verdict="NO-GO",
                               reviewed_sha=_SHA, in_reply_to=cp["idempotency_key"]))
    snap = _monitor(tmp_path).snapshot()
    assert snap["threads"][0]["state"] == "FIXING"
    assert snap["threads"][0]["decision"] == "NO-GO"


def test_go_reviewed_sha_match_vs_current_head(tmp_path):
    store = CollaborationStore(str(tmp_path))
    cp = _checkpoint(store)
    store.append(make_envelope(kind="DECISION", thread_id="t-1", actor="gpt-reviewer", body="ok",
                               head_sha=_SHA, branch="feat/x", verdict="GO", reviewed_sha=_SHA,
                               in_reply_to=cp["idempotency_key"]))
    matched = _monitor(tmp_path, head=_SHA).snapshot()["threads"][0]
    assert matched["reviewed_sha_matches_head"] is True
    assert matched["stale_head"] is False
    moved = _monitor(tmp_path, head=_MOVED).snapshot()["threads"][0]
    assert moved["reviewed_sha_matches_head"] is False
    assert moved["stale_head"] is True


def test_needs_owner_sets_owner_action_required(tmp_path):
    store = CollaborationStore(str(tmp_path))
    cp = _checkpoint(store)
    store.append(make_envelope(kind="NEEDS_OWNER", thread_id="t-1", actor="collab-driver",
                               body="budget cap reached", in_reply_to=cp["idempotency_key"]))
    snap = _monitor(tmp_path).snapshot()
    assert snap["owner_action_required"] is True
    assert snap["threads"][0]["state"] == "NEEDS_OWNER"


def test_ack_marks_thread_done(tmp_path):
    store = CollaborationStore(str(tmp_path))
    cp = _checkpoint(store)
    store.append(make_envelope(kind="DECISION", thread_id="t-1", actor="gpt-reviewer", body="ok",
                               head_sha=_SHA, branch="feat/x", verdict="GO", reviewed_sha=_SHA,
                               in_reply_to=cp["idempotency_key"]))
    store.append(make_envelope(kind="ACKNOWLEDGEMENT", thread_id="t-1", actor="claude-worker",
                               body="applied", in_reply_to=cp["idempotency_key"]))
    snap = _monitor(tmp_path).snapshot()
    assert snap["threads"][0]["state"] == "DONE"
    assert snap["owner_action_required"] is False


def test_snapshot_includes_budget_and_bounded_timeline(tmp_path):
    store = CollaborationStore(str(tmp_path))
    _checkpoint(store)
    snap = _monitor(tmp_path).snapshot()
    assert "daily_calls" in snap["driver"]["budget"]
    assert len(snap["threads"][0]["timeline"]) <= 20

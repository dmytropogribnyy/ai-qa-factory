"""Direct Collaboration Driver v1 (Issue #14.D) — Dashboard collaboration monitor rendering."""
from __future__ import annotations

from core.collaboration.envelopes import make_envelope
from core.collaboration.monitor import CollaborationMonitor
from core.collaboration.store import CollaborationStore
from core.scout.dashboard import _collab_body

_SHA = "a" * 40


def test_collab_body_renders_driver_status_and_owner_banner():
    snap = {"current_head": _SHA, "owner_action_required": True,
            "driver": {"stage": "NEEDS_OWNER", "processed": 2, "heartbeat": "2026-07-21T20:00:00+00:00",
                       "stale": True, "budget": {"daily_calls": 3, "daily_usd": 0.12,
                                                 "cap_calls": 20, "cap_usd": 5.0}},
            "threads": [{"thread_id": "t-1", "state": "NEEDS_OWNER", "actor": "owner",
                         "current_action": "budget cap reached", "next_action": "owner decision",
                         "branch": "feat/x", "pr_number": 14, "head_sha": _SHA, "decision": "",
                         "reviewed_sha_matches_head": False, "stale_head": False,
                         "ci_refs": ["ci:run/1"], "timeline": [{"kind": "CHECKPOINT"},
                                                               {"kind": "NEEDS_OWNER"}]}]}
    html = _collab_body(snap)
    assert "Owner action required" in html
    assert "NEEDS_OWNER" in html
    assert "heartbeat stale" in html
    assert "feat/x" in html and "#14" in html
    assert _SHA[:12] in html


def test_collab_body_escapes_untrusted_thread_text():
    snap = {"current_head": "", "owner_action_required": False,
            "driver": {"stage": "IDLE", "processed": 0, "heartbeat": "", "stale": False,
                       "budget": {"daily_calls": 0, "daily_usd": 0.0, "cap_calls": 1, "cap_usd": 1.0}},
            "threads": [{"thread_id": "<script>x</script>", "state": "REVIEWING", "actor": "a",
                         "current_action": "b", "next_action": "c", "branch": "", "pr_number": None,
                         "head_sha": "", "decision": "", "reviewed_sha_matches_head": False,
                         "stale_head": False, "ci_refs": [], "timeline": []}]}
    html = _collab_body(snap)
    assert "<script>x</script>" not in html
    assert "&lt;script&gt;" in html


def test_monitor_to_body_integration(tmp_path):
    store = CollaborationStore(str(tmp_path))
    store.append(make_envelope(kind="CHECKPOINT", thread_id="t-1", actor="claude-worker",
                               body="ready", head_sha=_SHA, branch="feat/x", pr_number=14))
    snap = CollaborationMonitor(str(tmp_path), head_resolver=lambda: _SHA).snapshot()
    html = _collab_body(snap)
    assert "Collaboration" in html
    assert "t-1" in html
    assert "REVIEWING" in html

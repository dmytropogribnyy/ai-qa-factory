"""v3.3 operator workflow — persisted campaign run-control state machine.

Deterministic. Covers valid/invalid transitions, pause (finish current op, start no new work),
Stop & Save (preserve checkpoint), Resume (continue pending, never repeat), restart recovery
(orphaned active -> Recoverable; Paused stays Paused), no-overlap, and checkpoint persistence
across a fresh process (new object reading the same file).
"""
from __future__ import annotations

import pytest

from core.scout.run_control import (
    ANALYZING,
    DISCOVERING,
    PAUSED,
    PAUSING,
    RECOVERABLE,
    STOPPED_CHECKPOINT,
    TRIAGING,
    CampaignRunControl,
    Checkpoint,
    RunControlError,
)


def _rc(tmp_path, cid="camp-1", **kw):
    return CampaignRunControl(cid, output_dir=str(tmp_path), **kw)


def test_happy_path_transitions(tmp_path):
    rc = _rc(tmp_path)
    rc.run_now()
    assert rc.state.state == DISCOVERING
    rc.advance(TRIAGING)
    rc.advance(ANALYZING)
    rc.complete()
    assert rc.state.state == "completed"
    assert rc.state.stop_reason == "completed"


def test_invalid_transition_is_rejected(tmp_path):
    rc = _rc(tmp_path)
    rc.run_now()                       # DISCOVERING
    with pytest.raises(RunControlError):
        rc.advance("completed")        # cannot jump discovering -> completed


def test_pause_then_resume_continues_pending_without_repeat(tmp_path):
    rc = _rc(tmp_path)
    rc.run_now()
    rc.advance(TRIAGING)
    rc.advance(ANALYZING)
    rc.request_pause()
    assert rc.state.state == PAUSING
    assert rc.should_pause() is True
    # engine finishes the current atomic page op, persists checkpoint, then parks
    rc.enter_paused(Checkpoint(pending_queue=["b.com", "c.com"], completed=["a.com"],
                               budgets={"qa_analyzed": 1}))
    assert rc.state.state == PAUSED
    resumed = rc.resume()
    assert resumed == ANALYZING
    # pending work preserved, completed not repeated
    assert rc.state.checkpoint.pending_queue == ["b.com", "c.com"]
    assert rc.state.checkpoint.completed == ["a.com"]


def test_stop_and_save_preserves_checkpoint(tmp_path):
    rc = _rc(tmp_path)
    rc.run_now()
    rc.advance(TRIAGING)
    rc.advance(ANALYZING)
    rc.stop_and_save(Checkpoint(pending_queue=["x.com"], completed=["y.com"],
                                budgets={"qa_analyzed": 1}))
    assert rc.state.state == STOPPED_CHECKPOINT
    assert rc.should_stop() is True
    assert rc.state.checkpoint.pending_queue == ["x.com"]
    # continue remaining work later
    rc.resume()
    assert rc.state.state == ANALYZING


def test_checkpoint_persists_across_fresh_process(tmp_path):
    rc = _rc(tmp_path)
    rc.run_now()
    rc.advance(TRIAGING)
    rc.advance(ANALYZING)
    rc.save_checkpoint(Checkpoint(pending_queue=["p.com"], completed=["q.com"]))
    # fresh object == fresh process reloading the same file
    rc2 = _rc(tmp_path)
    assert rc2.state.state == ANALYZING
    assert rc2.state.checkpoint.pending_queue == ["p.com"]
    assert rc2.state.checkpoint.completed == ["q.com"]


def test_restart_recovery_orphaned_active_becomes_recoverable(tmp_path):
    # a run owned by a process whose heartbeat is stale
    rc = _rc(tmp_path, heartbeat_stale_s=0.0)
    rc.run_now()
    rc.advance(TRIAGING)
    rc.advance(ANALYZING)
    rc2 = _rc(tmp_path, heartbeat_stale_s=0.0)
    assert rc2.recover_on_startup() == RECOVERABLE
    assert rc2.resume() == ANALYZING


def test_paused_does_not_auto_resume_on_restart(tmp_path):
    rc = _rc(tmp_path, heartbeat_stale_s=0.0)
    rc.run_now()
    rc.advance(TRIAGING)
    rc.advance(ANALYZING)
    rc.request_pause()
    rc.enter_paused(Checkpoint(pending_queue=["z.com"]))
    rc2 = _rc(tmp_path, heartbeat_stale_s=0.0)
    # recovery leaves paused work paused (never auto-resumes)
    assert rc2.recover_on_startup() == PAUSED


def test_no_overlap_second_active_run_refused(tmp_path):
    rc = _rc(tmp_path)                 # live heartbeat (default stale window)
    rc.run_now()                       # DISCOVERING is an active state
    rc.advance(TRIAGING)
    rc.advance(ANALYZING)
    rc2 = _rc(tmp_path)                # same campaign, live owner
    with pytest.raises(RunControlError):
        rc2.run_now()


def test_blocked_and_failed_record_reason(tmp_path):
    rc = _rc(tmp_path)
    rc.run_now()
    rc.block("captcha_wall")
    assert rc.state.state == "blocked"
    assert rc.state.stop_reason == "captcha_wall"
    rc3 = _rc(tmp_path, cid="camp-3")
    rc3.run_now()
    rc3.fail("unexpected_error")
    assert rc3.state.state == "failed"
    assert rc3.state.stop_reason == "unexpected_error"

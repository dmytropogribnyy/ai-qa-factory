"""Durable supervisor for Dashboard + Direct Collaboration Driver (Issue #14 P0 5039502213).

Tests the pure supervision decision logic with injected dependencies — no real processes, network, or
Scheduled Task. The Windows Scheduled Task + live recovery are proven operationally, not here.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import time

from core.collaboration.product_packet import ProductPacketStore
from tools.collab_supervisor import (
    SupervisorConfig,
    SupervisorDeps,
    _run_with_timeout,
    supervise_once,
    writer_gate,
)

_WT0 = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)


def test_hung_driver_tick_times_out_without_blocking_supervision():
    # A stuck tick must not block the Dashboard watchdog; it surfaces as owner-visible and returns fast.
    t0 = time.time()
    out = _run_with_timeout(lambda: time.sleep(5) or {"review": {"status": "idle"}}, timeout_s=0.3)
    assert time.time() - t0 < 2.0                       # returned promptly, did not wait for the hang
    assert out["review"]["status"] == "tick_timeout"
    assert out["owner_action"] is True


def test_driver_tick_error_is_contained():
    out = _run_with_timeout(lambda: (_ for _ in ()).throw(RuntimeError("boom")), timeout_s=1.0)
    assert out["review"]["status"] == "tick_error"
    assert out["owner_action"] is True


def _deps(*, up=True, stale=False, sha="8a36374abcd", head="8a36374abcd",
          heartbeat_age=10.0, tick_result=None):
    events = {"started": 0, "killed": 0, "ticks": 0}

    def health():
        return {"up": up, "stale": stale, "sha": sha}

    def start_dashboard():
        events["started"] += 1

    def kill_dashboards():
        events["killed"] += 1

    def driver_tick():
        events["ticks"] += 1
        return tick_result or {"review": {"status": "idle"}, "deliveries": [],
                               "owner_action": False, "health": {"stage": "IDLE"}}

    deps = SupervisorDeps(health=health, current_head=lambda: head, start_dashboard=start_dashboard,
                          kill_dashboards=kill_dashboards, driver_tick=driver_tick,
                          heartbeat_age_s=lambda: heartbeat_age, clock=lambda: "2026-07-21T22:00:00+00:00")
    return deps, events


def test_healthy_dashboard_is_not_restarted(tmp_path):
    deps, ev = _deps(up=True, stale=False)
    out = supervise_once(deps, SupervisorConfig(output_root=str(tmp_path)))
    assert out["dashboard"] == "ok"
    assert ev["started"] == 0 and ev["killed"] == 0


def test_down_or_unresponsive_dashboard_is_killed_then_started(tmp_path):
    # 'down' over HTTP can be a hung-but-running Dashboard still holding :8765, so ALWAYS kill before
    # start — a bare start would race a duplicate. kill is a no-op when nothing is running.
    deps, ev = _deps(up=False)
    out = supervise_once(deps, SupervisorConfig(output_root=str(tmp_path)))
    assert out["dashboard"] == "started"
    assert ev["killed"] == 1 and ev["started"] == 1     # kill-before-start prevents a duplicate


def test_stale_dashboard_is_killed_then_restarted(tmp_path):
    deps, ev = _deps(up=True, stale=True)                # serving older code
    out = supervise_once(deps, SupervisorConfig(output_root=str(tmp_path)))
    assert out["dashboard"] == "restarted"
    assert ev["killed"] == 1 and ev["started"] == 1     # only one restart, no duplicates


def test_driver_tick_runs_every_cycle(tmp_path):
    deps, ev = _deps()
    supervise_once(deps, SupervisorConfig(output_root=str(tmp_path)))
    assert ev["ticks"] == 1                              # heartbeat kept fresh each cycle (free when idle)


def test_status_file_is_written_truthfully(tmp_path):
    deps, ev = _deps(up=True, stale=False, sha="8a36374abcd")
    supervise_once(deps, SupervisorConfig(output_root=str(tmp_path)))
    status = json.loads((Path(tmp_path) / "_review_relay" / "collab_supervisor.json").read_text())
    # Labelled as the check-time SAMPLE (truthful) rather than a claim about the current live state.
    assert status["dashboard_up_at_check"] is True
    assert status["dashboard_stale_at_check"] is False
    assert status["dashboard_action"] == "ok"
    assert status["running_sha"] == "8a36374abcd"
    assert "checked_at" in status


def test_started_dashboard_status_is_not_mislabelled_as_currently_up(tmp_path):
    # A just-restarted Dashboard is not yet serving; the status must not claim it is currently up.
    deps, ev = _deps(up=False)
    supervise_once(deps, SupervisorConfig(output_root=str(tmp_path)))
    status = json.loads((Path(tmp_path) / "_review_relay" / "collab_supervisor.json").read_text())
    assert status["dashboard_up_at_check"] is False       # honest: down at check
    assert status["dashboard_action"] == "started"        # and we started it
    assert "dashboard_up" not in status                   # no misleading "current" up field


_DEAD_PID = 2_147_483_646  # an implausible PID -> the owner process tree is provably dead


def test_writer_gate_recovers_orphaned_claim_and_becomes_eligible(tmp_path):
    # P0-A at the supervisor level: an expired lease WHOSE OWNER PROCESS TREE IS DEAD must not report
    # writer_active forever. writer_gate recovers it each cycle and re-eligibles the packet.
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="rank scout findings")
    store.claim(p["packet_id"], owner="dead-writer", owner_pids=[_DEAD_PID],
                lease_seconds=600, now=_WT0)                   # dead owner on this host
    gate = writer_gate(store, now=_WT0 + timedelta(seconds=601))
    assert gate == "eligible"
    assert store.get(p["packet_id"])["status"] == "pending"


def test_writer_gate_does_not_recover_a_live_owner_after_lease_expiry(tmp_path):
    # P0-A core: the double-writer root cause. A still-alive owner (this process) whose lease lapsed must
    # never be reclaimed -> the gate reports writer_active, not eligible (no second writer).
    import os as _os

    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    store.claim(p["packet_id"], owner="live-writer", owner_pids=[_os.getpid()],
                lease_seconds=150, now=_WT0)
    assert writer_gate(store, now=_WT0 + timedelta(seconds=1000)) == "writer_active"
    assert store.get(p["packet_id"])["status"] == "in_progress"


def test_writer_gate_reports_writer_active_while_lease_valid(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    store.claim(p["packet_id"], owner="live-writer", lease_seconds=600, now=_WT0)
    assert writer_gate(store, now=_WT0 + timedelta(seconds=60)) == "writer_active"


def test_writer_gate_reports_backoff_then_eligible(tmp_path):
    # P0-3 at the supervisor level: a packet waiting out its backoff is a free no-op, not a launch.
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    store.update(p["packet_id"],
                 next_retry_at=(_WT0 + timedelta(seconds=300)).isoformat(timespec="seconds"))
    assert writer_gate(store, now=_WT0) == "backoff"
    assert writer_gate(store, now=_WT0 + timedelta(seconds=301)) == "eligible"


def test_writer_gate_no_work_when_nothing_pending(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    assert writer_gate(store, now=_WT0) == "no_work"


def test_owner_action_from_driver_is_surfaced(tmp_path):
    deps, ev = _deps(tick_result={"review": {"status": "needs_owner"}, "deliveries": [],
                                  "owner_action": True, "health": {"stage": "NEEDS_OWNER"}})
    out = supervise_once(deps, SupervisorConfig(output_root=str(tmp_path)))
    status = json.loads((Path(tmp_path) / "_review_relay" / "collab_supervisor.json").read_text())
    assert status["owner_action_required"] is True
    assert out["owner_action"] is True

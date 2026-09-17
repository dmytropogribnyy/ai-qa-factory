"""Collaboration reliability corrections (Issue #74 TASK 0.1).

Three defects confirmed against ``main@da222ef44a8f`` by the TASK 0 live E2E and independent
controller review:

1. the prescribed bounded ACK command fails as a *subprocess* (no repo ``sys.path`` bootstrap);
2. the supervisor's outer tick bound was shorter than the delivery bound, so a legitimate long resume
   surfaced a false owner-action AND a later tick could start a second concurrent resume;
3. a durable ACK did not suppress re-delivery — suppression was success-marker-only.

These tests exercise the PRODUCTION shapes (a real subprocess for the ACK command, re-entrant delivery
for concurrency) rather than in-process conveniences, because that mismatch is what let the defects
survive a green suite.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

from core.collaboration.budget import BudgetPolicy
from core.collaboration.envelopes import make_envelope
from core.collaboration.reviewer_client import FixtureReviewerClient
from core.collaboration.service import CollaborationCycle, record_ack, submit_worker_message
from core.collaboration.session_delivery import ClaudeSessionDelivery, SessionRegistry
from core.collaboration.store import CollaborationStore

REPO_ROOT = Path(__file__).resolve().parent.parent
_SHA = "a" * 40
_SESSION = "b93d32d1-7c96-4489-945b-2a49df494349"


# --- defect 1: the prescribed bounded ACK command must work as a real subprocess -------------------
def _decision_file(tmp_path: Path, *, thread: str = "t-1", key: str = "k") -> Path:
    delivery_dir = tmp_path / "_review_relay" / "collab_delivery"
    delivery_dir.mkdir(parents=True, exist_ok=True)
    path = delivery_dir / f"{thread}_{key}.decision.json"
    path.write_text(json.dumps({"thread_id": thread, "idempotency_key": key, "kind": "RESPONSE",
                                "body": "reviewer reply"}), encoding="utf-8")
    return path


def _ack_env(base=None):
    """Environment for the ACK subprocess with PYTHONPATH removed.

    Matched case-INSENSITIVELY: Windows environment keys are case-insensitive, so an exact-key match
    would let a differently-cased `PythonPath` survive and silently make the repo importable again —
    weakening every test here that depends on the bootstrap, not PYTHONPATH, doing the work.
    """
    src = os.environ if base is None else base
    return {k: v for k, v in src.items() if k.upper() != "PYTHONPATH"}


def test_ack_env_strips_pythonpath_whatever_its_case():
    env = _ack_env({"PythonPath": "C:/injected", "PYTHONPATH": "C:/also", "PATH": "C:/keep"})
    assert [k for k in env if k.upper() == "PYTHONPATH"] == []
    assert env["PATH"] == "C:/keep"                           # unrelated vars are preserved


def _run_ack(decision_path: Path) -> subprocess.CompletedProcess:
    """Run the EXACT production command shape: `python tools/collab_ack.py --decision-file <p>` from
    the repo root with no repo PYTHONPATH and no broader shell grant."""
    return subprocess.run([sys.executable, "tools/collab_ack.py", "--decision-file",
                           str(decision_path)],
                          cwd=str(REPO_ROOT), env=_ack_env(), capture_output=True, text=True,
                          timeout=180)


def test_prescribed_ack_command_succeeds_as_a_subprocess_without_pythonpath(tmp_path):
    proc = _run_ack(_decision_file(tmp_path))
    assert proc.returncode == 0, f"stdout={proc.stdout!r} stderr={proc.stderr!r}"
    messages = CollaborationStore(str(tmp_path)).thread("t-1")["messages"]
    assert [m["kind"] for m in messages] == ["ACKNOWLEDGEMENT"]
    assert messages[0]["in_reply_to"] == "k"


def test_prescribed_ack_command_is_idempotent_as_a_subprocess(tmp_path):
    path = _decision_file(tmp_path)
    assert _run_ack(path).returncode == 0
    assert _run_ack(path).returncode == 0                     # replay of the same logical ACK
    messages = CollaborationStore(str(tmp_path)).thread("t-1")["messages"]
    assert [m["kind"] for m in messages] == ["ACKNOWLEDGEMENT"]   # exactly one, not two


def test_prescribed_ack_command_still_refuses_a_file_outside_the_delivery_dir(tmp_path):
    # NEGATIVE control: the bootstrap must not weaken the trust boundary.
    bogus = tmp_path / "evil.decision.json"
    bogus.write_text(json.dumps({"thread_id": "t-1", "idempotency_key": "k"}), encoding="utf-8")
    proc = _run_ack(bogus)
    assert proc.returncode == 2
    assert not (tmp_path / "_review_relay" / "collab_messages").exists()


# --- defect 2: outer supervisor bound vs inner delivery bound, and concurrent-resume refusal -------
def test_supervisor_tick_bound_is_derived_from_and_exceeds_the_delivery_bound():
    from core.collaboration.session_delivery import DEFAULT_DELIVERY_TIMEOUT_S
    from tools.collab_supervisor import _TICK_TIMEOUT_S

    # A legitimate resume may run for the whole delivery bound; the outer watchdog must be strictly
    # larger, or every long delivery reports a false terminal timeout.
    assert _TICK_TIMEOUT_S > DEFAULT_DELIVERY_TIMEOUT_S


def _delivery(tmp_path, runner, *, head=_SHA, **kw):
    reg = SessionRegistry(str(tmp_path / "s.json"))
    reg.bind("t-1", _SESSION)
    return ClaudeSessionDelivery(reg, str(tmp_path), exe_resolver=lambda: "claude.exe",
                                 runner=runner, head_resolver=lambda: head, **kw)


def _reply(thread="t-1", key="k"):
    dec = make_envelope(kind="RESPONSE", thread_id=thread, actor="gpt-reviewer", body="reply",
                        head_sha=_SHA, branch="main", in_reply_to="qkey")
    dec["message_id"] = f"{thread}:{key}"
    dec["idempotency_key"] = key
    return dec


def test_a_second_delivery_is_refused_while_the_first_resume_is_still_running(tmp_path):
    """The outer watchdog can elapse while a resume legitimately continues; the next tick must NOT
    start a second resume of the same reply. Re-entering deliver() from inside the runner simulates
    that overlap deterministically, without threads or a multi-minute wait."""
    reentrant = {}
    starts = []

    def runner(cmd, **kw):
        starts.append(1)
        if len(starts) == 1:                       # still "running" the first resume here
            reentrant["result"] = delivery.deliver(_reply())
        return type("P", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

    delivery = _delivery(tmp_path, runner)
    out = delivery.deliver(_reply())
    assert out["status"] == "delivered"
    assert reentrant["result"]["status"] == "in_progress"   # refused, and NOT a terminal failure
    assert len(starts) == 1                                 # exactly one resume was ever started


def test_an_in_progress_delivery_is_reported_without_owner_action(tmp_path):
    """Guard: the non-terminal ``in_progress`` status must be surfaced but never classified as a
    terminal delivery failure, or a legitimate long resume becomes a false owner alarm again."""
    submit_worker_message(str(tmp_path), kind="QUESTION", thread_id="t-1", body="q",
                          head_sha=_SHA, branch="main")
    reg = SessionRegistry(str(tmp_path / "s.json"))
    reg.bind("t-1", _SESSION)

    class _StillRunningDelivery:
        def deliver(self, reply):
            return {"status": "in_progress", "message_id": reply.get("message_id")}

    cycle = CollaborationCycle(str(tmp_path), str(tmp_path),
                               reviewer_client=FixtureReviewerClient(
                                   lambda m: {"decision_type": "RESPONSE", "message": "ok"}),
                               policy=BudgetPolicy(backoff_base_seconds=0.0),
                               registry=reg, delivery=_StillRunningDelivery())
    out = cycle.tick()
    assert [d["status"] for d in out["deliveries"]] == ["in_progress"]   # surfaced, not swallowed
    assert out["owner_action"] is False                                  # but not owner-actionable
    assert "NEEDS_OWNER" not in [m["kind"] for m in CollaborationStore(str(tmp_path))
                                 .thread("t-1")["messages"]]


def test_a_real_terminal_delivery_failure_is_still_owner_visible(tmp_path):
    # POSITIVE control for the escalation path: the in-progress lease must not mask real failures.
    submit_worker_message(str(tmp_path), kind="QUESTION", thread_id="t-1", body="q",
                          head_sha=_SHA, branch="main")
    reg = SessionRegistry(str(tmp_path / "s.json"))
    reg.bind("t-1", _SESSION)
    delivery = ClaudeSessionDelivery(reg, str(tmp_path), exe_resolver=lambda: "claude.exe",
                                     runner=lambda cmd, **kw: type("P", (), {"returncode": 1})(),
                                     head_resolver=lambda: _SHA, max_attempts=1)
    cycle = CollaborationCycle(str(tmp_path), str(tmp_path),
                               reviewer_client=FixtureReviewerClient(
                                   lambda m: {"decision_type": "RESPONSE", "message": "ok"}),
                               policy=BudgetPolicy(backoff_base_seconds=0.0),
                               registry=reg, delivery=delivery)
    cycle.tick()                                              # attempt 1 fails
    out = cycle.tick()                                        # now exhausted -> terminal
    assert out["owner_action"] is True
    assert "NEEDS_OWNER" in [m["kind"] for m in CollaborationStore(str(tmp_path))
                             .thread("t-1")["messages"]]


def test_an_active_lease_is_not_counted_as_a_delivered_delivery(tmp_path):
    """The lease is a new file type in collab_delivery/; the operator's delivery telemetry must not
    mistake an in-flight resume for a completed one."""
    from core.collaboration.monitor import CollaborationMonitor

    reentrant = {}

    def runner(cmd, **kw):
        reentrant["delivered_during"] = CollaborationMonitor(
            str(tmp_path))._delivery()["delivered"]          # lease is on disk at this moment
        return type("P", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

    delivery = _delivery(tmp_path, runner)
    delivery.deliver(_reply())
    assert reentrant["delivered_during"] == 0                # in-flight is not "delivered"
    assert CollaborationMonitor(str(tmp_path))._delivery()["delivered"] == 1   # after: exactly one


def _lease_path(tmp_path: Path, thread="t-1", key="k") -> Path:
    path = tmp_path / "_review_relay" / "collab_delivery" / f"{thread}_{key}.inprogress.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def test_a_partially_written_lease_is_treated_as_live_and_blocks_a_duplicate_resume(tmp_path):
    """The lease file is created with O_EXCL BEFORE its JSON payload is written, so a concurrent
    claimant can legitimately observe it mid-write. Parsing that as 'stale' unlinks a genuinely active
    lease and starts exactly the duplicate resume the lease exists to prevent. A fresh unparseable
    lease must therefore fail CLOSED as live."""
    starts = []

    def runner(cmd, **kw):
        starts.append(1)
        return type("P", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

    delivery = _delivery(tmp_path, runner)
    lease = _lease_path(tmp_path)
    lease.write_text("", encoding="utf-8")                 # the partial-write window: created, unwritten

    out = delivery.deliver(_reply())
    assert out["status"] == "in_progress"                  # refused, not reclaimed
    assert starts == []                                    # NO duplicate resume was started
    assert lease.exists()                                  # the active lease was not unlinked


def test_a_truncated_json_lease_is_also_treated_as_live(tmp_path):
    # Same window, caught slightly later: valid prefix, incomplete JSON.
    starts = []

    def runner(cmd, **kw):
        starts.append(1)
        return type("P", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

    delivery = _delivery(tmp_path, runner)
    lease = _lease_path(tmp_path)
    lease.write_text('{"message_id": "t-1:k", "expi', encoding="utf-8")

    assert delivery.deliver(_reply())["status"] == "in_progress"
    assert starts == []
    assert lease.exists()


def test_a_long_abandoned_malformed_lease_is_still_reclaimable(tmp_path):
    """Failing closed must not create a permanent wedge: a lease that has been malformed for longer
    than the grace window belongs to a dead process and must still be deterministically reclaimed."""
    starts = []

    def runner(cmd, **kw):
        starts.append(1)
        return type("P", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

    delivery = _delivery(tmp_path, runner)
    lease = _lease_path(tmp_path)
    lease.write_text("", encoding="utf-8")
    old = time.time() - 86400                              # malformed for a day -> genuinely abandoned
    os.utime(lease, (old, old))

    out = delivery.deliver(_reply())
    assert out["status"] == "delivered"                    # reclaimed deterministically
    assert len(starts) == 1


def test_a_stale_lease_from_a_dead_process_is_reclaimed(tmp_path):
    # A crashed resume must not wedge the reply for ever: an expired lease is reclaimable.
    starts = []

    def runner(cmd, **kw):
        starts.append(1)
        return type("P", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

    delivery = _delivery(tmp_path, runner, timeout=1)
    lease = (tmp_path / "_review_relay" / "collab_delivery" / "t-1_k.inprogress.json")
    lease.parent.mkdir(parents=True, exist_ok=True)
    lease.write_text(json.dumps({"message_id": "t-1:k", "expires_at": "2000-01-01T00:00:00+00:00"}),
                     encoding="utf-8")
    out = delivery.deliver(_reply())
    assert out["status"] == "delivered"
    assert len(starts) == 1


# --- defect 3: a durable ACK is authoritative completion proof for delivery suppression ------------
def _acking_cycle(tmp_path):
    reg = SessionRegistry(str(tmp_path / "s.json"))
    reg.bind("t-1", _SESSION)
    runs = {"n": 0}

    def runner(cmd, **kw):
        runs["n"] += 1
        return type("P", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

    delivery = ClaudeSessionDelivery(reg, str(tmp_path), exe_resolver=lambda: "claude.exe",
                                     runner=runner, head_resolver=lambda: _SHA)
    cycle = CollaborationCycle(str(tmp_path), str(tmp_path),
                               reviewer_client=FixtureReviewerClient(
                                   lambda m: {"decision_type": "RESPONSE", "message": "ok"}),
                               policy=BudgetPolicy(backoff_base_seconds=0.0),
                               registry=reg, delivery=delivery)
    return cycle, runs


def _markers(tmp_path):
    d = tmp_path / "_review_relay" / "collab_delivery"
    return [p for p in d.glob("*.json")
            if not p.name.endswith((".decision.json", ".attempts.json", ".inprogress.json"))]


def test_durable_ack_suppresses_redelivery_when_the_success_marker_is_missing(tmp_path):
    submit_worker_message(str(tmp_path), kind="QUESTION", thread_id="t-1", body="q",
                          head_sha=_SHA, branch="main")
    cycle, runs = _acking_cycle(tmp_path)
    cycle.tick()
    assert runs["n"] == 1
    store = CollaborationStore(str(tmp_path))
    reply = [m for m in store.thread("t-1")["messages"] if m["kind"] == "RESPONSE"][0]
    record_ack(str(tmp_path), thread_id="t-1", decision_key=reply["idempotency_key"])
    for marker in _markers(tmp_path):
        marker.unlink()                                       # lose the marker AFTER a durable ACK
    cycle.tick()
    assert runs["n"] == 1                                     # ACK alone must suppress the resume


def test_without_an_ack_a_missing_marker_still_delivers(tmp_path):
    # NEGATIVE control: suppression must come from a real ACK, not from skipping delivery generally.
    submit_worker_message(str(tmp_path), kind="QUESTION", thread_id="t-1", body="q",
                          head_sha=_SHA, branch="main")
    cycle, runs = _acking_cycle(tmp_path)
    cycle.tick()
    assert runs["n"] == 1
    for marker in _markers(tmp_path):
        marker.unlink()                                       # no ACK recorded this time
    cycle.tick()
    assert runs["n"] == 2                                     # normal delivery path still executes


def test_marker_dedupe_remains_intact_without_an_ack(tmp_path):
    submit_worker_message(str(tmp_path), kind="QUESTION", thread_id="t-1", body="q",
                          head_sha=_SHA, branch="main")
    cycle, runs = _acking_cycle(tmp_path)
    cycle.tick()
    cycle.tick()                                              # marker present, no ACK
    assert runs["n"] == 1                                     # existing marker dedupe preserved

"""Persisted campaign run-control state machine (v3.3).

Complements the in-process cooperative `RunControl` (threading pause/stop) with a *persisted*
campaign-level lifecycle that survives a Windows/Dashboard restart. It enforces valid
transitions, records the operator's requested control, persists a checkpoint after every atomic
step, and reads an ACTIVE run whose worker stopped reporting as RECOVERABLE (never auto-resuming
paused work, never overlapping a scheduled and an active run).

That last rule is applied when the record is READ, so every surface built on it — Observer,
Dashboard, the shared read model — reaches the same answer and none can drift; the stored row is
left exactly as the worker left it, and a worker that reports in again is believed on the next
read. `recover_on_startup` / `recover_orphaned_runs` write the same correction down once at
startup, where no worker of ours is running and Activity can carry the change.

States:
    QUEUED -> DISCOVERING -> TRIAGING -> ANALYZING -> COMPLETED
    (any active) -> PAUSING -> PAUSED -> (resume) -> ANALYZING/DISCOVERING
    (any active/paused/recoverable) -> STOPPED_CHECKPOINT   (Stop & Save)
    (any active) -> BLOCKED | FAILED
    orphaned active on restart -> RECOVERABLE -> (resume) -> ANALYZING

Controls: run_now / pause / resume / stop_and_save / continue_remaining.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from core.atomic_io import atomic_replace

QUEUED = "queued"
DISCOVERING = "discovering"
TRIAGING = "triaging"
ANALYZING = "analyzing"
PAUSING = "pausing"
PAUSED = "paused"
STOPPED_CHECKPOINT = "stopped_with_checkpoint"
RECOVERABLE = "recoverable"
COMPLETED = "completed"
BLOCKED = "blocked"
FAILED = "failed"

ACTIVE_STATES = frozenset({DISCOVERING, TRIAGING, ANALYZING, PAUSING})
TERMINAL_STATES = frozenset({STOPPED_CHECKPOINT, COMPLETED, BLOCKED, FAILED})
RESUMABLE_STATES = frozenset({PAUSED, RECOVERABLE, STOPPED_CHECKPOINT})

# Two different questions are asked of the same heartbeat, and they carry opposite costs.
#
# "May a new run start?" (``heartbeat_stale_s``, 120s) is safe to answer eagerly: being wrong once
# means one extra run the operator asked for anyway.
#
# "Should the operator be told this work is gone?" (``RECOVERY_STALE_S``) must be answered
# reluctantly. The engine heartbeats on candidate events (`DiscoveryEngine._event`), so a deep
# analysis of a single site legitimately exceeds the 120s window while it is very much alive —
# declaring that run dead is the same lie as the one being fixed here, pointing the other way.
RECOVERY_STALE_S = 900.0

# The code that prefixes every recovery reason, so a persisted row can be recognised as recovered
# without parsing prose.
RECOVERY_REASON_CODE = "worker_gone"
STOPPED_REASON_DEFAULT = "stopped by the operator (Stop & Save); the checkpoint was kept"

ALLOWED: Dict[str, frozenset] = {
    QUEUED: frozenset({DISCOVERING, BLOCKED, FAILED, STOPPED_CHECKPOINT}),
    DISCOVERING: frozenset({TRIAGING, PAUSING, STOPPED_CHECKPOINT, BLOCKED, FAILED, RECOVERABLE}),
    TRIAGING: frozenset({ANALYZING, PAUSING, STOPPED_CHECKPOINT, BLOCKED, FAILED, RECOVERABLE}),
    ANALYZING: frozenset({ANALYZING, COMPLETED, PAUSING, STOPPED_CHECKPOINT, BLOCKED, FAILED,
                          RECOVERABLE}),
    PAUSING: frozenset({PAUSED, STOPPED_CHECKPOINT, FAILED, RECOVERABLE}),
    PAUSED: frozenset({ANALYZING, DISCOVERING, TRIAGING, STOPPED_CHECKPOINT, FAILED}),
    RECOVERABLE: frozenset({ANALYZING, DISCOVERING, TRIAGING, STOPPED_CHECKPOINT, FAILED}),
    STOPPED_CHECKPOINT: frozenset({ANALYZING, DISCOVERING, TRIAGING}),   # continue remaining work
    COMPLETED: frozenset(),
    BLOCKED: frozenset({STOPPED_CHECKPOINT}),
    FAILED: frozenset({STOPPED_CHECKPOINT}),
}


class RunControlError(RuntimeError):
    """Invalid transition or an overlapping/active-run violation."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _heartbeat_age_s(heartbeat_at: str) -> float:
    """Seconds since the worker last reported. A missing or unreadable heartbeat is infinitely old.

    A run that never said when it was last alive cannot later prove that it was: treating that as
    "age unknown, assume fine" is what let a row claim to be working for a full day.
    """
    if not heartbeat_at:
        return float("inf")
    try:
        last = datetime.fromisoformat(heartbeat_at)
    except ValueError:
        return float("inf")
    return (datetime.now(timezone.utc) - last).total_seconds()


def recovery_reason(previous_state: str, age_s: float) -> str:
    """Why a run the operator did not touch stopped calling itself active."""
    age = "an unknown time" if age_s == float("inf") else f"{int(age_s)}s"
    return (f"{RECOVERY_REASON_CODE}: the worker stopped reporting {age} ago while the run was "
            f"'{previous_state}'; nothing was resumed, deleted or relabelled")


@dataclass
class Checkpoint:
    pending_queue: List[str] = field(default_factory=list)     # domains not yet analyzed
    completed: List[str] = field(default_factory=list)         # domains already analyzed
    budgets: Dict[str, Any] = field(default_factory=dict)
    current_company: str = ""
    current_page: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Checkpoint":
        known = set(cls().__dict__)
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


@dataclass
class RunControlState:
    campaign_id: str = ""
    state: str = QUEUED
    requested_control: str = ""        # "", pause, stop, resume, continue
    stop_reason: str = ""
    owner_pid: int = 0
    heartbeat_at: str = ""
    updated_at: str = ""
    checkpoint: Checkpoint = field(default_factory=Checkpoint)

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["checkpoint"] = self.checkpoint.to_dict()
        return d

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "RunControlState":
        known = set(cls().__dict__)
        kwargs = {k: v for k, v in (d or {}).items() if k in known}
        kwargs["checkpoint"] = Checkpoint.from_dict((d or {}).get("checkpoint"))
        return cls(**kwargs)


class CampaignRunControl:
    """Persisted per-campaign run-control. One JSON file per campaign; atomic writes."""

    def __init__(self, campaign_id: str, output_dir: str = "outputs", *,
                 pid: Optional[int] = None, heartbeat_stale_s: float = 120.0,
                 recovery_stale_s: Optional[float] = None) -> None:
        self.campaign_id = campaign_id
        self._out_dir = output_dir
        self._dir = Path(output_dir) / "scout" / "_runcontrol"
        self._path = self._dir / f"{campaign_id}.json"
        self._pid = pid if pid is not None else os.getpid()
        self._stale_s = heartbeat_stale_s
        self._recovery_stale_s = (RECOVERY_STALE_S if recovery_stale_s is None
                                  else float(recovery_stale_s))
        # The state this run was in when recovery corrected it, empty when nothing was corrected.
        # It is what `recover_on_startup` persists and what Activity reports; a derived correction
        # that was never written down must not be reported twice.
        self.recovered_from = ""
        self.state = self._load()

    # -- persistence -----------------------------------------------------------------------------
    def _load(self) -> RunControlState:
        self.recovered_from = ""           # each read draws its own conclusion, from this file only
        try:
            state = RunControlState.from_dict(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return RunControlState(campaign_id=self.campaign_id)
        return self._as_attended(state)

    def _as_attended(self, state: RunControlState) -> RunControlState:
        """Read an unattended ACTIVE run as RECOVERABLE — derived, never written here.

        Every surface that answers "what is this run doing" builds one of these, so putting the rule
        at the point of reading is what makes the Observer, the Dashboard and the shared read model
        incapable of disagreeing about it. Deriving rather than rewriting matters twice over: the
        operator's record of what the worker was actually doing survives being looked at, and a
        worker that comes back is believed again on the very next read instead of staying wrongly
        marked dead.
        """
        age = _heartbeat_age_s(state.heartbeat_at)
        if state.state not in ACTIVE_STATES or age < self._recovery_stale_s:
            return state
        self.recovered_from = state.state
        state.state = RECOVERABLE
        state.requested_control = ""      # a control nobody is left to honour is not pending
        state.stop_reason = recovery_reason(self.recovered_from, age)
        return state

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self.state.updated_at = _now_iso()
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(self.state.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        atomic_replace(tmp, self._path)

    def _activity(self, event: str, **fields: Any) -> None:
        """Append one operator-visible Activity event for this campaign.

        Called only AFTER the state itself is persisted: a run whose event log cannot be appended to
        is still in the correct state, and a failed audit line must not surface to the operator as a
        stop that did not happen. The log is an account of the change, never its record of truth.
        """
        try:
            from core.scout.store import RunStore
            RunStore(self._out_dir, self.campaign_id).append_event(
                {"at": _now_iso(), "event": event, "campaign_id": self.campaign_id, **fields})
        except Exception:            # noqa: BLE001 - never fail a state change on its own audit line
            pass

    # -- transitions -----------------------------------------------------------------------------
    def _transition(self, target: str) -> None:
        cur = self.state.state
        if target not in ALLOWED.get(cur, frozenset()):
            raise RunControlError(f"invalid transition {cur!r} -> {target!r}")
        self.state.state = target

    def run_now(self) -> None:
        """Start a new run. Refuses to overlap an already-active (live) run."""
        if self.state.state in ACTIVE_STATES and not self._is_orphaned():
            raise RunControlError("a run is already active for this campaign (no overlap)")
        # A fresh record answers for itself: what was inferred about the run being replaced must not
        # travel into it (a later heartbeat would otherwise restore the dead run's own state).
        self.recovered_from = ""
        self.state = RunControlState(campaign_id=self.campaign_id, state=QUEUED,
                                     owner_pid=self._pid, heartbeat_at=_now_iso())
        self._transition(DISCOVERING)
        self.state.owner_pid = self._pid
        self.state.heartbeat_at = _now_iso()
        self._save()

    def _worker_present(self) -> None:
        """Withdraw a read-time recovery when the worker itself reports in.

        The engine reloads this record on every progress event and then heartbeats, so its own
        object can carry a correction that was inferred from a gap between events. The heartbeat is
        first-hand evidence against that inference and outranks it — otherwise one long analysis
        step would let a live run persist itself as recoverable, where no later read could undo it.
        """
        if self.recovered_from:
            self.state.state = self.recovered_from
            self.state.stop_reason = ""
            self.recovered_from = ""

    def advance(self, target: str) -> None:
        self._worker_present()
        self._transition(target)
        self.state.heartbeat_at = _now_iso()
        self._save()

    def heartbeat(self) -> None:
        self._worker_present()
        self.state.heartbeat_at = _now_iso()
        self.state.owner_pid = self._pid
        self._save()

    # -- operator controls -----------------------------------------------------------------------
    def request_pause(self) -> None:
        self.state.requested_control = "pause"
        if self.state.state in (DISCOVERING, TRIAGING, ANALYZING):
            self._transition(PAUSING)
        self._save()

    def enter_paused(self, checkpoint: Optional[Checkpoint] = None) -> None:
        """The engine calls this after finishing the current atomic page op (starts no new work)."""
        if checkpoint is not None:
            self.state.checkpoint = checkpoint
        if self.state.state != PAUSED:
            self._transition(PAUSED)
        self.state.requested_control = ""
        self._save()

    def resume(self) -> str:
        """Resume from PAUSED / RECOVERABLE / STOPPED_CHECKPOINT into ANALYZING (continue pending
        work, never rediscover). Returns the state resumed into."""
        if self.state.state not in RESUMABLE_STATES:
            raise RunControlError(f"cannot resume from {self.state.state!r}")
        self.state.requested_control = ""
        # A run that is going again is no longer stopped, and the campaign page renders any
        # `stop_reason` as "Stopped because ...". Leaving the old one behind would have a resumed
        # run describe itself as running and stopped at once. Why it stopped stays in Activity.
        self.state.stop_reason = ""
        self.recovered_from = ""
        self._transition(ANALYZING)
        self.state.owner_pid = self._pid
        self.state.heartbeat_at = _now_iso()
        self._save()
        return self.state.state

    def stop_and_save(self, checkpoint: Optional[Checkpoint] = None, *, reason: str = "") -> None:
        """Stop safely, preserving completed work + pending queue + budgets + evidence.

        The reason is recorded because ``stopped_with_checkpoint`` names the state, not the cause:
        a stopped row that could not say what stopped it left the operator to guess between their
        own Stop, a crash and a budget ceiling. An explicit ``reason`` replaces any earlier one —
        including a derived recovery reason — since the stop is now the cause; the earlier reason
        stays in Activity.
        """
        if checkpoint is not None:
            self.state.checkpoint = checkpoint
        self.state.requested_control = "stop"
        self.state.stop_reason = reason or STOPPED_REASON_DEFAULT
        self._transition(STOPPED_CHECKPOINT)
        self._save()
        self._activity("run_stopped", reason=self.state.stop_reason,
                       pending=len(self.state.checkpoint.pending_queue))

    def block(self, reason: str) -> None:
        self.state.stop_reason = reason
        self._transition(BLOCKED)
        self._save()

    def fail(self, reason: str) -> None:
        self.state.stop_reason = reason
        self._transition(FAILED)
        self._save()

    def complete(self, stop_reason: str = "completed") -> None:
        self.state.stop_reason = stop_reason
        self._transition(COMPLETED)
        self.state.requested_control = ""
        self._save()

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        self._worker_present()
        self.state.checkpoint = checkpoint
        self.state.heartbeat_at = _now_iso()
        self._save()

    # -- cooperative signals (read by the engine loop) -------------------------------------------
    def should_pause(self) -> bool:
        return self.state.requested_control == "pause" or self.state.state in (PAUSING, PAUSED)

    def should_stop(self) -> bool:
        return self.state.requested_control == "stop" or self.state.state == STOPPED_CHECKPOINT

    # -- restart recovery ------------------------------------------------------------------------
    def _is_orphaned(self) -> bool:
        """An active run whose owner heartbeat is stale (crashed/closed process).

        This answers the *overlap* question only — "may a new run start for this campaign?" —
        against the short ``heartbeat_stale_s`` window. What the operator is TOLD about the run is
        decided separately and far more reluctantly, in :meth:`_as_attended`.
        """
        # Use >= so a heartbeat exactly at the stale threshold counts as stale (deterministic:
        # a 0.0 stale window means "any age is stale", not "must be strictly newer than now").
        return (self.state.state in ACTIVE_STATES
                and _heartbeat_age_s(self.state.heartbeat_at) >= self._stale_s)

    def reload(self) -> None:
        """Re-read the persisted state (another thread/process may have set a control)."""
        self.state = self._load()

    def wait_until_resumed(self, poll: float = 0.1, timeout: float = 3600.0) -> None:
        """Block until the run is resumed or stopped (reloading the persisted control each poll)."""
        import time as _time
        waited = 0.0
        while waited < timeout:
            self.reload()
            if self.state.requested_control == "stop" or self.state.state == STOPPED_CHECKPOINT:
                return
            if self.state.state not in (PAUSED, PAUSING):
                return
            _time.sleep(poll)
            waited += poll

    def recover_on_startup(self) -> str:
        """Write down what a read already derives. PAUSED work is left PAUSED (never auto-resumed).

        Startup is the one moment when correcting the stored row is safe: no worker of ours is
        running yet, so nothing can be overwritten mid-step. Persisting it means the row itself
        stops claiming work is in progress, and Activity carries the change — a state the operator
        did not ask for has to be explainable after the fact. Returns the resulting state.
        """
        if self.recovered_from and self.state.state == RECOVERABLE:
            previous, self.recovered_from = self.recovered_from, ""
            self._save()
            self._activity("run_recovered", reason=self.state.stop_reason, previous_state=previous)
        return self.state.state


def offered_controls(state: str) -> Dict[str, bool]:
    """Which operator controls make sense in a run state — decided once, where the states live.

    The campaign page used to decide this from its own copy of the vocabulary, written before
    RECOVERABLE existed. So a recovered run offered Pause — which has no worker left to pause — and
    hid Resume, the very action the same page recommended in words. A second list of state names is
    a list that stops being updated; this one travels with the progress payload instead.
    """
    resumable = state in (PAUSED, "pause_requested", RECOVERABLE)
    finished = state in (COMPLETED, STOPPED_CHECKPOINT, FAILED, "cancelled")
    return {"pause": not finished and not resumable,
            "resume": not finished and resumable,
            "stop": not finished}


def recover_orphaned_runs(output_dir: str = "outputs") -> List[Dict[str, str]]:
    """Correct every run whose worker is gone, once, at startup — the caller recovery never had.

    Never resumes, never deletes, never relabels: each run keeps its checkpoint, its provenance and
    its place, and only stops describing itself as in progress. Returns one row per corrected run so
    the caller can tell the operator what changed while they were away.
    """
    rc_dir = Path(output_dir) / "scout" / "_runcontrol"
    if not rc_dir.is_dir():
        return []
    recovered: List[Dict[str, str]] = []
    for path in sorted(rc_dir.glob("*.json")):
        control = CampaignRunControl(path.stem, output_dir)
        previous = control.recovered_from
        if not previous:
            continue
        control.recover_on_startup()
        recovered.append({"campaign_id": path.stem, "previous_state": previous,
                          "reason": control.state.stop_reason})
    return recovered

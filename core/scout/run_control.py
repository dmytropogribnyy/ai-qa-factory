"""Persisted campaign run-control state machine (v3.3).

Complements the in-process cooperative `RunControl` (threading pause/stop) with a *persisted*
campaign-level lifecycle that survives a Windows/Dashboard restart. It enforces valid
transitions, records the operator's requested control, and persists a checkpoint after every atomic
step (never auto-resuming paused work, never overlapping a scheduled and an active run).

Every state here is one a writer *asserted*. RECOVERABLE is the exception: nothing writes it any
more. An active run whose owner stopped reporting is reported as recoverable at read time by
`canonical_runs.canonical_run_state()`, from `is_unattended()` below — so the record keeps saying
what the worker last said, and a worker that comes back is authoritative again on its next heartbeat
with nothing to restore. Rows an earlier release persisted as RECOVERABLE stay readable and resumable.

States:
    QUEUED -> DISCOVERING -> TRIAGING -> ANALYZING -> COMPLETED
    (any active) -> PAUSING -> PAUSED -> (resume) -> ANALYZING/DISCOVERING
    (any active/paused/recoverable) -> STOPPED_CHECKPOINT   (Stop & Save)
    (any active) -> BLOCKED | FAILED
    active + no reporting owner -> reads as RECOVERABLE (derived; disk unchanged)

Controls: run_now / pause / resume / stop_and_save / continue_remaining.
"""
from __future__ import annotations

import itertools
import json
import os
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional
from core.atomic_io import atomic_replace

# One lock per campaign file, shared by every CampaignRunControl in this process that addresses it.
# The whole read-modify-write runs under it: the operator's Pause and the worker's heartbeat are
# separate instances holding separate snapshots, so without serialising the ENTIRE cycle a saver
# can still write a snapshot it read before someone else's change and erase it.
#
# Bound stated plainly: this serialises writers within one process, which is where the campaign
# worker thread and the Dashboard request thread both live. Serialising a second OS process would
# need a file lock and is not claimed here.
_PATH_LOCKS: Dict[str, threading.RLock] = {}
_PATH_LOCKS_GUARD = threading.Lock()

# Every write gets its own temp file. A shared `<name>.tmp` let two savers fight over one path:
# whoever replaced first consumed it and the loser's os.replace raised FileNotFoundError. This is
# the second barrier, not the fix — the lock above is what keeps state consistent.
_TMP_SEQUENCE = itertools.count()


def _lock_for(path: Path) -> threading.RLock:
    key = str(Path(path).resolve())
    with _PATH_LOCKS_GUARD:
        lock = _PATH_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _PATH_LOCKS[key] = lock
        return lock

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

# Two questions, two windows: `heartbeat_stale_s` (120s) guards run overlap, where a stalled owner
# must not block the operator for long; this one asks "is anyone still there?" and must tolerate a
# genuinely slow page op without calling live work lost.
RECOVERY_STALE_S = 900.0
RECOVERY_REASON_CODE = "worker_gone"

ALL_STATES: tuple = (QUEUED, DISCOVERING, TRIAGING, ANALYZING, PAUSING, PAUSED,
                     STOPPED_CHECKPOINT, RECOVERABLE, COMPLETED, BLOCKED, FAILED)


def heartbeat_age_s(heartbeat_at: Any) -> float:
    """Seconds since a heartbeat, or +inf when it cannot be trusted to mean anything.

    The type is checked before parsing: `fromisoformat` raises TypeError on a list and ValueError on
    a bad string, so catching only the latter made a malformed row crash the read path.
    """
    if not isinstance(heartbeat_at, str) or not heartbeat_at:
        return float("inf")
    try:
        last = datetime.fromisoformat(heartbeat_at)
    except ValueError:
        return float("inf")
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)      # legacy rows were written naive, always UTC
    return (datetime.now(timezone.utc) - last).total_seconds()


def is_unattended(state: str, heartbeat_at: Any, *,
                  recovery_stale_s: float = RECOVERY_STALE_S) -> bool:
    """True when an ACTIVE record's owner has stopped reporting for `recovery_stale_s`.

    Membership is tested BEFORE the timestamp, so a parked or finished row is never parsed however
    malformed its heartbeat is. `>=` pins the boundary: a 0.0 window means "any age is stale".
    """
    if state not in ACTIVE_STATES:
        return False
    return heartbeat_age_s(heartbeat_at) >= recovery_stale_s


def offered_controls(state: str) -> Dict[str, bool]:
    """Which operator controls are truthful for a state — the one rule, not a copy in JavaScript.

    `recoverable` gets neither Pause nor Resume: there is no worker to pause, and continuing a run
    whose worker is gone needs a relaunch this release does not have, so a Resume button would be a
    promise it cannot keep. Stop & Save stays — keeping what was collected is real.
    """
    s = str(state or "").strip().lower()
    if s in TERMINAL_STATES:
        return {"pause": False, "resume": False, "stop": False}
    if s == RECOVERABLE:
        return {"pause": False, "resume": False, "stop": True}
    if s == PAUSED:
        return {"pause": False, "resume": True, "stop": True}
    if s == PAUSING:
        return {"pause": False, "resume": False, "stop": True}
    if s in ACTIVE_STATES:
        return {"pause": True, "resume": False, "stop": True}
    return {"pause": False, "resume": False, "stop": s == QUEUED}


def recovery_reason(prior_state: str, age_s: float) -> str:
    """Why a row reads as recoverable. Derived text — never written into `stop_reason`, which
    records what something actually did."""
    tail = f"while the run was {prior_state!r}; nothing was resumed, deleted or relabelled"
    if age_s == float("inf"):
        return f"{RECOVERY_REASON_CODE}: the worker left no usable heartbeat {tail}"
    return f"{RECOVERY_REASON_CODE}: the worker stopped reporting {int(age_s)}s ago {tail}"


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
                 pid: Optional[int] = None, heartbeat_stale_s: float = 120.0) -> None:
        self.campaign_id = campaign_id
        self._dir = Path(output_dir) / "scout" / "_runcontrol"
        self._path = self._dir / f"{campaign_id}.json"
        self._pid = pid if pid is not None else os.getpid()
        self._stale_s = heartbeat_stale_s
        self.state = self._load()

    # -- persistence -----------------------------------------------------------------------------
    def _load(self) -> RunControlState:
        try:
            return RunControlState.from_dict(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            return RunControlState(campaign_id=self.campaign_id)

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self.state.updated_at = _now_iso()
        tmp = self._path.with_name(
            f"{self._path.name}.{os.getpid()}.{next(_TMP_SEQUENCE)}.tmp")
        tmp.write_text(json.dumps(self.state.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        atomic_replace(tmp, self._path)

    @contextmanager
    def _mutation(self) -> Iterator[None]:
        """Serialise one campaign's whole read-modify-write: fresh read -> change -> durable write.

        Re-reading inside the lock is the point. Each instance keeps its own ``state`` snapshot, so
        a worker that loaded the run before the operator paused it would otherwise write that older
        view back and silently drop ``requested_control`` — no exception, just a lost instruction.

        A mutation that raises (a refused transition, an unwritable disk) leaves the file untouched:
        the save only runs when the body completed.
        """
        with _lock_for(self._path):
            self.state = self._load()
            yield
            self._save()

    # -- transitions -----------------------------------------------------------------------------
    def _transition(self, target: str) -> None:
        cur = self.state.state
        if target not in ALLOWED.get(cur, frozenset()):
            raise RunControlError(f"invalid transition {cur!r} -> {target!r}")
        self.state.state = target

    def run_now(self) -> None:
        """Start a new run. Refuses to overlap an already-active (live) run."""
        with self._mutation():
            if self.state.state in ACTIVE_STATES and not is_unattended(
                    self.state.state, self.state.heartbeat_at, recovery_stale_s=self._stale_s):
                raise RunControlError("a run is already active for this campaign (no overlap)")
            self.state = RunControlState(campaign_id=self.campaign_id, state=QUEUED,
                                         owner_pid=self._pid, heartbeat_at=_now_iso())
            self._transition(DISCOVERING)
            self.state.owner_pid = self._pid
            self.state.heartbeat_at = _now_iso()

    def advance(self, target: str) -> None:
        with self._mutation():
            self._transition(target)
            self.state.heartbeat_at = _now_iso()

    def begin_phase(self, target: str) -> str:
        """Atomically decide between honouring a pending control and entering the next phase.

        Checking the controls and then advancing as two steps leaves a window: a Pause landing
        between them makes the state PAUSING, and PAUSING -> TRIAGING/ANALYZING is not a legal
        transition, so the phase step fails the whole run. Re-reading before the advance does not
        close it — the gap is between the decision and the write, not before the decision.

        So the read and the decision happen under ONE hold of this campaign's lock. A concurrent
        operator either gets there first (we see the control and report it) or waits (their pause
        lands after the transition and is honoured at the next boundary). There is no in-between.

        The parking is part of the same hold. Reporting ``paused`` and letting the caller park as
        a second mutation reopens the gap one level down: a Stop landing in between would meet
        ``STOPPED_CHECKPOINT -> PAUSED``, which is not a legal transition either. A Stop that is
        already written therefore always wins here — it is checked first and never becomes a
        failure.

        Returns ``stop``, ``paused``, ``already_past`` or ``advanced``. ``stop`` and
        ``already_past`` write nothing.
        """
        with _lock_for(self._path):
            self.state = self._load()
            if self.should_stop():
                return "stop"
            if self.should_pause():
                if self.state.state != PAUSED:
                    self._transition(PAUSED)
                self.state.requested_control = ""
                self._save()
                return "paused"
            # A resume deliberately lands the run in ANALYZING — continue pending work, never
            # rediscover — so a phase already behind the run is a no-op, not an illegal transition.
            if self.state.state == ANALYZING and target in (TRIAGING, ANALYZING):
                return "already_past"
            self._transition(target)
            self.state.heartbeat_at = _now_iso()
            self._save()
            return "advanced"

    def heartbeat(self) -> None:
        """Liveness only. It reports that this worker is alive — it decides nothing else.

        Re-reading first is what keeps that true: the beat carries no opinion about the operator's
        pending control or the run's phase, so it must never write those back from an older view.
        """
        with self._mutation():
            self.state.heartbeat_at = _now_iso()
            self.state.owner_pid = self._pid

    # -- operator controls -----------------------------------------------------------------------
    def request_pause(self) -> None:
        with self._mutation():
            self.state.requested_control = "pause"
            if self.state.state in (DISCOVERING, TRIAGING, ANALYZING):
                self._transition(PAUSING)

    def enter_paused(self, checkpoint: Optional[Checkpoint] = None) -> None:
        """The engine calls this after finishing the current atomic page op (starts no new work)."""
        with self._mutation():
            if checkpoint is not None:
                self.state.checkpoint = checkpoint
            if self.state.state != PAUSED:
                self._transition(PAUSED)
            self.state.requested_control = ""

    def resume(self) -> str:
        """Resume from PAUSED / RECOVERABLE / STOPPED_CHECKPOINT into ANALYZING (continue pending
        work, never rediscover). Returns the state resumed into."""
        with self._mutation():
            if self.state.state not in RESUMABLE_STATES:
                raise RunControlError(f"cannot resume from {self.state.state!r}")
            self.state.requested_control = ""
            self._transition(ANALYZING)
            self.state.owner_pid = self._pid
            self.state.heartbeat_at = _now_iso()
        return self.state.state

    def stop_and_save(self, checkpoint: Optional[Checkpoint] = None) -> None:
        """Stop safely, preserving completed work + pending queue + budgets + evidence.

        Idempotent: a run already stopped with a checkpoint records the new checkpoint and stays
        stopped. Re-transitioning would be illegal (STOPPED_CHECKPOINT only leads back into work),
        so a worker that notices an operator's Stop and calls this on its way out would otherwise
        turn an orderly stop into a FAILED run.
        """
        with self._mutation():
            if checkpoint is not None:
                self.state.checkpoint = checkpoint
            self.state.requested_control = "stop"
            if self.state.state != STOPPED_CHECKPOINT:
                self._transition(STOPPED_CHECKPOINT)

    def block(self, reason: str) -> None:
        with self._mutation():
            self.state.stop_reason = reason
            self._transition(BLOCKED)

    def fail(self, reason: str) -> None:
        with self._mutation():
            self.state.stop_reason = reason
            self._transition(FAILED)

    def complete(self, stop_reason: str = "completed") -> None:
        with self._mutation():
            self.state.stop_reason = stop_reason
            self._transition(COMPLETED)
            self.state.requested_control = ""

    def save_checkpoint(self, checkpoint: Checkpoint) -> None:
        """Record where the worker got to. Like the heartbeat, it asserts nothing about controls."""
        with self._mutation():
            self.state.checkpoint = checkpoint
            self.state.heartbeat_at = _now_iso()

    # -- cooperative signals (read by the engine loop) -------------------------------------------
    def should_pause(self) -> bool:
        return self.state.requested_control == "pause" or self.state.state in (PAUSING, PAUSED)

    def should_stop(self) -> bool:
        return self.state.requested_control == "stop" or self.state.state == STOPPED_CHECKPOINT

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

    # There is deliberately NO startup sweep writing RECOVERABLE. Persisting it was tried and is a
    # one-way door: the record then carries a state the surviving worker never asserted, so its next
    # complete() is an illegal RECOVERABLE -> COMPLETED transition, and a wrong staleness guess
    # becomes a permanent wrong fact instead of a display the next heartbeat corrects.

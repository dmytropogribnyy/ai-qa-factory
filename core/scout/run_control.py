"""Persisted campaign run-control state machine (v3.3).

Complements the in-process cooperative `RunControl` (threading pause/stop) with a *persisted*
campaign-level lifecycle that survives a Windows/Dashboard restart. It enforces valid
transitions, records the operator's requested control, persists a checkpoint after every atomic
step, and — on a fresh process — flips an orphaned active run to RECOVERABLE (never auto-resuming
paused work, never overlapping a scheduled and an active run).

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
        tmp = self._path.with_name(self._path.name + ".tmp")
        tmp.write_text(json.dumps(self.state.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, self._path)

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
        self.state = RunControlState(campaign_id=self.campaign_id, state=QUEUED,
                                     owner_pid=self._pid, heartbeat_at=_now_iso())
        self._transition(DISCOVERING)
        self.state.owner_pid = self._pid
        self.state.heartbeat_at = _now_iso()
        self._save()

    def advance(self, target: str) -> None:
        self._transition(target)
        self.state.heartbeat_at = _now_iso()
        self._save()

    def heartbeat(self) -> None:
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
        self._transition(ANALYZING)
        self.state.owner_pid = self._pid
        self.state.heartbeat_at = _now_iso()
        self._save()
        return self.state.state

    def stop_and_save(self, checkpoint: Optional[Checkpoint] = None) -> None:
        """Stop safely, preserving completed work + pending queue + budgets + evidence."""
        if checkpoint is not None:
            self.state.checkpoint = checkpoint
        self.state.requested_control = "stop"
        self._transition(STOPPED_CHECKPOINT)
        self._save()

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
        """An active run whose owner heartbeat is stale (crashed/closed process)."""
        if self.state.state not in ACTIVE_STATES:
            return False
        hb = self.state.heartbeat_at
        if not hb:
            return True
        try:
            last = datetime.fromisoformat(hb)
        except ValueError:
            return True
        age = (datetime.now(timezone.utc) - last).total_seconds()
        # Use >= so a heartbeat exactly at the stale threshold counts as stale (deterministic:
        # a 0.0 stale window means "any age is stale", not "must be strictly newer than now").
        return age >= self._stale_s

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
        """On a fresh process: flip an orphaned ACTIVE run to RECOVERABLE. PAUSED work is left
        PAUSED (never auto-resumed). Returns the resulting state."""
        if self._is_orphaned():
            self.state.state = RECOVERABLE           # direct set: recovery is not a normal edge
            self.state.requested_control = ""
            self._save()
        return self.state.state

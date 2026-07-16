"""WorkRunState — canonical resumable state machine (Phase 8.0).

REUSE DECISION (correction #4):
- The existing `ProjectStatus` (core/schemas/project_status.py) uses free-form
  `phase` / `overall_status` strings and is NOT a formal, resumable state machine.
- `ProgressTracker` tracks completion percentages, not run lifecycle.
- Therefore WorkRunState is added as an ADDITIVE, canonical lifecycle record. It
  complements ProjectStatus (which remains unchanged) and is what lets a run resume
  after restart, retry a single failed step, and hand off between Claude, Codex and
  the CLI via artifacts rather than chat history.

SAFETY / DESIGN NOTES:
- This is a state record + transition vocabulary. No executor is attached in 8.0.
- Terminal states are immutable once reached (documented in WORK_EXECUTION_MODEL.md).

IDEMPOTENCY SCOPE (Phase 8.0 — foundation only):
- `run_idempotency_key` identifies one logical work run and supports safe resume /
  deduplication of run CREATION.
- Run-level idempotency prevents accidental duplication of a logical work run. Per-step
  and per-tool-call idempotency, execution receipts, write deduplication, and replay
  protection remain runtime responsibilities for later phases — they are NOT provided
  or enforced here.
- `state_version` supports optimistic state evolution and future concurrent-agent
  protection. `updated_at` is expected to advance only through future controlled state
  transitions, not arbitrary agent rewriting. No runtime enforcement exists in 8.0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin

# Canonical, ordered lifecycle states.
WORK_RUN_STATES: tuple[str, ...] = (
    "RECEIVED",
    "INTAKE_COMPLETE",
    "PLANNED",
    "WAITING_FOR_INFORMATION",
    "WAITING_FOR_APPROVAL",
    "READY_TO_EXECUTE",
    "EXECUTING",
    "EXECUTION_PARTIAL",
    "VERIFYING",
    "REPAIR_REQUIRED",
    "READY_FOR_REVIEW",
    "READY_FOR_DELIVERY",
    "BLOCKED",
    "FAILED",
    "CANCELLED",
    "COMPLETED",
)

WORK_RUN_STATE_SET = frozenset(WORK_RUN_STATES)

TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "CANCELLED"})

# Allowed forward transitions (documented; not enforced by an executor in 8.0).
ALLOWED_TRANSITIONS: Dict[str, tuple[str, ...]] = {
    "RECEIVED": ("INTAKE_COMPLETE", "BLOCKED", "CANCELLED"),
    "INTAKE_COMPLETE": ("PLANNED", "WAITING_FOR_INFORMATION", "BLOCKED", "CANCELLED"),
    "PLANNED": ("WAITING_FOR_APPROVAL", "READY_TO_EXECUTE", "WAITING_FOR_INFORMATION",
                "BLOCKED", "CANCELLED"),
    "WAITING_FOR_INFORMATION": ("INTAKE_COMPLETE", "PLANNED", "BLOCKED", "CANCELLED"),
    "WAITING_FOR_APPROVAL": ("READY_TO_EXECUTE", "BLOCKED", "CANCELLED"),
    "READY_TO_EXECUTE": ("EXECUTING", "BLOCKED", "CANCELLED"),
    "EXECUTING": ("EXECUTION_PARTIAL", "VERIFYING", "FAILED", "BLOCKED", "CANCELLED"),
    "EXECUTION_PARTIAL": ("EXECUTING", "VERIFYING", "REPAIR_REQUIRED", "FAILED",
                          "BLOCKED", "CANCELLED"),
    "VERIFYING": ("READY_FOR_REVIEW", "REPAIR_REQUIRED", "FAILED", "BLOCKED"),
    "REPAIR_REQUIRED": ("READY_TO_EXECUTE", "EXECUTING", "FAILED", "BLOCKED", "CANCELLED"),
    "READY_FOR_REVIEW": ("READY_FOR_DELIVERY", "REPAIR_REQUIRED", "BLOCKED", "CANCELLED"),
    "READY_FOR_DELIVERY": ("COMPLETED", "BLOCKED", "CANCELLED"),
    "BLOCKED": ("READY_TO_EXECUTE", "CANCELLED", "FAILED"),
    "FAILED": (),
    "CANCELLED": (),
    "COMPLETED": (),
}


@dataclass
class StateTransition(SchemaMixin):
    """One recorded transition in the run history (immutable audit trail entry)."""

    from_state: str = ""
    to_state: str = ""
    reason: str = ""
    actor: str = ""                             # e.g. "cli", "claude", "codex"
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StateTransition:
        return super().from_dict(data)


@dataclass
class WorkRunState(SchemaMixin):
    """Resumable lifecycle state for one work run."""

    project_id: str = ""
    work_packet_ref: str = ""
    run_idempotency_key: str = field(default_factory=lambda: str(uuid4()))
    state_version: int = 0
    status: str = "RECEIVED"
    previous_status: str = ""
    completed_steps: List[str] = field(default_factory=list)
    pending_step: str = ""
    waiting_reason: str = ""
    last_error: str = ""
    owner_agent: str = ""                        # cli | claude | codex | other
    history: List[StateTransition] = field(default_factory=list)
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "work_packet_ref": self.work_packet_ref,
            "run_idempotency_key": self.run_idempotency_key,
            "state_version": self.state_version,
            "status": self.status,
            "previous_status": self.previous_status,
            "completed_steps": list(self.completed_steps),
            "pending_step": self.pending_step,
            "waiting_reason": self.waiting_reason,
            "last_error": self.last_error,
            "owner_agent": self.owner_agent,
            "history": [h.to_dict() for h in self.history],
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkRunState:
        known = {
            "project_id", "work_packet_ref", "run_idempotency_key", "state_version",
            "status", "previous_status",
            "completed_steps", "pending_step", "waiting_reason", "last_error",
            "owner_agent", "updated_at",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["history"] = [
            StateTransition.from_dict(h) if isinstance(h, dict) else h
            for h in data.get("history", [])
        ]
        return cls(**kwargs)

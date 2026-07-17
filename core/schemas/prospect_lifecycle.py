"""Prospect Radar lifecycle contracts (Phase 8.2 — slice 3).

Planning / contracts only. A prospect-specific lifecycle vocabulary and deterministic
transition map, reusing the *shape* and audit ideas of `WorkRunState` /
`StateTransition` (uuid/versioned, history of transitions) **without** reusing the
client-work execution states. Nothing here executes, sends, schedules, or persists.

REUSE NOTES (verified against the repository):
- Serialization: `core.schemas.base.SchemaMixin`.
- Mirrors `core.schemas.work_run_state` patterns (status/previous_status/history,
  `state_version`, UTC ISO timestamps) — a parallel vocabulary, not a reuse of its states.

Semantic guarantees:
- `APPROVED` means a human approved the outreach draft — **not** that an email was sent.
- `CONTACTED` (outreach happened) is only reachable from `APPROVED` or `COOLDOWN`
  (which itself only follows an approved/contacted state) — enforced by the map and an
  explicit guard.
- `PAID_AUDIT` is a commercial lifecycle state, not a payment execution.
- Stale evidence routes via `NEEDS_RECHECK` / `EVIDENCE_EXPIRED`.
- `SUPPRESSED` and `ARCHIVED` are distinct states.
- No runtime enforcement is claimed; this is a validation/transition contract only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple
from uuid import uuid4

from core.schemas.base import SchemaMixin
from core.schemas.prospect_interaction import PROSPECT_CONTRACT_SCHEMA_VERSION

# Canonical prospect lifecycle states (normal progression + control states).
PROSPECT_STATES: Tuple[str, ...] = (
    "DISCOVERED",
    "ELIGIBLE",
    "QUICK_SCANNED",
    "BROWSER_AUDITED",
    "FINDING_VERIFIED",
    "QUALIFIED",
    "CONTACT_FOUND",
    "DRAFT_READY",
    "APPROVED",
    "CONTACTED",
    "REPLIED",
    "PAID_AUDIT",
    "CLOSED",
    "ARCHIVED",
    # Control / exceptional states.
    "REJECTED",
    "SUPPRESSED",
    "DUPLICATE",
    "NEEDS_RECHECK",
    "EVIDENCE_EXPIRED",
    "CONTACT_FIRST",
    "MANUAL_REVIEW_REQUIRED",
    "COOLDOWN",
)

PROSPECT_STATE_SET = frozenset(PROSPECT_STATES)

# Terminal states (no outgoing transitions).
TERMINAL_STATES = frozenset({"ARCHIVED", "REJECTED", "DUPLICATE"})

# States from which reaching CONTACTED is permitted (human-approved provenance).
_CONTACTED_ALLOWED_FROM = frozenset({"APPROVED", "COOLDOWN"})

# States that cannot appear as an empty-history planning snapshot: they require a
# verifiable approved lineage (an APPROVED transition carries actor + approval_ref).
_SNAPSHOT_FORBIDDEN_STATES = frozenset({
    "APPROVED", "CONTACTED", "REPLIED", "PAID_AUDIT",
})

# Deterministic allowed forward/control transitions (documented; validation only).
ALLOWED_TRANSITIONS: Dict[str, Tuple[str, ...]] = {
    "DISCOVERED": ("ELIGIBLE", "REJECTED", "DUPLICATE", "SUPPRESSED", "MANUAL_REVIEW_REQUIRED"),
    "ELIGIBLE": ("QUICK_SCANNED", "CONTACT_FIRST", "REJECTED", "SUPPRESSED", "MANUAL_REVIEW_REQUIRED"),
    "QUICK_SCANNED": ("BROWSER_AUDITED", "NEEDS_RECHECK", "REJECTED", "SUPPRESSED", "MANUAL_REVIEW_REQUIRED"),
    "BROWSER_AUDITED": ("FINDING_VERIFIED", "NEEDS_RECHECK", "REJECTED", "SUPPRESSED", "MANUAL_REVIEW_REQUIRED"),
    "FINDING_VERIFIED": ("QUALIFIED", "NEEDS_RECHECK", "EVIDENCE_EXPIRED", "REJECTED", "SUPPRESSED"),
    "QUALIFIED": ("CONTACT_FOUND", "CONTACT_FIRST", "NEEDS_RECHECK", "REJECTED", "SUPPRESSED", "ARCHIVED"),
    "CONTACT_FOUND": ("DRAFT_READY", "MANUAL_REVIEW_REQUIRED", "REJECTED", "SUPPRESSED"),
    "DRAFT_READY": ("APPROVED", "MANUAL_REVIEW_REQUIRED", "REJECTED", "SUPPRESSED"),
    "APPROVED": ("CONTACTED", "COOLDOWN", "MANUAL_REVIEW_REQUIRED", "SUPPRESSED"),
    "CONTACTED": ("REPLIED", "COOLDOWN", "CLOSED", "ARCHIVED", "SUPPRESSED"),
    "REPLIED": ("PAID_AUDIT", "CLOSED", "COOLDOWN", "ARCHIVED"),
    "PAID_AUDIT": ("CLOSED", "ARCHIVED"),
    "CLOSED": ("ARCHIVED",),
    "CONTACT_FIRST": ("CONTACT_FOUND", "DRAFT_READY", "REJECTED", "SUPPRESSED", "MANUAL_REVIEW_REQUIRED"),
    "NEEDS_RECHECK": ("QUICK_SCANNED", "BROWSER_AUDITED", "EVIDENCE_EXPIRED", "REJECTED", "ARCHIVED"),
    "EVIDENCE_EXPIRED": ("NEEDS_RECHECK", "QUICK_SCANNED", "ARCHIVED", "REJECTED"),
    "MANUAL_REVIEW_REQUIRED": ("ELIGIBLE", "QUALIFIED", "DRAFT_READY", "REJECTED", "SUPPRESSED", "ARCHIVED"),
    "COOLDOWN": ("CONTACTED", "ARCHIVED", "CLOSED", "SUPPRESSED"),
    "SUPPRESSED": ("ARCHIVED", "MANUAL_REVIEW_REQUIRED"),
    # Terminal states — no outgoing transitions.
    "REJECTED": (),
    "DUPLICATE": (),
    "ARCHIVED": (),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_iso(value: str) -> bool:
    """Whether value is a non-empty parseable ISO 8601 date/datetime."""
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def is_transition_allowed(from_state: str, to_state: str) -> bool:
    """Whether from_state → to_state is a permitted lifecycle transition."""
    return to_state in ALLOWED_TRANSITIONS.get(from_state, ())


@dataclass
class ProspectTransition(SchemaMixin):
    """One recorded lifecycle transition (immutable audit-trail entry)."""

    from_state: str = ""
    to_state: str = ""
    reason: str = ""
    actor: str = ""                             # e.g. "cli", "claude", "human"
    approval_ref: str = ""                       # provenance for an APPROVED transition
    at: str = field(default_factory=_now_iso)

    def __post_init__(self) -> None:
        if self.from_state not in PROSPECT_STATE_SET:
            raise ValueError(f"Unknown transition from_state: {self.from_state!r}")
        if self.to_state not in PROSPECT_STATE_SET:
            raise ValueError(f"Unknown transition to_state: {self.to_state!r}")
        if self.from_state == self.to_state:
            raise ValueError("a transition cannot have equal from_state and to_state")
        if not is_transition_allowed(self.from_state, self.to_state):
            raise ValueError(
                f"invalid transition {self.from_state!r} -> {self.to_state!r}"
            )
        if not _valid_iso(self.at):
            raise ValueError(f"transition timestamp must be valid ISO: {self.at!r}")
        # An APPROVED transition records (does not perform) human approval provenance.
        if self.to_state == "APPROVED":
            if not self.actor.strip():
                raise ValueError("an APPROVED transition requires a non-empty actor")
            if not self.approval_ref.strip():
                raise ValueError(
                    "an APPROVED transition requires a non-empty approval_ref"
                )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProspectTransition":
        return super().from_dict(data)


@dataclass
class ProspectLifecycle(SchemaMixin):
    """Resumable prospect lifecycle state (planning/validation only, no runtime)."""

    prospect_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    state_version: int = 0
    status: str = "DISCOVERED"
    previous_status: str = ""
    history: List[ProspectTransition] = field(default_factory=list)
    updated_at: str = field(default_factory=_now_iso)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in PROSPECT_STATE_SET:
            raise ValueError(f"Unknown prospect state: {self.status!r}")
        if self.previous_status and self.previous_status not in PROSPECT_STATE_SET:
            raise ValueError(f"Unknown previous prospect state: {self.previous_status!r}")
        if self.state_version < 0:
            raise ValueError("state_version cannot be negative")
        if not _valid_iso(self.updated_at):
            raise ValueError(f"updated_at must be valid ISO: {self.updated_at!r}")
        self._validate_history_integrity()

    def _validate_history_integrity(self) -> None:
        # state_version is the count of recorded transitions (forged counts fail).
        if self.state_version != len(self.history):
            raise ValueError(
                "state_version must equal the number of recorded transitions"
            )
        if not self.history:
            # Empty-history planning snapshot.
            if self.previous_status:
                raise ValueError("empty-history snapshot cannot have a previous_status")
            if self.status in _SNAPSHOT_FORBIDDEN_STATES:
                raise ValueError(
                    f"state {self.status!r} cannot be an empty-history snapshot without "
                    "a verifiable approved lineage"
                )
            return
        # Contiguity: each transition begins where the previous ended.
        for i in range(1, len(self.history)):
            if self.history[i - 1].to_state != self.history[i].from_state:
                raise ValueError("non-contiguous transition history")
        last = self.history[-1]
        if last.to_state != self.status:
            raise ValueError("final history to_state must match current status")
        if self.previous_status != last.from_state:
            raise ValueError(
                "previous_status must match the final transition's from_state"
            )
        # Approved lineage: any CONTACTED must be preceded by an APPROVED transition
        # (whose ProspectTransition validation already required actor + approval_ref).
        to_states = [h.to_state for h in self.history]
        if "CONTACTED" in to_states:
            first_contacted = to_states.index("CONTACTED")
            if "APPROVED" not in to_states[:first_contacted]:
                raise ValueError(
                    "CONTACTED requires a prior APPROVED transition in history"
                )

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATES

    def can_transition(self, to_state: str) -> bool:
        return is_transition_allowed(self.status, to_state)

    def apply_transition(
        self, to_state: str, reason: str = "", actor: str = "", approval_ref: str = ""
    ) -> "ProspectLifecycle":
        """Validate and record a transition (mutates + returns self). No side effects."""
        if to_state not in PROSPECT_STATE_SET:
            raise ValueError(f"Unknown prospect state: {to_state!r}")
        if not is_transition_allowed(self.status, to_state):
            raise ValueError(
                f"invalid transition {self.status!r} -> {to_state!r}"
            )
        # Human-approved provenance for outreach: CONTACTED requires an approved lineage.
        if to_state == "CONTACTED" and self.status not in _CONTACTED_ALLOWED_FROM:
            raise ValueError(
                "CONTACTED requires an APPROVED (human-reviewed) prior state"
            )
        if to_state == "APPROVED":
            if not actor.strip():
                raise ValueError("an APPROVED transition requires a non-empty actor")
            if not approval_ref.strip():
                raise ValueError(
                    "an APPROVED transition requires a non-empty approval_ref"
                )
        self.history.append(
            ProspectTransition(
                from_state=self.status,
                to_state=to_state,
                reason=reason,
                actor=actor,
                approval_ref=approval_ref,
            )
        )
        self.previous_status = self.status
        self.status = to_state
        self.state_version += 1
        self.updated_at = _now_iso()
        return self

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prospect_id": self.prospect_id,
            "schema_version": self.schema_version,
            "state_version": self.state_version,
            "status": self.status,
            "previous_status": self.previous_status,
            "history": [h.to_dict() for h in self.history],
            "updated_at": self.updated_at,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProspectLifecycle":
        known = {
            "prospect_id", "schema_version", "state_version", "status",
            "previous_status", "updated_at", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        history = data.get("history") or []
        kwargs["history"] = [
            ProspectTransition.from_dict(h) for h in history if isinstance(h, dict)
        ]
        return cls(**kwargs)

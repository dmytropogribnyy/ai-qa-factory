"""WorkStateManager — Phase 8.1 (first enforced state transitions).

Phase 8.0 declared ALLOWED_TRANSITIONS but did not enforce them. Phase 8.1 is the first
runtime phase, so transitions go through this manager: it validates against
ALLOWED_TRANSITIONS, forbids mutating a terminal state, increments state_version,
updates updated_at, and appends an immutable transition record.
"""
from __future__ import annotations

from core.schemas.work_run_state import (
    WorkRunState, StateTransition, ALLOWED_TRANSITIONS, TERMINAL_STATES,
)
from core.orchestration.providers import ClockProvider


class InvalidTransitionError(Exception):
    """Raised when a state transition is not permitted."""


class WorkStateManager:
    """Enforces the WorkRunState lifecycle."""

    def __init__(self, clock: ClockProvider) -> None:
        self._clock = clock

    def transition(
        self, state: WorkRunState, to_status: str, reason: str, actor: str
    ) -> WorkRunState:
        if state.status in TERMINAL_STATES:
            raise InvalidTransitionError(
                f"cannot transition out of terminal state {state.status}"
            )
        allowed = ALLOWED_TRANSITIONS.get(state.status, ())
        if to_status not in allowed:
            raise InvalidTransitionError(
                f"transition {state.status} -> {to_status} is not allowed"
            )
        now = self._clock.now_iso()
        state.history.append(StateTransition(
            from_state=state.status, to_state=to_status, reason=reason, actor=actor, at=now,
        ))
        state.previous_status = state.status
        state.status = to_status
        state.state_version += 1
        state.updated_at = now
        return state

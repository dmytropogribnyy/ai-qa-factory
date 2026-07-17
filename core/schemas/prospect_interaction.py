"""Prospect Radar interaction-boundary contracts (Phase 8.2 — slice 1).

Planning / contracts only. No runtime, no browser, no network, no MCP, no CLI.

Defines the typed action-class vocabulary and a **fail-closed** interaction boundary
that governs what a *future, separately approved* execution phase would be permitted
to attempt against a prospect site. Nothing here executes anything.

REUSE NOTES (verified against the repository):
- Serialization: `core.schemas.base.SchemaMixin` (its `from_dict` ignores unknown keys,
  so new optional fields stay backwards compatible / additive-safe).
- The action-class vocabulary is the typed form of the planned classes already
  documented in `docs/APPROVAL_MODEL.md` ("Prospect QA Radar — planned action classes")
  and is consistent with the existing capability-class model in
  `core/schemas/capability.py` (`CAPABILITY_CLASSES`). This is not a competing generic
  risk enum; it is the documented model made typed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin

# Shared version string for the Phase 8.2 prospect contract family.
PROSPECT_CONTRACT_SCHEMA_VERSION = "8.2.0"


class InteractionActionClass(str, Enum):
    """Risk / approval class for a single planned interaction with a prospect site.

    Ordered least → most sensitive. Mirrors the planned classes in
    `docs/APPROVAL_MODEL.md`. `DESTRUCTIVE` is blocked by default everywhere.
    """

    READ_ONLY = "READ_ONLY"
    REVERSIBLE_SESSION_WRITE = "REVERSIBLE_SESSION_WRITE"
    POTENTIAL_BUSINESS_SIDE_EFFECT = "POTENTIAL_BUSINESS_SIDE_EFFECT"
    EXTERNAL_COMMUNICATION = "EXTERNAL_COMMUNICATION"
    FINANCIAL = "FINANCIAL"
    DESTRUCTIVE = "DESTRUCTIVE"


# Classes that may never be auto-permitted. A boundary listing any of these as
# "permitted" is fail-closed corrected (they are moved out of the permitted set).
_ALWAYS_APPROVAL_REQUIRED = frozenset({
    InteractionActionClass.POTENTIAL_BUSINESS_SIDE_EFFECT.value,
    InteractionActionClass.EXTERNAL_COMMUNICATION.value,
    InteractionActionClass.FINANCIAL.value,
})

# Classes that may never be permitted or merely approval-gated — always blocked.
_ALWAYS_BLOCKED = frozenset({
    InteractionActionClass.DESTRUCTIVE.value,
})

_VALID_ACTION_CLASSES = frozenset(c.value for c in InteractionActionClass)


@dataclass
class InteractionBoundary(SchemaMixin):
    """Fail-closed boundary describing what a future execution phase may attempt.

    Defaults are maximally conservative: only `READ_ONLY` is permitted; business
    side effects, external communication and financial actions are approval-gated;
    destructive actions are blocked; real submissions and account / order / booking /
    payment / file-upload are blocked; and CAPTCHA solving/bypass plus
    access-control / proxy / stealth evasion **cannot be enabled through this
    contract** (the setters are forced off in `_enforce_invariants`).
    """

    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    permitted_action_classes: List[str] = field(
        default_factory=lambda: [InteractionActionClass.READ_ONLY.value]
    )
    approval_required_action_classes: List[str] = field(
        default_factory=lambda: [
            InteractionActionClass.POTENTIAL_BUSINESS_SIDE_EFFECT.value,
            InteractionActionClass.EXTERNAL_COMMUNICATION.value,
            InteractionActionClass.FINANCIAL.value,
        ]
    )
    blocked_action_classes: List[str] = field(
        default_factory=lambda: [InteractionActionClass.DESTRUCTIVE.value]
    )
    cleanup_required: bool = True
    public_access_only: bool = True
    authenticated_access_allowed: bool = False
    real_submission_allowed: bool = False
    account_creation_allowed: bool = False
    order_creation_allowed: bool = False
    booking_or_hold_allowed: bool = False
    payment_allowed: bool = False
    file_upload_allowed: bool = False
    # Hard safety switches — can never be enabled through this contract.
    captcha_bypass_allowed: bool = False
    access_control_evasion_allowed: bool = False
    proxy_or_stealth_evasion_allowed: bool = False
    # Reference to written authorization required before any later authorized E2E.
    written_authorization_ref: str = ""
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._enforce_invariants()

    def _enforce_invariants(self) -> None:
        # Every listed class must be a known action class (fail closed on unknowns).
        for group_name, group in (
            ("permitted_action_classes", self.permitted_action_classes),
            ("approval_required_action_classes", self.approval_required_action_classes),
            ("blocked_action_classes", self.blocked_action_classes),
        ):
            for value in group:
                if value not in _VALID_ACTION_CLASSES:
                    raise ValueError(
                        f"Unknown interaction action class {value!r} in {group_name}"
                    )
        # Fail-closed: approval-required and always-blocked classes can never be permitted.
        self.permitted_action_classes = [
            c for c in self.permitted_action_classes
            if c not in _ALWAYS_APPROVAL_REQUIRED and c not in _ALWAYS_BLOCKED
        ]
        # Destructive is always blocked and must be present in the blocked set.
        if InteractionActionClass.DESTRUCTIVE.value not in self.blocked_action_classes:
            self.blocked_action_classes.append(InteractionActionClass.DESTRUCTIVE.value)
        # Hard safety switches cannot be turned on through this contract.
        self.captcha_bypass_allowed = False
        self.access_control_evasion_allowed = False
        self.proxy_or_stealth_evasion_allowed = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InteractionBoundary":
        # super().from_dict constructs the object, which runs __post_init__ and thus
        # re-applies every fail-closed invariant on rehydration.
        return super().from_dict(data)

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
# Ordered tuple so restoration is deterministic (frozenset iteration order is not).
_MANDATORY_APPROVAL_CLASSES: tuple[str, ...] = (
    InteractionActionClass.POTENTIAL_BUSINESS_SIDE_EFFECT.value,
    InteractionActionClass.EXTERNAL_COMMUNICATION.value,
    InteractionActionClass.FINANCIAL.value,
)
_ALWAYS_APPROVAL_REQUIRED = frozenset(_MANDATORY_APPROVAL_CLASSES)

# Classes that may never be permitted or merely approval-gated — always blocked.
_ALWAYS_BLOCKED = frozenset({
    InteractionActionClass.DESTRUCTIVE.value,
})

_VALID_ACTION_CLASSES = frozenset(c.value for c in InteractionActionClass)

# Boolean side-effect flags whose enablement requires a written authorization reference.
_SIDE_EFFECT_FLAGS: tuple[str, ...] = (
    "authenticated_access_allowed",
    "real_submission_allowed",
    "account_creation_allowed",
    "order_creation_allowed",
    "booking_or_hold_allowed",
    "payment_allowed",
    "file_upload_allowed",
)


def _dedup(seq: List[str]) -> List[str]:
    """Order-preserving de-duplication."""
    seen: set[str] = set()
    out: List[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


@dataclass
class InteractionBoundary(SchemaMixin):
    """Fail-closed boundary describing what a future execution phase may attempt.

    Defaults are maximally conservative: only `READ_ONLY` is permitted; business
    side effects, external communication and financial actions are approval-gated;
    destructive actions are blocked; real submissions and account / order / booking /
    payment / file-upload are blocked; and CAPTCHA solving/bypass plus
    access-control / proxy / stealth evasion **cannot be enabled through this
    contract** (the setters are forced off in `_enforce_invariants`).

    Hardened invariants (deterministic normalization, applied on construction and on
    rehydration):
    - the mandatory approval classes (POTENTIAL_BUSINESS_SIDE_EFFECT,
      EXTERNAL_COMMUNICATION, FINANCIAL) can never vanish from both approval-required
      and blocked — each is restored to approval-required unless it is blocked;
    - a class can never be simultaneously permitted and approval-required/blocked;
      lists are de-duplicated;
    - permitting `REVERSIBLE_SESSION_WRITE` forces `cleanup_required=True`;
    - `public_access_only` wins: it forces `authenticated_access_allowed=False`;
    - enabling any side-effect flag (authenticated access, real submission, account/
      order/booking/hold, payment, file upload) requires a non-empty
      `written_authorization_ref` (else `ValueError`), and keeps the matching action
      class approval-required. Evasion switches stay off regardless of authorization.
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
        # 1. Every listed class must be a known action class (fail closed on unknowns).
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

        # 2. De-duplicate each list (order preserving) — no duplicates after normalization.
        self.permitted_action_classes = _dedup(self.permitted_action_classes)
        self.approval_required_action_classes = _dedup(self.approval_required_action_classes)
        self.blocked_action_classes = _dedup(self.blocked_action_classes)

        # 3. Destructive is always blocked and must be present in the blocked set.
        if InteractionActionClass.DESTRUCTIVE.value not in self.blocked_action_classes:
            self.blocked_action_classes.append(InteractionActionClass.DESTRUCTIVE.value)

        # 4. Mandatory approval classes may never vanish from BOTH approval-required and
        #    blocked. Deterministically restore each to approval-required unless blocked.
        for cls_value in _MANDATORY_APPROVAL_CLASSES:
            if (
                cls_value not in self.blocked_action_classes
                and cls_value not in self.approval_required_action_classes
            ):
                self.approval_required_action_classes.append(cls_value)

        # 5. A class cannot be both approval-required and blocked — blocked wins.
        self.approval_required_action_classes = [
            c for c in self.approval_required_action_classes
            if c not in self.blocked_action_classes
        ]

        # 6. Permitted may never contain an approval-required or blocked class.
        disallowed_permitted = (
            set(self.approval_required_action_classes)
            | set(self.blocked_action_classes)
            | _ALWAYS_APPROVAL_REQUIRED
            | _ALWAYS_BLOCKED
        )
        self.permitted_action_classes = [
            c for c in self.permitted_action_classes if c not in disallowed_permitted
        ]

        # 7. Hard safety switches can never be turned on through this contract —
        #    regardless of any authorization reference.
        self.captcha_bypass_allowed = False
        self.access_control_evasion_allowed = False
        self.proxy_or_stealth_evasion_allowed = False

        # 8. Public-only wins: authenticated access is forced off when public_access_only.
        if self.public_access_only:
            self.authenticated_access_allowed = False

        # 9. Permitting a reversible session write requires cleanup.
        if InteractionActionClass.REVERSIBLE_SESSION_WRITE.value in self.permitted_action_classes:
            self.cleanup_required = True

        # 10. Any enabled side-effect flag requires a written authorization reference.
        enabled_flags = [f for f in _SIDE_EFFECT_FLAGS if getattr(self, f)]
        if enabled_flags and not self.written_authorization_ref.strip():
            raise ValueError(
                "written_authorization_ref is required when side-effect flags are "
                f"enabled: {enabled_flags}"
            )

        # 11. Enabling a side-effect flag keeps its action class approval-required
        #     (unless already blocked, which is stricter).
        if self.payment_allowed:
            self._require_approval(InteractionActionClass.FINANCIAL.value)
        if (
            self.real_submission_allowed
            or self.account_creation_allowed
            or self.file_upload_allowed
        ):
            self._require_approval(InteractionActionClass.EXTERNAL_COMMUNICATION.value)
        if self.order_creation_allowed or self.booking_or_hold_allowed:
            self._require_approval(
                InteractionActionClass.POTENTIAL_BUSINESS_SIDE_EFFECT.value
            )

    def _require_approval(self, cls_value: str) -> None:
        """Ensure a class is approval-required (unless already blocked, which is stricter)."""
        if (
            cls_value not in self.blocked_action_classes
            and cls_value not in self.approval_required_action_classes
        ):
            self.approval_required_action_classes.append(cls_value)
        # Approval-required classes can never remain permitted.
        self.permitted_action_classes = [
            c for c in self.permitted_action_classes if c != cls_value
        ]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "InteractionBoundary":
        # super().from_dict constructs the object, which runs __post_init__ and thus
        # re-applies every fail-closed invariant on rehydration.
        return super().from_dict(data)

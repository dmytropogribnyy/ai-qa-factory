"""Prospect Radar governance contracts (Phase 8.2 — slice 3).

Planning / contracts only. Suppression, retention, and recheck *policies* — no runtime
enforcement, scheduler, filesystem deletion, network, or crawling. Deletion is never
executed by any schema here.

REUSE NOTES (verified against the repository):
- Serialization: `core.schemas.base.SchemaMixin`.
- `ProspectRetentionPolicy` **composes** the existing `core.schemas.cleanup.CleanupPolicy`
  (safe-by-default retention record) rather than building a competing cleanup engine; it
  forces `dry_run_required`, `preserve_git_tracked_files`, and `preserve_client_outputs`
  on so prospect retention can never weaken those safety defaults.
- Version string reuses `PROSPECT_CONTRACT_SCHEMA_VERSION`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin
from core.schemas.cleanup import CleanupPolicy
from core.schemas.prospect_identity import normalize_hostname
from core.schemas.prospect_interaction import PROSPECT_CONTRACT_SCHEMA_VERSION

SUPPRESSION_MODES = frozenset({
    "NO_OUTREACH",
    "NO_SCAN",
    "COOLDOWN",
    "MONITOR_CHANGES_ONLY",
})

RETENTION_ARCHIVE_STATES = frozenset({"archive", "soft_delete", "purge_planned"})

RECHECK_LEVELS = frozenset({"L0", "L1", "L2", "L3", "L4"})

# Recheck levels that involve any active scanning/change-detection (i.e. not history-only).
_SCANNING_RECHECK_LEVELS = frozenset({"L1", "L2", "L3", "L4"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _valid_iso(value: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def _to_dt(value: str) -> datetime:
    dt = datetime.fromisoformat(value)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _iso_after(later: str, earlier: str) -> bool:
    """True when `later` is strictly after `earlier` (naive values treated as UTC)."""
    try:
        return _to_dt(later) > _to_dt(earlier)
    except (ValueError, TypeError):
        return True  # already ISO-validated; skip strict ordering if incomparable


def _dedup(seq: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


@dataclass
class SuppressionPolicy(SchemaMixin):
    """Suppression decision for a company/domains (planning-only; no runtime enforcement).

    Safe default is disabled with no external action. This schema never removes itself and
    never enforces anything at runtime — it records a decision that a future, separately
    approved runtime would honor.
    """

    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    enabled: bool = False
    mode: str = "NO_OUTREACH"
    reason: str = ""
    reference: str = ""
    created_at: str = field(default_factory=_now_iso)
    expires_at: str = ""
    manual_override_required: bool = True
    applies_to_company: str = ""
    applies_to_domains: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.mode not in SUPPRESSION_MODES:
            raise ValueError(f"Unknown suppression mode: {self.mode!r}")
        # Normalize + de-duplicate domains via the canonical hostname helper (fail closed).
        self.applies_to_domains = _dedup(
            [normalize_hostname(d) for d in self.applies_to_domains]
        )
        if self.created_at and not _valid_iso(self.created_at):
            raise ValueError(f"created_at must be valid ISO: {self.created_at!r}")
        if self.expires_at and not _valid_iso(self.expires_at):
            raise ValueError(f"expires_at must be valid ISO: {self.expires_at!r}")
        if self.enabled:
            # Enabled suppression always requires manual override and a reason.
            self.manual_override_required = True
            if not self.reason.strip():
                raise ValueError("enabled suppression requires a non-empty reason")
            if self.mode == "COOLDOWN":
                if not self.expires_at.strip():
                    raise ValueError(
                        "COOLDOWN suppression requires an expiry/review date"
                    )
                if not _iso_after(self.expires_at, self.created_at):
                    raise ValueError(
                        "COOLDOWN expiry must be later than created_at"
                    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SuppressionPolicy":
        return super().from_dict(data)


@dataclass
class ProspectRetentionPolicy(SchemaMixin):
    """Prospect data-retention policy (planning-only; deletion is never executed here).

    Composes the existing `CleanupPolicy` for the safe-by-default cleanup contract and adds
    prospect-specific retention windows. Suppression and identity metadata are preserved
    even when evidence is purged; paid/client work is not governed by these defaults.
    """

    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    cleanup_policy: CleanupPolicy = field(default_factory=CleanupPolicy)
    retention_days_failed_eligibility: int = 30
    retention_days_weak_rejected: int = 30
    retention_days_qualified: int = 180
    retention_days_contacted: int = 365
    retention_days_positive_reply: int = 730
    evidence_retention_days: int = 90
    preserve_identity_metadata: bool = True
    preserve_suppression_metadata: bool = True
    archive_state: str = "archive"
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for name in (
            "retention_days_failed_eligibility",
            "retention_days_weak_rejected",
            "retention_days_qualified",
            "retention_days_contacted",
            "retention_days_positive_reply",
            "evidence_retention_days",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.archive_state not in RETENTION_ARCHIVE_STATES:
            raise ValueError(f"Unknown archive_state: {self.archive_state!r}")
        if self.cleanup_policy.retention_days < 0:
            raise ValueError("cleanup_policy.retention_days cannot be negative")
        # Fail-closed safety invariants that prospect retention can never weaken:
        # the composed cleanup stays inert (no runtime); dry-run stays required; git-tracked
        # files and client outputs stay preserved; suppression + identity metadata survive
        # evidence deletion. Evidence retention (`evidence_retention_days`) is a separate,
        # typically shorter window than the generic `CleanupPolicy.retention_days`.
        self.cleanup_policy.enabled = False
        self.cleanup_policy.dry_run_required = True
        self.cleanup_policy.preserve_git_tracked_files = True
        self.cleanup_policy.preserve_client_outputs = True
        self.preserve_suppression_metadata = True
        self.preserve_identity_metadata = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "cleanup_policy": self.cleanup_policy.to_dict(),
            "retention_days_failed_eligibility": self.retention_days_failed_eligibility,
            "retention_days_weak_rejected": self.retention_days_weak_rejected,
            "retention_days_qualified": self.retention_days_qualified,
            "retention_days_contacted": self.retention_days_contacted,
            "retention_days_positive_reply": self.retention_days_positive_reply,
            "evidence_retention_days": self.evidence_retention_days,
            "preserve_identity_metadata": self.preserve_identity_metadata,
            "preserve_suppression_metadata": self.preserve_suppression_metadata,
            "archive_state": self.archive_state,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProspectRetentionPolicy":
        known = {
            "schema_version", "retention_days_failed_eligibility",
            "retention_days_weak_rejected", "retention_days_qualified",
            "retention_days_contacted", "retention_days_positive_reply",
            "evidence_retention_days", "preserve_identity_metadata",
            "preserve_suppression_metadata", "archive_state", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        cleanup = data.get("cleanup_policy")
        kwargs["cleanup_policy"] = (
            CleanupPolicy.from_dict(cleanup) if isinstance(cleanup, dict)
            else CleanupPolicy()
        )
        return cls(**kwargs)


@dataclass
class RecheckPolicy(SchemaMixin):
    """Planned recheck cadence (planning-only; no scheduler, network, or browser runtime).

    Levels: L0 history check, L1 cheap change detection, L2 finding recheck, L3 targeted
    re-audit, L4 full re-audit. Pre-send revalidation defaults on; full re-audit defaults off.
    """

    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    level: str = "L0"
    enabled: bool = False
    cooldown_days: int = 0
    evidence_max_age_days: int = 0
    pre_send_revalidation_required: bool = True
    next_recheck_at: str = ""
    change_detection_required: bool = False
    full_reaudit_allowed: bool = False
    reason: str = ""
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.level not in RECHECK_LEVELS:
            raise ValueError(f"Unknown recheck level: {self.level!r}")
        for name in ("cooldown_days", "evidence_max_age_days"):
            if getattr(self, name) < 0:
                raise ValueError(f"{name} cannot be negative")
        if self.next_recheck_at and not _valid_iso(self.next_recheck_at):
            raise ValueError(f"next_recheck_at must be valid ISO: {self.next_recheck_at!r}")
        # Pre-send revalidation can never be disabled through this contract.
        self.pre_send_revalidation_required = True
        # A full re-audit is only meaningful at the highest level.
        if self.full_reaudit_allowed and self.level != "L4":
            raise ValueError("full_reaudit_allowed is only valid for level L4")
        # L0 is a history check only: it cannot require active change detection.
        if self.level == "L0" and self.change_detection_required:
            raise ValueError("L0 (history check) cannot require active change detection")

    @property
    def is_active_scan(self) -> bool:
        """True when this recheck implies active scanning/change detection."""
        return self.enabled and (
            self.change_detection_required or self.level in _SCANNING_RECHECK_LEVELS
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RecheckPolicy":
        return super().from_dict(data)


@dataclass
class ProspectGovernancePlan(SchemaMixin):
    """Small planning-only aggregate tying suppression, recheck, and retention together.

    Its only cross-policy invariant: a `NO_SCAN` suppression cannot coexist with an active
    automatic recheck (scanning/change detection). A history-only (`L0`, no change
    detection) recheck is still allowed under `NO_SCAN`.
    """

    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    suppression: SuppressionPolicy = field(default_factory=SuppressionPolicy)
    recheck: RecheckPolicy = field(default_factory=RecheckPolicy)
    retention: ProspectRetentionPolicy = field(default_factory=ProspectRetentionPolicy)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if (
            self.suppression.enabled
            and self.suppression.mode == "NO_SCAN"
            and self.recheck.is_active_scan
        ):
            raise ValueError(
                "NO_SCAN suppression cannot coexist with an active automatic recheck"
            )
        # MONITOR_CHANGES_ONLY permits only history / cheap change detection (L0/L1).
        if (
            self.suppression.enabled
            and self.suppression.mode == "MONITOR_CHANGES_ONLY"
            and self.recheck.enabled
            and self.recheck.level in {"L2", "L3", "L4"}
        ):
            raise ValueError(
                "MONITOR_CHANGES_ONLY allows only L0/L1 recheck, not L2–L4"
            )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "suppression": self.suppression.to_dict(),
            "recheck": self.recheck.to_dict(),
            "retention": self.retention.to_dict(),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProspectGovernancePlan":
        known = {"schema_version", "notes"}
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        supp = data.get("suppression")
        kwargs["suppression"] = (
            SuppressionPolicy.from_dict(supp) if isinstance(supp, dict)
            else SuppressionPolicy()
        )
        rech = data.get("recheck")
        kwargs["recheck"] = (
            RecheckPolicy.from_dict(rech) if isinstance(rech, dict) else RecheckPolicy()
        )
        ret = data.get("retention")
        kwargs["retention"] = (
            ProspectRetentionPolicy.from_dict(ret) if isinstance(ret, dict)
            else ProspectRetentionPolicy()
        )
        return cls(**kwargs)

"""Prospect Radar storage & controlled-disclosure contracts (Phase 8.2 — child slice).

Planning / contracts only. No evidence capture, report sending, email, contact-form
submission, screenshotting, revalidation, or client-delivery runtime. A `DisclosureManifest`
only *references* findings/evidence and *computes* readiness — it never sends anything and
never approves itself.

REUSE NOTES (verified against the repository):
- Serialization: `core.schemas.base.SchemaMixin` (unknown keys ignored → additive-safe).
- Storage classification (handling) is kept **separate** from disclosure level (permission).
- Disclosure items reference existing finding/evidence artifacts by id — no raw finding
  payloads, screenshots, logs, or secrets are embedded here.

Fail-closed model: default disclosure level is INTERNAL_ONLY; RAW_INTERNAL is never
outreach-safe; CLIENT_SAFE requires sanitized content without PII/secrets; OUTREACH_ELIGIBLE
requires independent verification + CLIENT_SAFE storage; responsible-disclosure material
stays INTERNAL_ONLY. Readiness is computed from references, never a freely trusted boolean.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin
from core.schemas.prospect_interaction import PROSPECT_CONTRACT_SCHEMA_VERSION


class StorageClass(str, Enum):
    """How content is handled (NOT where it lives, and NOT a disclosure permission)."""

    RAW_INTERNAL = "RAW_INTERNAL"
    SANITIZED_INTERNAL = "SANITIZED_INTERNAL"
    VERIFIED_INTERNAL = "VERIFIED_INTERNAL"
    CLIENT_SAFE = "CLIENT_SAFE"


class DisclosureLevel(str, Enum):
    """What a disclosure item is permitted to be used for (NOT a storage class)."""

    INTERNAL_ONLY = "INTERNAL_ONLY"
    OUTREACH_ELIGIBLE = "OUTREACH_ELIGIBLE"
    QUALIFICATION_ELIGIBLE = "QUALIFICATION_ELIGIBLE"
    PAID_DELIVERY_ONLY = "PAID_DELIVERY_ONLY"


class DisclosureStage(str, Enum):
    """The stage a manifest is being assembled for."""

    INTERNAL = "INTERNAL"
    OUTREACH = "OUTREACH"
    QUALIFICATION = "QUALIFICATION"
    PAID_DELIVERY = "PAID_DELIVERY"


_VALID_STORAGE = frozenset(s.value for s in StorageClass)
_VALID_LEVELS = frozenset(x.value for x in DisclosureLevel)
_VALID_STAGES = frozenset(s.value for s in DisclosureStage)
DISCLOSURE_ROLES = frozenset({"primary", "support"})
REPRODUCTION_DETAIL_LEVELS = frozenset({"none", "minimal", "partial", "full"})

# Canonical hard ceilings for disclosure item counts (safety limits, not configuration).
_CANONICAL_CEILINGS = {
    "outreach_max_primary": 1,
    "outreach_max_support": 1,
    "outreach_max_total": 2,
    "qualification_max_total": 3,
}


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


def _parse_iso(value: str, field_name: str) -> datetime:
    if not _valid_iso(value):
        raise ValueError(f"{field_name} must be valid ISO: {value!r}")
    return datetime.fromisoformat(value)


def _dedup_refs(seq: List[str]) -> List[str]:
    if not isinstance(seq, list):
        raise ValueError("evidence_refs must be a list of strings")
    seen: set[str] = set()
    out: List[str] = []
    for item in seq:
        if not isinstance(item, str) or not item.strip():
            raise ValueError("evidence_refs entries must be non-empty strings")
        normalized = item.strip()
        if normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return out


def _require_dict(entry: Any, field_name: str) -> Dict[str, Any]:
    if not isinstance(entry, dict):
        raise ValueError(
            f"{field_name} must be an object, got {type(entry).__name__}"
        )
    return entry


@dataclass
class DisclosureItem(SchemaMixin):
    """A reference to one finding/evidence item with its disclosure constraints.

    References only — no raw finding payload, screenshots, logs, or secrets are embedded.
    """

    finding_ref: str = ""
    disclosure_level: str = "INTERNAL_ONLY"
    role: str = "primary"
    business_impact_summary: str = ""
    evidence_refs: List[str] = field(default_factory=list)
    storage_class: str = "RAW_INTERNAL"
    sanitized: bool = False
    independently_verified: bool = False
    contains_pii: bool = False
    contains_secrets: bool = False
    root_cause_included: bool = False
    full_logs_included: bool = False
    reproduction_detail_level: str = "none"
    responsible_disclosure_flag: bool = False
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not isinstance(self.finding_ref, str):
            raise ValueError("DisclosureItem.finding_ref must be a string")
        self.finding_ref = self.finding_ref.strip()
        if not self.finding_ref.strip():
            raise ValueError("DisclosureItem.finding_ref must be non-empty")
        if self.disclosure_level not in _VALID_LEVELS:
            raise ValueError(f"Unknown disclosure_level: {self.disclosure_level!r}")
        if self.role not in DISCLOSURE_ROLES:
            raise ValueError(f"Unknown disclosure role: {self.role!r}")
        if self.storage_class not in _VALID_STORAGE:
            raise ValueError(f"Unknown storage_class: {self.storage_class!r}")
        if self.reproduction_detail_level not in REPRODUCTION_DETAIL_LEVELS:
            raise ValueError(
                f"Unknown reproduction_detail_level: {self.reproduction_detail_level!r}"
            )
        self.evidence_refs = _dedup_refs(self.evidence_refs)
        # CLIENT_SAFE storage requires sanitized content without PII or secrets.
        if self.storage_class == "CLIENT_SAFE" and (
            not self.sanitized or self.contains_pii or self.contains_secrets
        ):
            raise ValueError(
                "CLIENT_SAFE storage requires sanitized content with no PII/secrets"
            )
        # Responsible-disclosure material stays INTERNAL_ONLY (manual review required).
        if self.responsible_disclosure_flag and self.disclosure_level != "INTERNAL_ONLY":
            raise ValueError(
                "responsible_disclosure_flag material must be INTERNAL_ONLY"
            )
        # OUTREACH_ELIGIBLE requires independent verification, CLIENT_SAFE storage, a
        # business-impact summary, at least one evidence reference, and a minimal teaser
        # (no root cause, no full logs, at most minimal reproduction).
        if self.disclosure_level == "OUTREACH_ELIGIBLE":
            if not self.independently_verified:
                raise ValueError("OUTREACH_ELIGIBLE requires independently_verified")
            if self.storage_class != "CLIENT_SAFE":
                raise ValueError("OUTREACH_ELIGIBLE requires CLIENT_SAFE storage")
            if self.contains_pii or self.contains_secrets:
                raise ValueError("OUTREACH_ELIGIBLE cannot contain PII or secrets")
            if (
                not isinstance(self.business_impact_summary, str)
                or not self.business_impact_summary.strip()
            ):
                raise ValueError(
                    "OUTREACH_ELIGIBLE requires a non-empty business_impact_summary"
                )
            if not any(r.strip() for r in self.evidence_refs):
                raise ValueError(
                    "OUTREACH_ELIGIBLE requires at least one evidence reference"
                )
            if self.responsible_disclosure_flag:
                raise ValueError(
                    "OUTREACH_ELIGIBLE cannot carry a responsible_disclosure_flag"
                )
            if self.root_cause_included or self.full_logs_included:
                raise ValueError(
                    "OUTREACH_ELIGIBLE cannot include root cause or full logs"
                )
            if self.reproduction_detail_level not in ("none", "minimal"):
                raise ValueError(
                    "OUTREACH_ELIGIBLE reproduction detail must be none/minimal"
                )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DisclosureItem":
        return super().from_dict(data)


@dataclass
class FindingDisclosurePolicy(SchemaMixin):
    """Controlled disclosure limits per stage (fail-closed; default INTERNAL_ONLY).

    The `allow_*` safety toggles can never be enabled through this contract.
    """

    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    default_level: str = "INTERNAL_ONLY"
    outreach_max_primary: int = 1
    outreach_max_support: int = 1
    outreach_max_total: int = 2
    qualification_max_total: int = 3
    allow_raw_logs_in_outreach: bool = False
    allow_root_cause_in_outreach: bool = False
    allow_pii: bool = False
    allow_secrets: bool = False
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.default_level not in _VALID_LEVELS:
            raise ValueError(f"Unknown default_level: {self.default_level!r}")
        for name in (
            "outreach_max_primary", "outreach_max_support", "outreach_max_total",
            "qualification_max_total",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if value < 0:
                raise ValueError(f"{name} cannot be negative")
        # Canonical hard ceilings are safety limits, not user-expandable configuration.
        # A caller may configure stricter (lower) limits, but may never raise above these.
        for name, ceiling in _CANONICAL_CEILINGS.items():
            if getattr(self, name) > ceiling:
                raise ValueError(
                    f"{name}={getattr(self, name)} exceeds the canonical ceiling {ceiling}"
                )
        # These safety toggles are fail-closed and cannot be enabled through this contract.
        self.allow_raw_logs_in_outreach = False
        self.allow_root_cause_in_outreach = False
        self.allow_pii = False
        self.allow_secrets = False

    def blockers_for(self, stage: str, items: List["DisclosureItem"]) -> List[str]:
        """Return a list of disclosure-policy blockers for the given stage + items."""
        blockers: List[str] = []
        if not isinstance(items, list) or not all(
            isinstance(item, DisclosureItem) for item in items
        ):
            return ["disclosure items are malformed"]
        outreach_max_primary = _effective_limit(
            self.outreach_max_primary, "outreach_max_primary"
        )
        outreach_max_support = _effective_limit(
            self.outreach_max_support, "outreach_max_support"
        )
        outreach_max_total = _effective_limit(
            self.outreach_max_total, "outreach_max_total"
        )
        qualification_max_total = _effective_limit(
            self.qualification_max_total, "qualification_max_total"
        )
        primary = sum(1 for i in items if i.role == "primary")
        support = sum(1 for i in items if i.role == "support")
        if stage == "OUTREACH":
            if not items:
                blockers.append("outreach requires at least one finding")
            if primary != 1:
                blockers.append("outreach requires exactly one primary finding")
            if primary > outreach_max_primary:
                blockers.append("too many primary findings for outreach")
            if support > outreach_max_support:
                blockers.append("too many supporting findings for outreach")
            if len(items) > outreach_max_total:
                blockers.append("too many total findings for outreach")
            for item in items:
                if (
                    not isinstance(item.finding_ref, str)
                    or not item.finding_ref.strip()
                ):
                    blockers.append("outreach item has an empty finding reference")
                if item.disclosure_level != "OUTREACH_ELIGIBLE":
                    blockers.append(f"item {item.finding_ref!r} is not OUTREACH_ELIGIBLE")
                if item.storage_class != "CLIENT_SAFE":
                    blockers.append(f"item {item.finding_ref!r} is not CLIENT_SAFE")
                if not item.sanitized:
                    blockers.append(f"item {item.finding_ref!r} is not sanitized")
                if not item.independently_verified:
                    blockers.append(
                        f"item {item.finding_ref!r} is not independently verified"
                    )
                if (
                    not isinstance(item.business_impact_summary, str)
                    or not item.business_impact_summary.strip()
                ):
                    blockers.append(
                        f"item {item.finding_ref!r} has no business impact summary"
                    )
                if not isinstance(item.evidence_refs, list) or not item.evidence_refs or any(
                    not isinstance(ref, str) or not ref.strip()
                    for ref in item.evidence_refs
                ):
                    blockers.append(
                        f"item {item.finding_ref!r} has no valid evidence reference"
                    )
                if item.contains_pii or item.contains_secrets:
                    blockers.append(f"item {item.finding_ref!r} contains PII/secrets")
                if item.full_logs_included or item.root_cause_included:
                    blockers.append(f"item {item.finding_ref!r} includes logs/root cause")
                if item.responsible_disclosure_flag:
                    blockers.append(
                        f"item {item.finding_ref!r} is responsible-disclosure blocked"
                    )
                if item.reproduction_detail_level not in ("none", "minimal"):
                    blockers.append(
                        f"item {item.finding_ref!r} has excessive reproduction detail"
                    )
        elif stage == "QUALIFICATION":
            if not items:
                blockers.append("qualification requires at least one finding")
            if len(items) > qualification_max_total:
                blockers.append("too many findings for qualification")
            for item in items:
                if item.disclosure_level not in (
                    "QUALIFICATION_ELIGIBLE", "OUTREACH_ELIGIBLE"
                ):
                    blockers.append(
                        f"item {item.finding_ref!r} not qualification-eligible"
                    )
                if item.contains_secrets:
                    blockers.append(f"item {item.finding_ref!r} contains secrets")
                if item.contains_pii and not item.sanitized:
                    blockers.append(
                        f"item {item.finding_ref!r} contains unsanitized PII"
                    )
        elif stage == "PAID_DELIVERY":
            for item in items:
                if item.contains_secrets:
                    blockers.append(f"item {item.finding_ref!r} contains secrets")
                if item.contains_pii and not item.sanitized:
                    blockers.append(
                        f"item {item.finding_ref!r} contains unsanitized PII"
                    )
        # INTERNAL stage has no external blockers.
        return blockers

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FindingDisclosurePolicy":
        return super().from_dict(data)


@dataclass
class DisclosureManifest(SchemaMixin):
    """Aggregates selected disclosure items and proves eligibility (never sends anything).

    Readiness is computed from references and item constraints; it is not a trusted stored
    boolean. The manifest performs no send/submit/lookup/screenshot/revalidation/approval.
    """

    manifest_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    prospect_ref: str = ""
    stage: str = "INTERNAL"
    items: List[DisclosureItem] = field(default_factory=list)
    policy: FindingDisclosurePolicy = field(default_factory=FindingDisclosurePolicy)
    contact_ref: str = ""
    suppression_check_ref: str = ""
    pre_send_revalidation_ref: str = ""
    approval_ref: str = ""
    generated_at: str = field(default_factory=_now_iso)
    expires_at: str = ""
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.stage not in _VALID_STAGES:
            raise ValueError(f"Unknown disclosure stage: {self.stage!r}")
        if not isinstance(self.items, list) or not all(
            isinstance(item, DisclosureItem) for item in self.items
        ):
            raise ValueError("items must be a list of DisclosureItem objects")
        if not isinstance(self.policy, FindingDisclosurePolicy):
            raise ValueError("policy must be a FindingDisclosurePolicy object")
        finding_refs = [item.finding_ref for item in self.items]
        if len(finding_refs) != len(set(finding_refs)):
            raise ValueError("duplicate finding_ref entries are not allowed")
        generated = _parse_iso(self.generated_at, "generated_at")
        if self.expires_at:
            expires = _parse_iso(self.expires_at, "expires_at")
            try:
                expires_after_generated = expires > generated
            except TypeError as exc:
                raise ValueError(
                    "generated_at and expires_at must use compatible ISO timezones"
                ) from exc
            if not expires_after_generated:
                raise ValueError("expires_at must be later than generated_at")

    @property
    def blockers(self) -> List[str]:
        """Computed eligibility blockers for the manifest's stage (never sends anything)."""
        if not isinstance(self.items, list) or not all(
            isinstance(item, DisclosureItem) for item in self.items
        ):
            return ["disclosure items are malformed"]
        if not isinstance(self.policy, FindingDisclosurePolicy):
            return ["disclosure policy is malformed"]
        finding_refs = [item.finding_ref for item in self.items]
        duplicate_refs = {
            ref for ref in finding_refs if finding_refs.count(ref) > 1
        }
        blockers = list(self.policy.blockers_for(self.stage, self.items))
        if duplicate_refs:
            blockers.append("duplicate finding_ref entries are not allowed")
        if self.stage == "OUTREACH":
            if not self.contact_ref.strip():
                blockers.append("missing verified/public contact reference")
            if not self.suppression_check_ref.strip():
                blockers.append("missing suppression-check reference")
            if not self.pre_send_revalidation_ref.strip():
                blockers.append("missing pre-send revalidation reference")
            if not self.approval_ref.strip():
                blockers.append("missing human approval reference")
        return blockers

    @property
    def outreach_ready(self) -> bool:
        return self.stage == "OUTREACH" and not self.blockers

    @property
    def is_ready(self) -> bool:
        return not self.blockers

    def to_dict(self) -> Dict[str, Any]:
        return {
            "manifest_id": self.manifest_id,
            "schema_version": self.schema_version,
            "prospect_ref": self.prospect_ref,
            "stage": self.stage,
            "items": [i.to_dict() for i in self.items],
            "policy": self.policy.to_dict(),
            "contact_ref": self.contact_ref,
            "suppression_check_ref": self.suppression_check_ref,
            "pre_send_revalidation_ref": self.pre_send_revalidation_ref,
            "approval_ref": self.approval_ref,
            "generated_at": self.generated_at,
            "expires_at": self.expires_at,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DisclosureManifest":
        known = {
            "manifest_id", "schema_version", "prospect_ref", "stage", "contact_ref",
            "suppression_check_ref", "pre_send_revalidation_ref", "approval_ref",
            "generated_at", "expires_at", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        items = data.get("items") or []
        if not isinstance(items, list):
            raise ValueError("items must be a list of objects")
        kwargs["items"] = [
            DisclosureItem.from_dict(_require_dict(item, "items entry"))
            for item in items
        ]
        if "policy" in data:
            kwargs["policy"] = FindingDisclosurePolicy.from_dict(
                _require_dict(data["policy"], "policy")
            )
        else:
            kwargs["policy"] = FindingDisclosurePolicy()
        return cls(**kwargs)


def _effective_limit(value: Any, field_name: str) -> int:
    """Apply the immutable safety ceiling even if a live policy object was mutated."""
    ceiling = _CANONICAL_CEILINGS[field_name]
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return min(value, ceiling)

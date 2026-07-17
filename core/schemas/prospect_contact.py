"""Prospect Radar public business contact contracts (Phase 8.2 — child slice).

Planning / contracts only. No contact lookup, provider call, scraping, enrichment,
guessing, sending, or database runtime. These dataclasses only describe *public business*
contact information already observed elsewhere; nothing here fetches or sends anything.

REUSE NOTES (verified against the repository):
- Serialization: `core.schemas.base.SchemaMixin` (unknown keys ignored → additive-safe).
- Provenance reuses `core.schemas.source_reference.SourceReference` and the
  `core.schemas.finding.Confidence` vocabulary.
- Canonical domain handling reuses `normalize_hostname` from `prospect_identity.py`.

Safety: no secrets/credentials/cookies/tokens are stored; inferred candidates can never
become VERIFIED or an outreach candidate merely because they have a plausible format;
named-person business contacts always require manual review; SUPPRESSED / DO_NOT_CONTACT
are never outreach candidates. There is no private/stolen/breached source category.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin
from core.schemas.finding import Confidence
from core.schemas.source_reference import SourceReference
from core.schemas.prospect_identity import normalize_hostname
from core.schemas.prospect_interaction import PROSPECT_CONTRACT_SCHEMA_VERSION

CONFIDENCE_LEVELS = frozenset(c.value for c in Confidence)

# Public source categories only — no private/stolen/breached source exists.
CONTACT_SOURCE_CATEGORIES = frozenset({
    "public_website",
    "public_directory",
    "public_registry",
    "manual_verified",
    "provider_public",
    "inferred_candidate",
})

# Source categories that count as a real public/manual observation (not inferred).
_NON_INFERRED_SOURCES = frozenset({
    "public_website",
    "public_directory",
    "public_registry",
    "manual_verified",
    "provider_public",
})

EXTRACTION_METHODS = frozenset({
    "published_link",
    "structured_data",
    "page_text",
    "manual_entry",
    "inferred_pattern",
    "unknown",
})

TERMS_REVIEW_STATUSES = frozenset({
    "not_reviewed",
    "in_review",
    "reviewed_ok",
    "reviewed_blocked",
})

CONTACT_CHANNELS = frozenset({
    "email",
    "phone",
    "contact_form",
    "public_social",
    "business_address",
})

DATA_SUBJECT_CATEGORIES = frozenset({
    "role_based",
    "named_person",
    "organization",
    "unknown",
})

# Terms that must never appear in a stored contact value (no secrets/credentials).
_FORBIDDEN_VALUE_TERMS = (
    "password", "passwd", "secret", "token", "cookie", "credential",
    "authorization", "bearer", "jwt", "api_key", "apikey", "access_token",
)


class ContactStatus(str, Enum):
    """Public business contact lifecycle (distinct from ProspectLifecycle)."""

    UNVERIFIED = "UNVERIFIED"
    PUBLIC_OBSERVED = "PUBLIC_OBSERVED"
    MANUAL_REVIEW_REQUIRED = "MANUAL_REVIEW_REQUIRED"
    VERIFIED = "VERIFIED"
    STALE = "STALE"
    INVALID = "INVALID"
    SUPPRESSED = "SUPPRESSED"
    DO_NOT_CONTACT = "DO_NOT_CONTACT"


_VALID_STATUSES = frozenset(s.value for s in ContactStatus)

# Statuses that can never be an outreach candidate.
_NON_OUTREACH_STATUSES = frozenset({
    "UNVERIFIED", "PUBLIC_OBSERVED", "MANUAL_REVIEW_REQUIRED", "STALE",
    "INVALID", "SUPPRESSED", "DO_NOT_CONTACT",
})

# Strictness ordering for deterministic merge (higher wins — more restrictive).
_STATUS_STRICTNESS = {
    "VERIFIED": 0,
    "PUBLIC_OBSERVED": 1,
    "UNVERIFIED": 2,
    "MANUAL_REVIEW_REQUIRED": 3,
    "STALE": 4,
    "INVALID": 5,
    "SUPPRESSED": 6,
    "DO_NOT_CONTACT": 7,
}


def _valid_iso(value: str) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        datetime.fromisoformat(value)
        return True
    except (ValueError, TypeError):
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reject_secret_value(value: str) -> None:
    lowered = value.lower()
    for term in _FORBIDDEN_VALUE_TERMS:
        if term in lowered:
            raise ValueError(f"contact value contains a forbidden secret term: {term!r}")


def _normalize_email(value: str) -> str:
    v = value.strip()
    if v.count("@") != 1:
        raise ValueError(f"invalid email (need exactly one '@'): {value!r}")
    local, domain = v.split("@")
    if not local or any(ch.isspace() for ch in local):
        raise ValueError(f"invalid email local part: {value!r}")
    return f"{local.lower()}@{normalize_hostname(domain)}"


def _normalize_phone(value: str) -> str:
    v = value.strip()
    has_plus = v.startswith("+")
    digits = re.sub(r"\D", "", v)
    if not digits:
        raise ValueError(f"phone has no digits: {value!r}")
    # Conservative: preserve an explicit leading '+', never invent a country code.
    return ("+" if has_plus else "") + digits


def _normalize_contact_form(value: str) -> str:
    v = value.strip()
    if not (v.startswith("http://") or v.startswith("https://") or v.startswith("/")):
        raise ValueError(
            f"contact_form must be a public URL or path reference: {value!r}"
        )
    return v


def _normalize_value(channel: str, value: str) -> str:
    if channel == "email":
        return _normalize_email(value)
    if channel == "phone":
        return _normalize_phone(value)
    if channel == "contact_form":
        return _normalize_contact_form(value)
    # public_social / business_address: collapse whitespace, preserve content.
    return " ".join(value.split())


@dataclass
class ContactProvenance(SchemaMixin):
    """Where/how a public business contact was observed (no runtime lookup)."""

    source: SourceReference = field(default_factory=SourceReference)
    source_category: str = "public_website"
    observed_at: str = ""
    evidence_ref: str = ""
    extraction_method: str = "unknown"
    confidence: str = "low"
    publicly_published_for_contact: bool = False
    terms_review_status: str = "not_reviewed"
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.source_category not in CONTACT_SOURCE_CATEGORIES:
            raise ValueError(f"Unknown contact source_category: {self.source_category!r}")
        if self.extraction_method not in EXTRACTION_METHODS:
            raise ValueError(f"Unknown extraction_method: {self.extraction_method!r}")
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"Unknown confidence: {self.confidence!r}")
        if self.terms_review_status not in TERMS_REVIEW_STATUSES:
            raise ValueError(f"Unknown terms_review_status: {self.terms_review_status!r}")
        if self.observed_at and not _valid_iso(self.observed_at):
            raise ValueError(f"observed_at must be valid ISO: {self.observed_at!r}")

    @property
    def is_inferred(self) -> bool:
        return (
            self.source_category == "inferred_candidate"
            or self.extraction_method == "inferred_pattern"
        )

    @property
    def is_public_verified_source(self) -> bool:
        return self.source_category in _NON_INFERRED_SOURCES and not self.is_inferred

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source": self.source.to_dict(),
            "source_category": self.source_category,
            "observed_at": self.observed_at,
            "evidence_ref": self.evidence_ref,
            "extraction_method": self.extraction_method,
            "confidence": self.confidence,
            "publicly_published_for_contact": self.publicly_published_for_contact,
            "terms_review_status": self.terms_review_status,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactProvenance":
        known = {
            "source_category", "observed_at", "evidence_ref", "extraction_method",
            "confidence", "publicly_published_for_contact", "terms_review_status",
            "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        source = data.get("source")
        kwargs["source"] = (
            SourceReference.from_dict(source) if isinstance(source, dict)
            else SourceReference()
        )
        return cls(**kwargs)


@dataclass
class ContactRecord(SchemaMixin):
    """One public business contact (planning-only; never sendable by this schema)."""

    contact_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    company_ref: str = ""
    domain_ref: str = ""
    channel: str = "email"
    value: str = ""
    normalized_value: str = ""
    display_name: str = ""
    role_title: str = ""
    data_subject_category: str = "unknown"
    status: str = "UNVERIFIED"
    provenance: List[ContactProvenance] = field(default_factory=list)
    first_observed_at: str = ""
    last_verified_at: str = ""
    suppression_check_ref: str = ""
    manual_review_required: bool = False
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.channel not in CONTACT_CHANNELS:
            raise ValueError(f"Unknown contact channel: {self.channel!r}")
        if self.data_subject_category not in DATA_SUBJECT_CATEGORIES:
            raise ValueError(
                f"Unknown data_subject_category: {self.data_subject_category!r}"
            )
        if self.status not in _VALID_STATUSES:
            raise ValueError(f"Unknown contact status: {self.status!r}")
        if not self.value.strip():
            raise ValueError("contact value must be non-empty")
        _reject_secret_value(self.value)
        # Deterministic normalization (recomputed; does not claim deliverability).
        self.normalized_value = _normalize_value(self.channel, self.value)
        for ts_name in ("first_observed_at", "last_verified_at"):
            ts = getattr(self, ts_name)
            if ts and not _valid_iso(ts):
                raise ValueError(f"{ts_name} must be valid ISO: {ts!r}")
        # Named-person business contacts always require manual review.
        if self.data_subject_category == "named_person":
            self.manual_review_required = True
        # VERIFIED requires a real public/manual verified provenance + a verification time.
        if self.status == "VERIFIED":
            if not any(p.is_public_verified_source for p in self.provenance):
                raise ValueError(
                    "VERIFIED requires at least one public/manual verified provenance"
                )
            if not self.last_verified_at.strip():
                raise ValueError("VERIFIED requires a non-empty last_verified_at")

    @property
    def is_inferred_only(self) -> bool:
        """True when every provenance record is inferred (no public/manual verification)."""
        return bool(self.provenance) and all(p.is_inferred for p in self.provenance)

    @property
    def is_outreach_candidate(self) -> bool:
        """Fail-closed: only VERIFIED contacts are outreach candidates (computed, not stored)."""
        return self.status == "VERIFIED"

    def dedup_key(self) -> tuple[str, str]:
        return (self.channel, self.normalized_value)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "contact_id": self.contact_id,
            "schema_version": self.schema_version,
            "company_ref": self.company_ref,
            "domain_ref": self.domain_ref,
            "channel": self.channel,
            "value": self.value,
            "normalized_value": self.normalized_value,
            "display_name": self.display_name,
            "role_title": self.role_title,
            "data_subject_category": self.data_subject_category,
            "status": self.status,
            "provenance": [p.to_dict() for p in self.provenance],
            "first_observed_at": self.first_observed_at,
            "last_verified_at": self.last_verified_at,
            "suppression_check_ref": self.suppression_check_ref,
            "manual_review_required": self.manual_review_required,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactRecord":
        known = {
            "contact_id", "schema_version", "company_ref", "domain_ref", "channel",
            "value", "display_name", "role_title", "data_subject_category", "status",
            "first_observed_at", "last_verified_at", "suppression_check_ref",
            "manual_review_required", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        prov = data.get("provenance") or []
        kwargs["provenance"] = [
            ContactProvenance.from_dict(p) for p in prov if isinstance(p, dict)
        ]
        return cls(**kwargs)


@dataclass
class ContactCollection(SchemaMixin):
    """Deterministically de-duplicated set of contacts for one company (planning-only).

    Merges duplicates by (channel, normalized_value): keeps the stricter status, unions
    provenance, and ORs manual_review_required. It makes no contact-selection decision.
    """

    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    company_ref: str = ""
    contacts: List[ContactRecord] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        merged: Dict[tuple[str, str], ContactRecord] = {}
        for contact in self.contacts:
            key = contact.dedup_key()
            if key not in merged:
                merged[key] = contact
            else:
                merged[key] = _merge_contacts(merged[key], contact)
        self.contacts = list(merged.values())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "company_ref": self.company_ref,
            "contacts": [c.to_dict() for c in self.contacts],
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactCollection":
        known = {"schema_version", "company_ref", "notes"}
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        contacts = data.get("contacts") or []
        kwargs["contacts"] = [
            ContactRecord.from_dict(c) for c in contacts if isinstance(c, dict)
        ]
        return cls(**kwargs)


def _merge_contacts(a: ContactRecord, b: ContactRecord) -> ContactRecord:
    """Merge two same-key contacts: stricter status wins; provenance unioned."""
    keep = a if _STATUS_STRICTNESS[a.status] >= _STATUS_STRICTNESS[b.status] else b
    other = b if keep is a else a
    merged_prov = list(keep.provenance)
    for prov in other.provenance:
        if prov not in merged_prov:
            merged_prov.append(prov)
    keep.provenance = merged_prov
    keep.manual_review_required = (
        a.manual_review_required or b.manual_review_required
    )
    return keep

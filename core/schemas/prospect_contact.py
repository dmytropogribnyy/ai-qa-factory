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
from urllib.parse import urlsplit
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


# Conservative phone digit bounds (E.164 caps a subscriber number at 15 digits).
_MIN_PHONE_DIGITS = 5
_MAX_PHONE_DIGITS = 15


def _require_dict(entry: Any, field_name: str) -> Dict[str, Any]:
    """Fail closed: a malformed non-dict nested entry is rejected, never silently dropped."""
    if not isinstance(entry, dict):
        raise ValueError(f"{field_name} entries must be objects, got {type(entry).__name__}")
    return entry


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
    # Conservative bounds — reject implausibly short/long numbers (E.164 caps at 15).
    if len(digits) < _MIN_PHONE_DIGITS:
        raise ValueError(f"phone has too few digits: {value!r}")
    if len(digits) > _MAX_PHONE_DIGITS:
        raise ValueError(f"phone has too many digits: {value!r}")
    # Conservative: preserve an explicit leading '+', never invent a country code.
    # Normalization does not claim validity or reachability.
    return ("+" if has_plus else "") + digits


def _normalize_contact_form(value: str) -> str:
    v = value.strip()
    if not v:
        raise ValueError("contact_form reference must be non-empty")
    if "\\" in v or any(ord(char) < 32 for char in v):
        raise ValueError(
            f"contact_form reference contains an unsafe path character: {value!r}"
        )
    # Protocol-relative references (//host/path) are rejected.
    if v.startswith("//"):
        raise ValueError(
            f"protocol-relative contact_form reference not allowed: {value!r}"
        )
    parts = urlsplit(v)
    if parts.fragment:
        raise ValueError(f"contact_form fragments are not allowed: {value!r}")
    # Relative path with exactly one leading slash is allowed.
    if v.startswith("/"):
        if parts.scheme or parts.netloc:
            raise ValueError(f"malformed relative contact_form reference: {value!r}")
        query = f"?{parts.query}" if parts.query else ""
        return f"{parts.path}{query}"
    if parts.scheme not in ("http", "https"):
        raise ValueError(
            f"contact_form must be an http(s) URL or a '/'-path: {value!r}"
        )
    if "@" in parts.netloc or parts.username or parts.password:
        raise ValueError(f"contact_form must not contain credentials: {value!r}")
    try:
        port = parts.port
    except ValueError as exc:
        raise ValueError(f"contact_form has an invalid port: {value!r}") from exc
    if port is not None:
        raise ValueError(f"contact_form must not specify a port: {value!r}")
    host = parts.hostname
    if not host:
        raise ValueError(f"contact_form has no host: {value!r}")
    # normalize_hostname rejects IPs, localhost, single-label, and malformed hosts.
    norm_host = normalize_hostname(host)
    path = parts.path or "/"
    query = f"?{parts.query}" if parts.query else ""
    return f"{parts.scheme}://{norm_host}{path}{query}"


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
        if not isinstance(self.source, SourceReference):
            raise ValueError("source must be a SourceReference object")
        if self.source_category not in CONTACT_SOURCE_CATEGORIES:
            raise ValueError(f"Unknown contact source_category: {self.source_category!r}")
        if self.extraction_method not in EXTRACTION_METHODS:
            raise ValueError(f"Unknown extraction_method: {self.extraction_method!r}")
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"Unknown confidence: {self.confidence!r}")
        if self.terms_review_status not in TERMS_REVIEW_STATUSES:
            raise ValueError(f"Unknown terms_review_status: {self.terms_review_status!r}")
        if not isinstance(self.observed_at, str):
            raise ValueError("observed_at must be a string")
        if not isinstance(self.evidence_ref, str):
            raise ValueError("evidence_ref must be a string")
        if not isinstance(self.publicly_published_for_contact, bool):
            raise ValueError("publicly_published_for_contact must be a boolean")
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

    @property
    def counts_for_verification(self) -> bool:
        """Whether this provenance may support VERIFIED status (fail-closed).

        Requires a non-inferred public/manual source that was visibly published for
        contact, with a valid observation timestamp, a non-empty evidence reference, and
        terms review that is not blocked. A plausible format or provider label alone can
        never qualify.
        """
        return (
            self.is_public_verified_source
            and self.publicly_published_for_contact
            and _valid_iso(self.observed_at)
            and isinstance(self.evidence_ref, str)
            and bool(self.evidence_ref.strip())
            and self.terms_review_status != "reviewed_blocked"
        )

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
        if "source" in data:
            kwargs["source"] = SourceReference.from_dict(
                _require_dict(data["source"], "source")
            )
        else:
            kwargs["source"] = SourceReference()
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
    manual_review_ref: str = ""
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
        if not isinstance(self.value, str):
            raise ValueError("contact value must be a string")
        for field_name in (
            "first_observed_at",
            "last_verified_at",
            "suppression_check_ref",
            "manual_review_ref",
        ):
            if not isinstance(getattr(self, field_name), str):
                raise ValueError(f"{field_name} must be a string")
        if not isinstance(self.manual_review_required, bool):
            raise ValueError("manual_review_required must be a boolean")
        if not self.value.strip():
            raise ValueError("contact value must be non-empty")
        _reject_secret_value(self.value)
        if not isinstance(self.provenance, list) or not all(
            isinstance(p, ContactProvenance) for p in self.provenance
        ):
            raise ValueError("provenance must be a list of ContactProvenance objects")
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
            if not any(p.counts_for_verification for p in self.provenance):
                raise ValueError(
                    "VERIFIED requires at least one fully-qualified public verified "
                    "provenance (non-inferred, published-for-contact, timestamped, "
                    "evidenced, terms not blocked)"
                )
            if not self.last_verified_at.strip():
                raise ValueError("VERIFIED requires a non-empty last_verified_at")

    @property
    def is_inferred_only(self) -> bool:
        """True when every provenance record is inferred (no public/manual verification)."""
        return bool(self.provenance) and all(p.is_inferred for p in self.provenance)

    @property
    def has_verified_provenance(self) -> bool:
        return any(p.counts_for_verification for p in self.provenance)

    @property
    def named_person_review_complete(self) -> bool:
        """Named-person contacts require a recorded reviewed decision; others are exempt."""
        if self.data_subject_category != "named_person":
            return True
        return isinstance(self.manual_review_ref, str) and bool(
            self.manual_review_ref.strip()
        )

    @property
    def is_outreach_candidate(self) -> bool:
        """Fail-closed contract indicator (does NOT authorize or perform outreach).

        Requires VERIFIED status backed by a fully-qualified public verified provenance, a
        valid verification timestamp, not inferred-only, no suppression/DNC state, a
        completed named-person review (when applicable), and a suppression-check reference.
        """
        return (
            self.status == "VERIFIED"
            and not self.is_inferred_only
            and self.has_verified_provenance
            and _valid_iso(self.last_verified_at)
            and self.status not in ("SUPPRESSED", "DO_NOT_CONTACT")
            and self.named_person_review_complete
            and isinstance(self.suppression_check_ref, str)
            and bool(self.suppression_check_ref.strip())
        )

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
            "manual_review_ref": self.manual_review_ref,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContactRecord":
        known = {
            "contact_id", "schema_version", "company_ref", "domain_ref", "channel",
            "value", "display_name", "role_title", "data_subject_category", "status",
            "first_observed_at", "last_verified_at", "suppression_check_ref",
            "manual_review_required", "manual_review_ref", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        prov = data.get("provenance") or []
        kwargs["provenance"] = [ContactProvenance.from_dict(_require_dict(p, "provenance")) for p in prov]
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
        if not isinstance(self.contacts, list) or not all(
            isinstance(contact, ContactRecord) for contact in self.contacts
        ):
            raise ValueError("contacts must be a list of ContactRecord objects")
        for original in self.contacts:
            # Own a defensive copy so de-duplication never mutates caller-owned records.
            contact = ContactRecord.from_dict(original.to_dict())
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
            ContactRecord.from_dict(_require_dict(c, "contacts")) for c in contacts
        ]
        return cls(**kwargs)


def _merge_contacts(a: ContactRecord, b: ContactRecord) -> ContactRecord:
    """Return a merged copy: stricter status wins and caller-owned inputs stay untouched."""
    keep = a if _STATUS_STRICTNESS[a.status] >= _STATUS_STRICTNESS[b.status] else b
    other = b if keep is a else a
    merged = ContactRecord.from_dict(keep.to_dict())
    merged_prov = list(merged.provenance)
    for prov in other.provenance:
        if prov not in merged_prov:
            merged_prov.append(ContactProvenance.from_dict(prov.to_dict()))
    merged.provenance = merged_prov
    merged.manual_review_required = (
        a.manual_review_required or b.manual_review_required
    )
    if not merged.manual_review_ref.strip():
        merged.manual_review_ref = (
            a.manual_review_ref.strip() or b.manual_review_ref.strip()
        )
    if not merged.suppression_check_ref.strip():
        merged.suppression_check_ref = (
            a.suppression_check_ref.strip() or b.suppression_check_ref.strip()
        )
    merged.notes = _dedup_strings([*a.notes, *b.notes])
    return merged


def _dedup_strings(values: List[str]) -> List[str]:
    """Preserve first-seen order while returning a detached deterministic list."""
    seen: set[str] = set()
    result: List[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result

"""Prospect Radar coverage & site-fingerprint contracts (Phase 8.2 — slice 2).

Planning / contracts only. No runtime, discovery, crawling, browser, network, MCP,
change-detection, or database. `CoverageMap` describes *planned/observed public QA
coverage*; `SiteFingerprint` is a versioned data container for fingerprint values and
comparison metadata. Neither computes anything or accesses a site.

REUSE NOTES (verified against the repository):
- Serialization: `core.schemas.base.SchemaMixin` (unknown keys ignored → additive-safe).
- Capability references validated against existing `ATOMIC_CAPABILITIES`.
- Provenance reuses `core.schemas.source_reference.SourceReference`.
- Fingerprints are opaque strings (same convention as `WorkPacket.input_fingerprint`);
  this schema never hashes or crawls anything — values are produced by a future,
  separately approved runtime.

Coverage semantics:
- Public QA coverage and commercial opportunity are **separate concepts**; this module
  models only QA coverage (commercial context lives in `BusinessContext` / future
  scoring schemas).
- `COVERED` / `PARTIAL` assert observed coverage and therefore require an evidence or
  verification reference. In planning-only Phase 8.2 (nothing executes) the
  planning-safe statuses are `PLANNED`, `BLOCKED`, `DEFERRED`, `NOT_APPLICABLE`; the
  execution-implying statuses remain in the vocabulary for future phases but cannot be
  claimed without evidence.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import re
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin
from core.schemas.capability import ATOMIC_CAPABILITIES
from core.schemas.source_reference import SourceReference
from core.schemas.prospect_interaction import (
    PROSPECT_CONTRACT_SCHEMA_VERSION,
    require_object_list,
)

COVERAGE_STATUSES = frozenset({
    "PLANNED",
    "COVERED",
    "PARTIAL",
    "BLOCKED",
    "DEFERRED",
    "NOT_APPLICABLE",
})

# Statuses that assert observed coverage — require an evidence/verification reference.
_COVERAGE_REQUIRES_EVIDENCE = frozenset({"COVERED", "PARTIAL"})

# Statuses safely usable in planning-only Phase 8.2 (no execution result exists).
COVERAGE_PLANNING_SAFE_STATUSES = frozenset({
    "PLANNED", "BLOCKED", "DEFERRED", "NOT_APPLICABLE",
})

COMPARISON_STATUSES = frozenset({"unknown", "new", "unchanged", "changed"})

# Supported fingerprint digest algorithms and their required hex length. Fingerprint
# values are opaque digests produced by a future runtime; the schema never hashes.
SUPPORTED_FINGERPRINT_ALGORITHMS = frozenset({"sha256"})
_DIGEST_HEX_LENGTHS = {"sha256": 64}
_HEX_RE = re.compile(r"^[0-9a-f]+$")
_FINGERPRINT_VALUE_FIELDS = (
    "content_fingerprint",
    "structural_fingerprint",
    "commercial_flow_fingerprint",
)

# Terms that must never appear in fingerprint inputs (no secrets / session / volatile
# browser state may be captured into a fingerprint).
_FORBIDDEN_FINGERPRINT_TERMS = (
    "cookie",
    "set-cookie",
    "session",
    "token",
    "password",
    "passwd",
    "secret",
    "credential",
    "authorization",
    "auth=",
    "bearer",
    "jwt",
    "api_key",
    "apikey",
    "access_token",
    "refresh_token",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _require_subset(values: List[str], allowed: frozenset[str], field_name: str) -> None:
    for value in values:
        if value not in allowed:
            raise ValueError(f"Unknown value {value!r} in {field_name}")


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
class CoverageArea(SchemaMixin):
    """One QA coverage area with a fail-closed status (planning-only).

    `COVERED` / `PARTIAL` require a non-empty `evidence_refs` or `verification_ref`;
    a planning artifact can never claim observed coverage without evidence.
    """

    area: str = ""
    status: str = "PLANNED"
    reason: str = ""
    limitation: str = ""
    evidence_refs: List[str] = field(default_factory=list)
    capability_refs: List[str] = field(default_factory=list)
    access_dependency: str = ""
    verification_ref: str = ""

    def __post_init__(self) -> None:
        if self.status not in COVERAGE_STATUSES:
            raise ValueError(f"Unknown coverage status: {self.status!r}")
        if not self.area.strip():
            raise ValueError("CoverageArea.area must be a non-empty string")
        # Deterministic de-duplication + capability validation.
        self.capability_refs = _dedup(self.capability_refs)
        _require_subset(self.capability_refs, ATOMIC_CAPABILITIES, "capability_refs")
        self.evidence_refs = _dedup(self.evidence_refs)
        for ref in self.evidence_refs:
            if not ref.strip():
                raise ValueError("evidence_refs entries must be non-empty strings")
        # COVERED/PARTIAL assert observed coverage: they require a non-blank evidence or
        # verification reference (a blank placeholder is rejected).
        if self.status in _COVERAGE_REQUIRES_EVIDENCE and not (
            any(e.strip() for e in self.evidence_refs) or self.verification_ref.strip()
        ):
            raise ValueError(
                f"coverage status {self.status!r} requires a non-empty evidence or "
                "verification reference"
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoverageArea":
        return super().from_dict(data)


@dataclass
class CoverageMap(SchemaMixin):
    """Public QA coverage projection for a subject (planning-only).

    QA coverage only — commercial opportunity is a separate concept and is not modeled
    here. Each area is a fail-closed `CoverageArea`.
    """

    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    subject_ref: str = ""
    areas: List[CoverageArea] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "subject_ref": self.subject_ref,
            "areas": [a.to_dict() for a in self.areas],
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CoverageMap":
        known = {"schema_version", "subject_ref", "notes"}
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["areas"] = [
            CoverageArea.from_dict(a)
            for a in require_object_list(data.get("areas"), "areas")
        ]
        return cls(**kwargs)


@dataclass
class SiteFingerprint(SchemaMixin):
    """Versioned fingerprint values + comparison metadata (planning-only data container).

    Stores opaque fingerprint strings and a deterministic (sorted, de-duplicated) list
    of fingerprint input descriptors. It never hashes, crawls, or detects change, and
    forbids secret/session/volatile-state material in its inputs.
    """

    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    subject_ref: str = ""
    fingerprint_algorithm: str = "sha256"
    content_fingerprint: str = ""
    structural_fingerprint: str = ""
    commercial_flow_fingerprint: str = ""
    fingerprint_inputs: List[str] = field(default_factory=list)
    source_refs: List[SourceReference] = field(default_factory=list)
    generated_at: str = field(default_factory=_now_iso)
    previous_fingerprint_ref: str = ""
    comparison_status: str = "unknown"
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.comparison_status not in COMPARISON_STATUSES:
            raise ValueError(f"Unknown comparison_status: {self.comparison_status!r}")
        if self.fingerprint_algorithm not in SUPPORTED_FINGERPRINT_ALGORITHMS:
            raise ValueError(
                f"Unsupported fingerprint_algorithm: {self.fingerprint_algorithm!r}"
            )
        # Fingerprint value fields must be empty (incomplete planning record) or a valid
        # digest of the selected algorithm. This rejects raw URLs, secrets, cookies,
        # tokens, user data, or prose (they are not hex digests of the right length).
        expected_len = _DIGEST_HEX_LENGTHS[self.fingerprint_algorithm]
        for name in _FINGERPRINT_VALUE_FIELDS:
            raw = getattr(self, name)
            if not raw:
                continue
            normalized = raw.strip().lower()
            if len(normalized) != expected_len or not _HEX_RE.match(normalized):
                raise ValueError(
                    f"{name} must be a {self.fingerprint_algorithm} hex digest "
                    f"({expected_len} hex chars), got {raw!r}"
                )
            setattr(self, name, normalized)  # deterministic lowercase normalization
        for item in self.fingerprint_inputs:
            lowered = item.lower()
            for term in _FORBIDDEN_FINGERPRINT_TERMS:
                if term in lowered:
                    raise ValueError(
                        f"fingerprint input {item!r} contains forbidden term {term!r}"
                    )
        # Deterministic representation: sorted, de-duplicated inputs.
        self.fingerprint_inputs = sorted(set(self.fingerprint_inputs))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "subject_ref": self.subject_ref,
            "fingerprint_algorithm": self.fingerprint_algorithm,
            "content_fingerprint": self.content_fingerprint,
            "structural_fingerprint": self.structural_fingerprint,
            "commercial_flow_fingerprint": self.commercial_flow_fingerprint,
            "fingerprint_inputs": list(self.fingerprint_inputs),
            "source_refs": [s.to_dict() for s in self.source_refs],
            "generated_at": self.generated_at,
            "previous_fingerprint_ref": self.previous_fingerprint_ref,
            "comparison_status": self.comparison_status,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SiteFingerprint":
        known = {
            "schema_version", "subject_ref", "fingerprint_algorithm",
            "content_fingerprint", "structural_fingerprint",
            "commercial_flow_fingerprint", "fingerprint_inputs", "generated_at",
            "previous_fingerprint_ref", "comparison_status", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["source_refs"] = [
            SourceReference.from_dict(r)
            for r in require_object_list(data.get("source_refs"), "source_refs")
        ]
        return cls(**kwargs)

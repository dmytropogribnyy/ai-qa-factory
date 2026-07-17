"""Prospect Radar identity contracts (Phase 8.2 — slice 3).

Planning / contracts only. No DNS, network, crawling, WHOIS, contact lookup, database,
or PII. `DomainIdentity` normalizes a *bare hostname* (never a URL) and `CompanyIdentity`
deduplicates one commercial entity across its domains/brands.

REUSE NOTES (verified against the repository):
- Serialization: `core.schemas.base.SchemaMixin` (unknown keys ignored → additive-safe).
- Provenance reuses `core.schemas.source_reference.SourceReference`.
- Confidence vocabulary reuses `core.schemas.finding.Confidence` values.
- Version string reuses `PROSPECT_CONTRACT_SCHEMA_VERSION`.

Identity is deliberately separate from contacts, commercial scoring, and outreach status.
No DNS verification is claimed; no legal identity is guessed; no private data is stored.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin
from core.schemas.finding import Confidence
from core.schemas.source_reference import SourceReference
from core.schemas.prospect_interaction import PROSPECT_CONTRACT_SCHEMA_VERSION

CONFIDENCE_LEVELS = frozenset(c.value for c in Confidence)

DOMAIN_RELATIONS = frozenset({
    "primary",
    "brand",
    "regional",
    "subdomain",
    "product",
    "redirect",
    "unknown",
})

# Characters/sequences that indicate a URL or credentials rather than a bare hostname.
_FORBIDDEN_HOSTNAME_MARKERS = ("://", "/", "?", "#", "@", ":")


def _dedup(seq: List[str]) -> List[str]:
    """Order-preserving de-duplication."""
    seen: set[str] = set()
    out: List[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def normalize_hostname(raw: str) -> str:
    """Normalize a bare hostname deterministically (no DNS, no network).

    - rejects empty, whitespace, scheme/path/query/fragment/credentials/port;
    - lowercases and strips a trailing dot;
    - requires at least two non-empty labels (a registrable domain) — this rejects
      bare single-label / internal names like ``localhost`` as unsupported planning data;
    - preserves international (unicode) labels as-is (no punycode conversion is claimed).
    """
    if raw is None:
        raise ValueError("hostname must be provided")
    host = raw.strip()
    if not host:
        raise ValueError("hostname must be non-empty")
    if any(ch.isspace() for ch in host):
        raise ValueError("hostname must not contain whitespace")
    for marker in _FORBIDDEN_HOSTNAME_MARKERS:
        if marker in host:
            raise ValueError(
                f"hostname must be a bare host, not a URL/credentialed value (found {marker!r})"
            )
    host = host.rstrip(".").lower()
    if not host:
        raise ValueError("hostname must be non-empty after normalization")
    labels = host.split(".")
    if len(labels) < 2:
        raise ValueError(
            f"hostname {raw!r} must be a registrable domain (>= 2 labels); "
            "single-label/internal hosts are unsupported planning data"
        )
    for label in labels:
        if not label:
            raise ValueError(f"hostname {raw!r} has an empty label")
        if len(label) > 63:
            raise ValueError(f"hostname {raw!r} has a label longer than 63 chars")
    return host


@dataclass
class DomainIdentity(SchemaMixin):
    """A normalized domain identity (planning-only; no DNS verification claimed)."""

    domain_id: str = field(default_factory=lambda: str(uuid4()))
    hostname: str = ""
    relation: str = "unknown"
    is_primary: bool = False
    sources: List[SourceReference] = field(default_factory=list)
    confidence: str = "low"
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.hostname = normalize_hostname(self.hostname)
        if self.relation not in DOMAIN_RELATIONS:
            raise ValueError(f"Unknown domain relation: {self.relation!r}")
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"Unknown confidence: {self.confidence!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain_id": self.domain_id,
            "hostname": self.hostname,
            "relation": self.relation,
            "is_primary": self.is_primary,
            "sources": [s.to_dict() for s in self.sources],
            "confidence": self.confidence,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DomainIdentity":
        known = {"domain_id", "hostname", "relation", "is_primary", "confidence", "notes"}
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        sources = data.get("sources") or []
        kwargs["sources"] = [
            SourceReference.from_dict(s) for s in sources if isinstance(s, dict)
        ]
        return cls(**kwargs)


@dataclass
class CompanyIdentity(SchemaMixin):
    """One deduplicated commercial entity (planning-only).

    Separate from contacts, commercial scoring, and outreach status. A company may have
    many domains but at most one primary; domains are unique by canonical hostname.
    Legal identity is never guessed; no private data is stored.
    """

    company_id: str = field(default_factory=lambda: str(uuid4()))
    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    canonical_name: str = ""
    legal_name: str = ""
    brand_names: List[str] = field(default_factory=list)
    aliases: List[str] = field(default_factory=list)
    domains: List[DomainIdentity] = field(default_factory=list)
    sources: List[SourceReference] = field(default_factory=list)
    confidence: str = "low"
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"Unknown confidence: {self.confidence!r}")
        self.brand_names = _dedup(self.brand_names)
        self.aliases = _dedup(self.aliases)
        # Domains are unique by canonical hostname; more than one primary is rejected.
        seen_hosts: set[str] = set()
        primary_count = 0
        for domain in self.domains:
            if domain.hostname in seen_hosts:
                raise ValueError(f"duplicate domain hostname: {domain.hostname!r}")
            seen_hosts.add(domain.hostname)
            if domain.is_primary:
                primary_count += 1
        if primary_count > 1:
            raise ValueError("a company may have at most one primary domain")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "company_id": self.company_id,
            "schema_version": self.schema_version,
            "canonical_name": self.canonical_name,
            "legal_name": self.legal_name,
            "brand_names": list(self.brand_names),
            "aliases": list(self.aliases),
            "domains": [d.to_dict() for d in self.domains],
            "sources": [s.to_dict() for s in self.sources],
            "confidence": self.confidence,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CompanyIdentity":
        known = {
            "company_id", "schema_version", "canonical_name", "legal_name",
            "brand_names", "aliases", "confidence", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        domains = data.get("domains") or []
        kwargs["domains"] = [
            DomainIdentity.from_dict(d) for d in domains if isinstance(d, dict)
        ]
        sources = data.get("sources") or []
        kwargs["sources"] = [
            SourceReference.from_dict(s) for s in sources if isinstance(s, dict)
        ]
        return cls(**kwargs)

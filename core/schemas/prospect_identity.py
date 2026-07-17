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

import ipaddress
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin
from core.schemas.finding import Confidence
from core.schemas.source_reference import SourceReference
from core.schemas.prospect_interaction import (
    PROSPECT_CONTRACT_SCHEMA_VERSION,
    require_object_list,
)

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

# A single valid LDH (letter-digit-hyphen) label: 1..63 chars, no leading/trailing
# hyphen, no underscore or other characters. Applied to the ASCII/IDNA form.
_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
_MAX_HOSTNAME_LEN = 253


def _dedup_ci(seq: List[str], field_name: str) -> List[str]:
    """Case-insensitive de-duplication preserving the first display spelling.

    Blank entries are rejected (fail closed).
    """
    seen: set[str] = set()
    out: List[str] = []
    for item in seq:
        stripped = item.strip()
        if not stripped:
            raise ValueError(f"{field_name} entries must be non-empty")
        key = stripped.lower()
        if key not in seen:
            seen.add(key)
            out.append(stripped)
    return out


def normalize_hostname(raw: str) -> str:
    """Normalize a bare hostname deterministically (standard library only; no DNS/network).

    - accepts only a bare hostname (rejects scheme/path/query/fragment/credentials/port);
    - rejects whitespace, IPv4/IPv6 literals (via ``ipaddress``), and single-label/internal
      names such as ``localhost``;
    - IDNA-encodes international labels to ASCII punycode deterministically;
    - stored canonical form is lowercase ASCII/IDNA;
    - validates total length (<= 253) and each label (1..63 LDH chars, no leading/trailing
      hyphen, no underscore/invalid chars, no empty label);
    - removes a single trailing dot. No DNS or network check is performed.
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
                f"hostname must be a bare host, not a URL/credentialed/ported value "
                f"(found {marker!r})"
            )
    host = host.rstrip(".")
    if not host:
        raise ValueError("hostname must be non-empty after normalization")
    # Reject IP literals — a fingerprint/identity hostname must be a domain name.
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass  # not an IP address — good
    else:
        raise ValueError(f"IP addresses are not valid hostnames: {host!r}")
    host_lower = host.lower()
    if host_lower.isascii():
        ascii_host = host_lower
    else:
        try:
            ascii_host = host_lower.encode("idna").decode("ascii")
        except (UnicodeError, ValueError) as exc:
            raise ValueError(
                f"hostname {raw!r} is not a valid IDNA domain: {exc}"
            ) from exc
    if len(ascii_host) > _MAX_HOSTNAME_LEN:
        raise ValueError(f"hostname {raw!r} exceeds {_MAX_HOSTNAME_LEN} chars")
    labels = ascii_host.split(".")
    if len(labels) < 2:
        raise ValueError(
            f"hostname {raw!r} must be a registrable domain (>= 2 labels); "
            "single-label/internal hosts are unsupported planning data"
        )
    for label in labels:
        if not label:
            raise ValueError(f"hostname {raw!r} has an empty label")
        if not _LABEL_RE.match(label):
            raise ValueError(
                f"invalid hostname label {label!r} in {raw!r} "
                "(LDH only; no leading/trailing hyphen, underscore, or invalid chars)"
            )
    return ascii_host


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
        # Keep is_primary and relation='primary' consistent: setting either implies both.
        if self.is_primary or self.relation == "primary":
            self.is_primary = True
            self.relation = "primary"

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
        kwargs["sources"] = [
            SourceReference.from_dict(s)
            for s in require_object_list(data.get("sources"), "sources")
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
        self.canonical_name = self.canonical_name.strip()
        self.legal_name = self.legal_name.strip()
        self.brand_names = _dedup_ci(self.brand_names, "brand_names")
        self.aliases = _dedup_ci(self.aliases, "aliases")
        # A company must be identifiable: a canonical name or at least one domain.
        if not self.canonical_name and not self.domains:
            raise ValueError(
                "CompanyIdentity requires a non-empty canonical_name or at least one domain"
            )
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
        kwargs["domains"] = [
            DomainIdentity.from_dict(d)
            for d in require_object_list(data.get("domains"), "domains")
        ]
        kwargs["sources"] = [
            SourceReference.from_dict(s)
            for s in require_object_list(data.get("sources"), "sources")
        ]
        return cls(**kwargs)

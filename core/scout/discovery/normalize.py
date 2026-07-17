"""Candidate normalization + deduplication (Phase 8.4).

Turns untrusted `DiscoveryCandidate`s into `CandidateRecord`s with a safe normalized URL and a
best-effort registrable domain (reusing the Scout URL-safety and the Phase 8.2
`normalize_hostname`). Deduplicates by normalized URL, then by domain, then flags likely
same-company aliases as *uncertain identity* for review — it never silently merges uncertain
companies. Invalid/private/credentialed URLs are flagged here and never fetched later.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple

from core.schemas.prospect_identity import normalize_hostname
from core.scout.discovery.candidate import (
    DUP_DOMAIN,
    DUP_UNCERTAIN,
    DUP_UNIQUE,
    DUP_URL,
    CandidateRecord,
)
from core.scout.discovery.providers import DiscoveryCandidate
from core.scout.url_safety import UrlPolicy, check_url


@dataclass
class NormalizationReport:
    total: int = 0
    normalized: int = 0
    invalid_url: int = 0
    duplicates_url: int = 0
    duplicates_domain: int = 0
    duplicates_company: int = 0
    uncertain_identity: int = 0
    unique: int = 0
    details: List[Dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def _registrable_domain(host: str) -> str:
    """Best-effort registrable domain: validated hostname with a leading 'www.' stripped.

    (Not a full public-suffix computation — honest approximation used only for dedup grouping.)
    """
    try:
        canonical = normalize_hostname(host)
    except ValueError:
        return ""
    return canonical[4:] if canonical.startswith("www.") else canonical


def _candidate_id(campaign_id: str, provider_id: str, key: str) -> str:
    raw = f"{campaign_id}\x00{provider_id}\x00{key}".encode("utf-8")
    return "cand-" + hashlib.sha1(raw).hexdigest()[:16]


def _norm_name(name: str) -> str:
    return " ".join(name.lower().split())


def normalize_candidates(candidates: List[DiscoveryCandidate], campaign_id: str,
                         policy: UrlPolicy) -> Tuple[List[CandidateRecord], NormalizationReport]:
    report = NormalizationReport(total=len(candidates))
    records: List[CandidateRecord] = []
    for cand in candidates:
        rec = CandidateRecord(
            campaign_id=campaign_id, provider_id=cand.provider_id,
            source_provenance=[cand.provenance().to_dict()],
            public_url=cand.website, business_name=cand.business_name,
            country_hint=cand.country_hint, language_hint=cand.language_hint,
            industry_hint=cand.industry_hint, business_type_hint=cand.business_type_hint,
            discovered_at=cand.observed_at or datetime.now(timezone.utc).isoformat(),
            confidence=cand.confidence,
        )
        elig = check_url(cand.website, policy=policy)
        if elig.eligible:
            rec.normalized_url = elig.normalized
            rec.registrable_domain = _registrable_domain(elig.host)
            report.normalized += 1
        else:
            rec.normalized_url = ""
            rec.eligibility_status = "technical_reject"
            rec.technical_reasons.append(f"invalid_or_private_url:{elig.reason}")
            rec.add_reason("invalid_or_private_url")
            report.invalid_url += 1
        key = rec.normalized_url or cand.website or _norm_name(cand.business_name) or cand.raw_candidate_id
        rec.candidate_id = _candidate_id(campaign_id, cand.provider_id, key)
        records.append(rec)

    _dedup(records, report)
    report.unique = sum(1 for r in records if r.duplicate_status == DUP_UNIQUE)
    return records, report


def _dedup(records: List[CandidateRecord], report: NormalizationReport) -> None:
    seen_url: Dict[str, str] = {}
    seen_domain: Dict[str, str] = {}
    seen_company: Dict[str, Tuple[str, str]] = {}  # name -> (candidate_id, domain)
    for rec in records:
        if not rec.normalized_url:
            continue  # invalid URLs are not deduped (already flagged, never fetched)
        if rec.normalized_url in seen_url:
            rec.duplicate_status = DUP_URL
            rec.duplicate_of = seen_url[rec.normalized_url]
            rec.add_reason("duplicate_url")
            report.duplicates_url += 1
            _merge_provenance(records, rec)
            continue
        if rec.registrable_domain and rec.registrable_domain in seen_domain:
            rec.duplicate_status = DUP_DOMAIN
            rec.duplicate_of = seen_domain[rec.registrable_domain]
            rec.add_reason("duplicate_domain")
            report.duplicates_domain += 1
            _merge_provenance(records, rec)
            continue
        name = _norm_name(rec.business_name)
        if name and name in seen_company and seen_company[name][1] != rec.registrable_domain:
            # Same name on a different domain: likely the same company, but not proven.
            # Mark for review — never silently merge uncertain identities.
            rec.duplicate_status = DUP_UNCERTAIN
            rec.duplicate_of = seen_company[name][0]
            rec.add_reason("uncertain_identity_review")
            report.uncertain_identity += 1
        seen_url[rec.normalized_url] = rec.candidate_id
        if rec.registrable_domain:
            seen_domain[rec.registrable_domain] = rec.candidate_id
        if name:
            seen_company.setdefault(name, (rec.candidate_id, rec.registrable_domain))


def _merge_provenance(records: List[CandidateRecord], dup: CandidateRecord) -> None:
    """Attach the duplicate's provenance to its canonical record (cross-provider evidence)."""
    canonical = next((r for r in records if r.candidate_id == dup.duplicate_of), None)
    if canonical is not None:
        for prov in dup.source_provenance:
            if prov not in canonical.source_provenance:
                canonical.source_provenance.append(prov)

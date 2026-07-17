"""Finding normalization, independent verification, and lifecycle reconciliation (Final Phase I).

Capabilities emit `RawObservation`s. Normalization merges observations into `NormalizedFinding`s
**only** when they share one root user impact (`root_impact_key`); distinct defects are never
merged just because titles look alike, and every source observation's provenance is preserved.
Independent verification requires the same signature to reproduce across two independent passes
before a finding can become VERIFIED + sanitized (hence CLIENT_SAFE-eligible). Lifecycle
reconciliation (used by rechecks) marks findings RESOLVED or REGRESSED without mutating history.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

from core.scout.pipeline.finding import (
    L_ACTIVE,
    L_REGRESSED,
    L_RESOLVED,
    V_REJECTED,
    V_VERIFIED,
    NormalizedFinding,
)

_SEV_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3}


@dataclass
class RawObservation:
    capability: str = ""
    category: str = "functional"
    title: str = ""
    severity: str = "low"
    confidence: str = "medium"
    url: str = ""
    root_impact_key: str = ""
    signature: str = ""
    reproduction_steps: List[str] = field(default_factory=list)
    expected: str = ""
    actual: str = ""
    business_impact: str = ""
    provenance: Dict[str, Any] = field(default_factory=dict)
    from_clean_session: bool = True

    def key(self) -> str:
        return self.root_impact_key or self.signature or f"{self.capability}:{self.title}"


def _finding_id(campaign_id: str, company_id: str, key: str) -> str:
    raw = f"{campaign_id}\x00{company_id}\x00{key}".encode("utf-8")
    return "f-" + hashlib.sha1(raw).hexdigest()[:16]


def normalize_findings(observations: List[RawObservation], *, campaign_id: str, company_id: str,
                       session_id: str, url: str, clock_iso: str) -> List[NormalizedFinding]:
    """Merge observations sharing a root impact into one finding each (provenance preserved)."""
    groups: Dict[str, List[RawObservation]] = {}
    for obs in observations:
        groups.setdefault(obs.key(), []).append(obs)

    findings: List[NormalizedFinding] = []
    for key, group in groups.items():
        lead = max(group, key=lambda o: _SEV_ORDER.get(o.severity, 0))
        steps: List[str] = []
        provenance: List[Dict[str, Any]] = []
        impacts: List[str] = []
        for obs in group:
            for step in obs.reproduction_steps:
                if step not in steps:
                    steps.append(step)
            if obs.provenance and obs.provenance not in provenance:
                provenance.append(obs.provenance)
            if obs.business_impact and obs.business_impact not in impacts:
                impacts.append(obs.business_impact)
        findings.append(NormalizedFinding(
            finding_id=_finding_id(campaign_id, company_id, key),
            campaign_id=campaign_id, company_id=company_id, session_id=session_id,
            url=lead.url or url, capability=lead.capability, category=lead.category,
            title=lead.title, severity=lead.severity, confidence=lead.confidence,
            root_impact_key=key, signature=lead.signature,
            reproduction_steps=steps or [f"Open {lead.url or url}"],
            expected=lead.expected, actual=lead.actual,
            business_impact=" ".join(impacts), provenance=provenance,
            from_clean_session=all(o.from_clean_session for o in group),
            first_seen_at=clock_iso, last_seen_at=clock_iso))
    findings.sort(key=lambda f: (-_SEV_ORDER.get(f.severity, 0), f.finding_id))
    return findings


def verify_findings(first_pass: List[NormalizedFinding], second_pass_signatures: set,
                    ) -> Tuple[List[NormalizedFinding], List[NormalizedFinding]]:
    """Independent verification: only findings whose signature reproduced in a second pass are
    marked VERIFIED (+sanitized here as content is evidence-by-reference). Others are REJECTED.
    A finding from an unclean session can never become client-safe (kept unsanitized)."""
    verified: List[NormalizedFinding] = []
    rejected: List[NormalizedFinding] = []
    for f in first_pass:
        if f.signature in second_pass_signatures:
            f.verification_state = V_VERIFIED
            f.sanitized = f.from_clean_session  # unclean session => never sanitized/client-safe
            (verified if f.sanitized else rejected).append(f)
            if not f.sanitized:
                f.verification_state = V_REJECTED
                f.notes.append("rejected: evidence from an unclean reversible session")
        else:
            f.verification_state = V_REJECTED
            f.notes.append("rejected: not reproduced in the independent second pass")
            rejected.append(f)
    return verified, rejected


def reconcile_lifecycle(prior: List[NormalizedFinding], current: List[NormalizedFinding],
                        *, clock_iso: str) -> Dict[str, Any]:
    """Compare a prior scan's findings with the current scan (rechecks). Returns a summary and
    mutates `current`/carries forward: findings absent now become RESOLVED; a finding that was
    RESOLVED and reappears becomes REGRESSED (requiring fresh verification). History is not
    mutated — resolved/regressed carry-forwards are new records the caller persists."""
    prior_by_key = {f.root_impact_key: f for f in prior}
    current_keys = {f.root_impact_key for f in current}
    resolved: List[NormalizedFinding] = []
    regressed: List[NormalizedFinding] = []

    for key, pf in prior_by_key.items():
        if key not in current_keys and pf.lifecycle_state == L_ACTIVE:
            carry = NormalizedFinding.from_dict(pf.to_dict())
            carry.lifecycle_state = L_RESOLVED
            carry.resolved_at = clock_iso
            carry.last_seen_at = clock_iso
            resolved.append(carry)

    for cf in current:
        pf = prior_by_key.get(cf.root_impact_key)
        if pf is not None and pf.lifecycle_state == L_RESOLVED:
            cf.lifecycle_state = L_REGRESSED
            # A regression must be independently re-verified before it is client-safe again.
            cf.verification_state = "UNVERIFIED"
            cf.sanitized = False
            cf.notes.append("regressed: reopened; requires new verification")
            regressed.append(cf)

    return {"resolved": [f.to_dict() for f in resolved],
            "regressed": [f.to_dict() for f in regressed],
            "resolved_count": len(resolved), "regressed_count": len(regressed)}

"""Suppression + exclusion check applied BEFORE any HTTP profiling or Scout promotion (Phase 8.4).

Reuses the Phase 8.2 `SuppressionPolicy` (modes NO_OUTREACH / NO_SCAN / COOLDOWN /
MONITOR_CHANGES_ONLY). `NO_SCAN` blocks all profiling and any fetch. `NO_OUTREACH` may still
permit read-only profiling only when the campaign policy explicitly permits it, and can never
later become outreach-ready. Every exclusion carries an explainable reason code and is applied
before anything is fetched.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.schemas.prospect_governance import SuppressionPolicy
from core.scout.discovery.candidate import CandidateRecord


@dataclass
class SuppressionReportRow:
    candidate_id: str = ""
    domain: str = ""
    mode: str = ""
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class SuppressionReport:
    checked: int = 0
    suppressed: int = 0
    no_scan: int = 0
    no_outreach_profiling_allowed: int = 0
    rows: List[SuppressionReportRow] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"checked": self.checked, "suppressed": self.suppressed,
                "no_scan": self.no_scan,
                "no_outreach_profiling_allowed": self.no_outreach_profiling_allowed,
                "rows": [r.to_dict() for r in self.rows]}


def _strip_www(domain: str) -> str:
    return domain[4:] if domain.startswith("www.") else domain


def _domain_index(policies: List[SuppressionPolicy]) -> Dict[str, SuppressionPolicy]:
    """Map each suppressed domain (www-stripped canonical hostname) to its enabled policy."""
    index: Dict[str, SuppressionPolicy] = {}
    for pol in policies:
        if not pol.enabled:
            continue
        for dom in pol.applies_to_domains:
            index[_strip_www(dom)] = pol
    return index


def apply_suppression(records: List[CandidateRecord], policies: List[SuppressionPolicy],
                      *, allow_readonly_when_no_outreach: bool) -> SuppressionReport:
    """Annotate each record's suppression status/reason. Runs before any fetch or promotion."""
    report = SuppressionReport(checked=len(records))
    index = _domain_index(policies)
    for rec in records:
        pol = index.get(_strip_www(rec.registrable_domain)) if rec.registrable_domain else None
        if pol is None:
            continue
        rec.suppression_status = pol.mode
        rec.suppression_reason = pol.reason or pol.mode
        rec.add_reason(f"suppressed:{pol.mode}")
        row = SuppressionReportRow(candidate_id=rec.candidate_id, domain=rec.registrable_domain,
                                   mode=pol.mode, reason=rec.suppression_reason)
        report.rows.append(row)
        report.suppressed += 1
        if pol.mode == "NO_SCAN":
            # Blocks all profiling and promotion — never fetched.
            rec.eligibility_status = "skipped"
            rec.technical_reasons.append("suppressed_no_scan_never_fetched")
            report.no_scan += 1
        elif pol.mode == "NO_OUTREACH":
            if allow_readonly_when_no_outreach:
                # Read-only profiling stays permitted, but the candidate can never become
                # outreach-ready (Phase 8.4 performs no outreach at all).
                report.no_outreach_profiling_allowed += 1
            else:
                rec.eligibility_status = "skipped"
                rec.technical_reasons.append("suppressed_no_outreach_profiling_disabled")
    return report

"""Phase 6.2 -- Risk matrix: scoring, sorting, and aggregation of findings.

Deterministic: given the same list of Finding objects, always produces the
same ordering and summary. No randomness, no timestamps in sort keys.
"""
from __future__ import annotations

from collections import defaultdict

from core.schemas.finding import Confidence, Finding, Severity

# Weights for risk_score calculation
_SEVERITY_WEIGHTS: dict[Severity, int] = {
    Severity.CRITICAL: 5,
    Severity.HIGH: 4,
    Severity.MEDIUM: 3,
    Severity.LOW: 2,
    Severity.INFO: 1,
}

_CONFIDENCE_WEIGHTS: dict[Confidence, float] = {
    Confidence.HIGH: 1.0,
    Confidence.MEDIUM: 0.75,
    Confidence.LOW: 0.5,
}


def risk_score(finding: Finding) -> float:
    """Compute a deterministic risk score for a single finding.

    Score = severity_weight * confidence_weight
    Range: 0.5 (INFO + LOW confidence) to 5.0 (CRITICAL + HIGH confidence)
    """
    sw = _SEVERITY_WEIGHTS.get(finding.severity, 1)
    cw = _CONFIDENCE_WEIGHTS.get(finding.confidence, 0.75)
    return round(sw * cw, 4)


class RiskMatrix:
    """Aggregate and group a list of Finding objects for reporting."""

    def __init__(self, findings: list[Finding]) -> None:
        self._findings = list(findings)  # defensive copy

    # ------------------------------------------------------------------
    # Sorting
    # ------------------------------------------------------------------

    def sorted_by_risk(self) -> list[Finding]:
        """Return findings sorted by risk_score descending, then id ascending."""
        return sorted(
            self._findings,
            key=lambda f: (-risk_score(f), f.id),
        )

    def top_n(self, n: int = 5) -> list[Finding]:
        """Return the top N findings by risk score."""
        return self.sorted_by_risk()[:n]

    # ------------------------------------------------------------------
    # Grouping
    # ------------------------------------------------------------------

    def by_severity(self) -> dict[str, list[Finding]]:
        """Return findings grouped by severity (all severity levels always present)."""
        result: dict[str, list[Finding]] = {s.value: [] for s in Severity}
        for f in self._findings:
            result[f.severity.value].append(f)
        return result

    def by_category(self) -> dict[str, list[Finding]]:
        """Return findings grouped by category (only categories that have findings)."""
        result: dict[str, list[Finding]] = defaultdict(list)
        for f in self._findings:
            result[f.category.value].append(f)
        return dict(result)

    def by_source_module(self) -> dict[str, list[Finding]]:
        """Return findings grouped by source_module."""
        result: dict[str, list[Finding]] = defaultdict(list)
        for f in self._findings:
            result[f.source_module].append(f)
        return dict(result)

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------

    def count_by_severity(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.by_severity().items()}

    def count_by_category(self) -> dict[str, int]:
        return {k: len(v) for k, v in self.by_category().items()}

    def summary(self) -> dict:
        """Return a complete summary dict suitable for JSON serialization."""
        top = [f.to_dict() for f in self.top_n(5)]
        return {
            "total": len(self._findings),
            "by_severity": self.count_by_severity(),
            "by_category": self.count_by_category(),
            "top_risks": top,
            "has_critical": any(f.severity == Severity.CRITICAL for f in self._findings),
            "has_high": any(f.severity == Severity.HIGH for f in self._findings),
            "recommended_next_actions": self._next_actions(),
        }

    def _next_actions(self) -> list[str]:
        actions = []
        by_sev = self.by_severity()
        if by_sev[Severity.CRITICAL.value]:
            actions.append("Address CRITICAL findings immediately before any release.")
        if by_sev[Severity.HIGH.value]:
            actions.append("Plan HIGH severity findings into the next sprint.")
        if by_sev[Severity.MEDIUM.value]:
            actions.append("Schedule MEDIUM severity improvements in upcoming iterations.")
        if not self._findings:
            actions.append("No findings generated. Run modules with explicit approvals for deeper analysis.")
        return actions

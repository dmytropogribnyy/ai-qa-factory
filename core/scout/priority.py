"""A/B/C prioritization + QA-value score (v3.3).

Priority combines the *commercial-opportunity* score (from discovery triage) with *QA evidence*
(verified findings from the Scout run) — never commercial score alone:

- **A** (actionable): strong commercial fit AND ≥1 evidence-backed medium/high public finding.
- **B**: reasonable commercial fit AND a useful UX/a11y/SEO/responsive/performance/funnel gap.
- **C**: analyzed but weak fit, weak evidence, or relatively clean — retained in history,
  never discarded automatically.

The QA-value score is tracked separately from the commercial score so the Dashboard can show
both. Rejected (directory/social/duplicate/unavailable/prohibited) is decided earlier in
triage/suppression, not here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

STRONG_COMMERCIAL = 75
REASONABLE_COMMERCIAL = 60

_SEV_WEIGHT = {"high": 40, "medium": 20, "low": 8, "info": 2}


def _has_evidence(f: Dict[str, Any]) -> bool:
    return bool(f.get("evidence_refs") or f.get("evidence_ids"))


def _evidence_backed(f: Dict[str, Any]) -> bool:
    """An evidence-backed medium/high public finding (the bar for a Priority-A prospect)."""
    return f.get("severity") in ("medium", "high") and _has_evidence(f)


def _useful_gap(f: Dict[str, Any]) -> bool:
    return f.get("severity") in ("low", "medium", "high")


@dataclass
class Prioritization:
    priority: str                     # "A" | "B" | "C"
    qa_value: int                     # 0-100, independent of commercial score
    commercial_score: int
    strong_finding: bool
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def qa_value_score(findings: List[Dict[str, Any]]) -> int:
    """QA-opportunity value from findings: severity-weighted with an evidence bonus, capped 100."""
    score = 0
    for f in findings or []:
        score += _SEV_WEIGHT.get(f.get("severity"), 0)
        if _evidence_backed(f):
            score += 10
    return min(score, 100)


def classify(commercial_score: int, findings: List[Dict[str, Any]]) -> Prioritization:
    findings = findings or []
    strong = any(_evidence_backed(f) for f in findings)
    useful = any(_useful_gap(f) for f in findings)
    reasons: List[str] = []
    if commercial_score >= STRONG_COMMERCIAL and strong:
        priority, why = "A", "strong commercial fit + evidence-backed medium/high finding"
    elif commercial_score >= REASONABLE_COMMERCIAL and useful:
        priority, why = "B", "reasonable commercial fit + useful QA gap"
    else:
        priority, why = "C", "weak fit / weak evidence / relatively clean (retained in history)"
    reasons.append(why)
    return Prioritization(priority=priority, qa_value=qa_value_score(findings),
                          commercial_score=int(commercial_score), strong_finding=strong,
                          reasons=reasons)


def load_verified_findings(scout_store) -> List[Dict[str, Any]]:
    """Aggregate verified findings across a completed Scout run's prospects (dict form)."""
    try:
        state = scout_store.load_state()
    except Exception:
        return []
    pids = list((state or {}).get("prospects", {}).keys())
    out: List[Dict[str, Any]] = []
    for pid in pids:
        data = None
        try:
            data = scout_store.load_prospect_artifact(pid, "findings.json")
        except Exception:
            data = None
        for fd in (data or {}).get("verified", []):
            out.append(fd)
    return out


def scout_actionable(rec, scout_store) -> bool:
    """Actionable-target predicate for the discovery engine: the promoted+analyzed candidate is
    Priority A (strong commercial fit AND an evidence-backed medium/high finding)."""
    findings = load_verified_findings(scout_store)
    return classify(getattr(rec, "commercial_score", 0), findings).priority == "A"

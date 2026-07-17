"""Scout scoring — deterministic, explainable, and NON-authorizing (Phase 8.3).

Builds a Phase 8.2 `LeadScorecard` from verified findings. Every dimension stays independently
visible. Scoring never authorizes outreach: `outreach_eligible` is always False here, and a
high score does not make any contact an outreach candidate or any disclosure ready.
"""
from __future__ import annotations

from typing import List

from core.schemas.prospect_scoring import LeadScorecard, ScoreDimension
from core.scout.findings import ScoutFinding

_SEVERITY_WEIGHT = {"info": 0, "low": 1, "medium": 3, "high": 6}


def build_scorecard(prospect_id: str, verified_findings: List[ScoutFinding]) -> LeadScorecard:
    defects = [f for f in verified_findings if f.severity != "info"]
    total_weight = sum(_SEVERITY_WEIGHT.get(f.severity, 0) for f in defects)

    # More/severe verified defects → higher audit opportunity (bounded 0..100).
    audit_opportunity = min(100, total_weight * 8)
    # Business impact from the presence of high-severity, impact-bearing defects.
    business_impact = min(100, sum(6 if f.severity == "high" else 3 if f.severity == "medium"
                                   else 0 for f in defects) * 4)
    # Evidence quality: verified findings are evidence-backed and sanitized.
    evidence_quality = 80 if defects else 40
    # Public coverage: how many distinct check families produced verified defects.
    families = {f.check_family for f in defects}
    public_coverage = min(100, len(families) * 20)
    # Technical confidence: high when findings reproduced with high confidence.
    high_conf = sum(1 for f in defects if f.confidence == "high")
    technical_confidence = min(100, 40 + high_conf * 15)

    dims = [
        ScoreDimension(name="audit_opportunity", value=audit_opportunity),
        ScoreDimension(name="business_impact", value=business_impact),
        ScoreDimension(name="evidence_quality", value=evidence_quality),
        ScoreDimension(name="public_coverage", value=public_coverage),
        ScoreDimension(name="technical_confidence", value=technical_confidence),
    ]

    if audit_opportunity >= 60:
        priority = "A"
    elif audit_opportunity >= 35:
        priority = "B"
    elif audit_opportunity >= 15:
        priority = "C"
    else:
        priority = "D"

    return LeadScorecard(
        prospect_id=prospect_id,
        dimensions=dims,
        priority=priority,
        outreach_eligible=False,  # scoring never authorizes outreach
        rationale=[
            f"{len(defects)} verified defect(s) across {len(families)} check famil(y/ies)",
            "score is advisory only and does not authorize outreach",
        ],
    )

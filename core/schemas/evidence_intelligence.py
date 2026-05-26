"""Phase 5K — Evidence Intelligence schemas.

Models structured analysis of existing evidence artifacts — gap detection,
coverage scoring, and recommendations. Static analysis only; no execution.

Safety invariants (hardcoded in __post_init__ + from_dict):
- network_calls_made=False
- execution_performed=False
- safe_to_deliver=False
- human_review_required=True
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.schemas.base import SchemaMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EVIDENCE_GAP_SEVERITIES = ("low", "medium", "high", "critical")

EVIDENCE_COVERAGE_AREAS = (
    "auth",
    "api",
    "mobile",
    "database",
    "visual",
    "task_source",
    "pipeline",
    "qa_report",
    "intake",
    "test_oracle",
)

# Maps coverage area label → artifact directory suffix
EVIDENCE_ARTIFACT_DIR_MAP: dict = {
    "auth": "12_dedicated_auth",
    "api": "13_api_auth",
    "qa_report": "14_qa_report",
    "google_auth": "15_google_auth",
    "task_source": "16_task_source",
    "mobile": "17_mobile_viewport",
    "visual": "18_visual_regression",
    "github_auth": "19_github_auth",
    "pipeline": "20_e2e_pipeline",
    "database": "21_db_smoke",
    "intake": "22_intake",
    "test_oracle": "23_test_oracle",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class EvidenceGap(SchemaMixin):
    """A single coverage gap identified in the evidence artifacts."""
    area: str = ""
    severity: str = "medium"
    description: str = ""
    recommendation: str = ""
    missing_artifact_dir: str = ""


@dataclass
class EvidenceCoverageItem(SchemaMixin):
    """Coverage status for a single evidence area."""
    area: str = ""
    artifact_dir: str = ""
    present: bool = False
    artifact_count: int = 0


@dataclass
class EvidenceIntelligenceReport(SchemaMixin):
    """Full evidence intelligence report — gaps, coverage, recommendations."""
    project_id: str = ""
    gaps: List[EvidenceGap] = field(default_factory=list)
    coverage_items: List[EvidenceCoverageItem] = field(default_factory=list)
    overall_coverage_score: float = 0.0
    high_severity_gap_count: int = 0
    recommendations: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # Safety invariants
    network_calls_made: bool = False
    execution_performed: bool = False
    safe_to_deliver: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "network_calls_made", False)
        object.__setattr__(self, "execution_performed", False)
        object.__setattr__(self, "safe_to_deliver", False)
        object.__setattr__(self, "human_review_required", True)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["gaps"] = [g.to_dict() for g in self.gaps]
        d["coverage_items"] = [c.to_dict() for c in self.coverage_items]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "EvidenceIntelligenceReport":
        gaps = [
            EvidenceGap(**g) if isinstance(g, dict) else g
            for g in data.get("gaps", [])
        ]
        items = [
            EvidenceCoverageItem(**c) if isinstance(c, dict) else c
            for c in data.get("coverage_items", [])
        ]
        obj = cls(
            project_id=str(data.get("project_id", "")),
            gaps=gaps,
            coverage_items=items,
            overall_coverage_score=float(data.get("overall_coverage_score", 0.0)),
            high_severity_gap_count=int(data.get("high_severity_gap_count", 0)),
            recommendations=list(data.get("recommendations", [])),
            blockers=list(data.get("blockers", [])),
            notes=list(data.get("notes", [])),
        )
        object.__setattr__(obj, "network_calls_made", False)
        object.__setattr__(obj, "execution_performed", False)
        object.__setattr__(obj, "safe_to_deliver", False)
        object.__setattr__(obj, "human_review_required", True)
        return obj

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class SelfAssessmentFinding(SchemaMixin):
    """One finding from a self-assessment of a generated artifact or workflow output."""

    id: str = field(default_factory=lambda: str(uuid4()))
    category: str = ""
    severity: str = "info"
    finding: str = ""
    recommendation: str = ""
    auto_fixable: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SelfAssessmentFinding:
        return super().from_dict(data)


@dataclass
class SelfAssessment(SchemaMixin):
    """Self-assessment results for a project run or artifact set."""

    project_id: str
    run_id: str = ""
    overall_score: float = 0.0
    findings: List[SelfAssessmentFinding] = field(default_factory=list)
    assessed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "overall_score": self.overall_score,
            "findings": [f.to_dict() for f in self.findings],
            "assessed_at": self.assessed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SelfAssessment:
        findings = [
            SelfAssessmentFinding.from_dict(f) if isinstance(f, dict) else f
            for f in data.get("findings", [])
        ]
        return cls(
            project_id=data["project_id"],
            run_id=data.get("run_id", ""),
            overall_score=data.get("overall_score", 0.0),
            findings=findings,
            assessed_at=data.get("assessed_at", datetime.now(timezone.utc).isoformat()),
        )

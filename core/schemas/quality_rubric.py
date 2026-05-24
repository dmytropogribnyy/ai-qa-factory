from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class QualityCriterion(SchemaMixin):
    """One criterion in a quality rubric."""

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    weight: float = 1.0
    passing_threshold: float = 0.7
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> QualityCriterion:
        return super().from_dict(data)


@dataclass
class QualityRubric(SchemaMixin):
    """Scoring rubric applied to project artifacts or test quality."""

    project_id: str
    criteria: List[QualityCriterion] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "criteria": [c.to_dict() for c in self.criteria],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> QualityRubric:
        criteria = [
            QualityCriterion.from_dict(c) if isinstance(c, dict) else c
            for c in data.get("criteria", [])
        ]
        return cls(
            project_id=data["project_id"],
            criteria=criteria,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )

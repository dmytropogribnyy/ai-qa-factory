from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class ToolRecommendation(SchemaMixin):
    """One tool recommendation for a project or test layer."""

    id: str = field(default_factory=lambda: str(uuid4()))
    tool_name: str = ""
    category: str = ""
    rationale: str = ""
    is_mandatory: bool = False
    alternatives: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolRecommendation:
        return super().from_dict(data)


@dataclass
class ToolSelection(SchemaMixin):
    """Tool selection for a project, with rationale per tool."""

    project_id: str
    recommendations: List[ToolRecommendation] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "recommendations": [r.to_dict() for r in self.recommendations],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolSelection:
        recommendations = [
            ToolRecommendation.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("recommendations", [])
        ]
        return cls(
            project_id=data["project_id"],
            recommendations=recommendations,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )

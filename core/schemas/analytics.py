from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class AnalyticsMetric(SchemaMixin):
    """One metric measurement in an analytics report."""

    id: str = field(default_factory=lambda: str(uuid4()))
    metric_name: str = ""
    value: float = 0.0
    unit: str = ""
    dimension: str = ""
    recorded_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AnalyticsMetric:
        return super().from_dict(data)


@dataclass
class AnalyticsReport(SchemaMixin):
    """Analytics report aggregating metrics for a project."""

    project_id: str
    metrics: List[AnalyticsMetric] = field(default_factory=list)
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "metrics": [m.to_dict() for m in self.metrics],
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AnalyticsReport:
        metrics = [
            AnalyticsMetric.from_dict(m) if isinstance(m, dict) else m
            for m in data.get("metrics", [])
        ]
        return cls(
            project_id=data["project_id"],
            metrics=metrics,
            generated_at=data.get("generated_at", datetime.now(timezone.utc).isoformat()),
        )

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin


@dataclass
class TaskClassification(SchemaMixin):
    """Classification result for a work request."""

    project_id: str = ""
    task_type: str = "unknown"
    project_type: str = "unknown"
    source_platform: str = "unknown"
    confidence: float = 0.0
    signals: List[str] = field(default_factory=list)
    notes: str = ""
    classified_at: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TaskClassification:
        return super().from_dict(data)

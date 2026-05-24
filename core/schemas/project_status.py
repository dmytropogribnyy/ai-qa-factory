from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin


@dataclass
class ProjectStatus(SchemaMixin):
    """Current status snapshot for a project."""

    project_id: str
    phase: str = "intake"
    overall_status: str = "in_progress"
    pending_approvals: List[str] = field(default_factory=list)
    completed_phases: List[str] = field(default_factory=list)
    next_action: str = ""
    notes: str = ""
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectStatus:
        return super().from_dict(data)

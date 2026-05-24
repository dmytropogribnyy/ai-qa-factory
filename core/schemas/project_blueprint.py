from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin


@dataclass
class ProjectBlueprint(SchemaMixin):
    """Structured source-of-truth for a client project."""

    project_id: str
    project_name: str = ""
    project_type: str = "unknown"
    client_name: str = ""
    target_urls: List[str] = field(default_factory=list)
    tech_stack: List[str] = field(default_factory=list)
    scope_notes: str = ""
    out_of_scope_notes: str = ""
    environment: str = "unknown"
    risk_areas: List[str] = field(default_factory=list)
    constraints: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProjectBlueprint:
        return super().from_dict(data)

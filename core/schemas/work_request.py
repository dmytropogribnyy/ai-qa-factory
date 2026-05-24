from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class WorkRequest(SchemaMixin):
    """Normalised intake record for any work that enters the workbench."""

    id: str = field(default_factory=lambda: str(uuid4()))
    project_id: str = ""
    # Core QA-first intake fields
    request_title: str = ""
    request_summary: str = ""
    client_context: str = ""
    inputs: List[str] = field(default_factory=list)
    desired_outcome: str = ""
    constraints: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
    # Legacy / convenience fields kept for compatibility
    title: str = ""
    raw_brief: str = ""
    source_platform: str = "unknown"
    source_url: str = ""
    target_urls: List[str] = field(default_factory=list)
    budget_range: str = ""
    deadline: str = ""
    client_name: str = ""
    tags: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> WorkRequest:
        return super().from_dict(data)

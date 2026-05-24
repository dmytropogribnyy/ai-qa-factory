from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin


@dataclass
class RunContext(SchemaMixin):
    """Context for a single workflow execution run."""

    project_id: str
    run_id: str = ""
    workflow: str = ""
    mode: str = "mock"
    approved: bool = False
    flags: List[str] = field(default_factory=list)
    source_platform: str = "unknown"
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str = ""
    agents_run: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RunContext:
        return super().from_dict(data)

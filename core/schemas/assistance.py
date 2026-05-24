from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class AssistanceRecord(SchemaMixin):
    """One session of AI-assisted work logged for a project."""

    id: str = field(default_factory=lambda: str(uuid4()))
    assistant_type: str = "unknown"
    workflow: str = ""
    llm_mode: str = "mock"
    agents_invoked: List[str] = field(default_factory=list)
    artifacts_produced: List[str] = field(default_factory=list)
    notes: str = ""
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    completed_at: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AssistanceRecord:
        return super().from_dict(data)


@dataclass
class AssistanceHistory(SchemaMixin):
    """History of all AI assistance sessions for a project."""

    project_id: str
    records: List[AssistanceRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "records": [r.to_dict() for r in self.records],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AssistanceHistory:
        records = [
            AssistanceRecord.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("records", [])
        ]
        return cls(
            project_id=data["project_id"],
            records=records,
        )

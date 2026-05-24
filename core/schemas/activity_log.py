from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class ActivityEvent(SchemaMixin):
    """One logged event in a project's activity timeline."""

    id: str = field(default_factory=lambda: str(uuid4()))
    event_type: str = "info"
    agent: str = ""
    message: str = ""
    details: str = ""
    occurred_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ActivityEvent:
        return super().from_dict(data)


@dataclass
class ActivityLog(SchemaMixin):
    """Ordered log of all activity events for a project."""

    project_id: str
    events: List[ActivityEvent] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "events": [e.to_dict() for e in self.events],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ActivityLog:
        events = [
            ActivityEvent.from_dict(e) if isinstance(e, dict) else e
            for e in data.get("events", [])
        ]
        return cls(
            project_id=data["project_id"],
            events=events,
        )

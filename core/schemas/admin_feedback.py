from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class AdminNotification(SchemaMixin):
    """One admin notification or feedback item requiring attention."""

    id: str = field(default_factory=lambda: str(uuid4()))
    category: str = "info"
    severity: str = "low"
    message: str = ""
    action_required: bool = False
    resolved: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    resolved_at: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AdminNotification:
        return super().from_dict(data)


@dataclass
class AdminFeedbackCenter(SchemaMixin):
    """Center for admin notifications and feedback items."""

    project_id: str
    notifications: List[AdminNotification] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "notifications": [n.to_dict() for n in self.notifications],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AdminFeedbackCenter:
        notifications = [
            AdminNotification.from_dict(n) if isinstance(n, dict) else n
            for n in data.get("notifications", [])
        ]
        return cls(
            project_id=data["project_id"],
            notifications=notifications,
        )

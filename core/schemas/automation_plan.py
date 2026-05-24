from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class AutomationAction(SchemaMixin):
    """One planned automation action (test, script, validation step)."""

    id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    action_type: str = "unknown"
    risk_level: str = "safe_local"
    target: str = ""
    framework: str = ""
    priority: int = 0
    status: str = "pending"
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AutomationAction:
        return super().from_dict(data)


@dataclass
class AutomationPlan(SchemaMixin):
    """Full automation plan for a project."""

    project_id: str
    actions: List[AutomationAction] = field(default_factory=list)
    framework_primary: str = "playwright_typescript"
    notes: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "actions": [a.to_dict() for a in self.actions],
            "framework_primary": self.framework_primary,
            "notes": self.notes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AutomationPlan:
        actions = [
            AutomationAction.from_dict(a) if isinstance(a, dict) else a
            for a in data.get("actions", [])
        ]
        return cls(
            project_id=data["project_id"],
            actions=actions,
            framework_primary=data.get("framework_primary", "playwright_typescript"),
            notes=data.get("notes", ""),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )

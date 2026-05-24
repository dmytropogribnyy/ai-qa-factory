from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class Blocker(SchemaMixin):
    """One blocking issue preventing progress on a project."""

    id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    description: str = ""
    severity: str = "medium"
    status: str = "open"
    raised_by: str = ""
    resolution_notes: str = ""
    raised_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    resolved_at: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Blocker:
        return super().from_dict(data)


@dataclass
class BlockerRegister(SchemaMixin):
    """Register of all blockers for a project."""

    project_id: str
    blockers: List[Blocker] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "blockers": [b.to_dict() for b in self.blockers],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BlockerRegister:
        blockers = [
            Blocker.from_dict(b) if isinstance(b, dict) else b
            for b in data.get("blockers", [])
        ]
        return cls(
            project_id=data["project_id"],
            blockers=blockers,
        )

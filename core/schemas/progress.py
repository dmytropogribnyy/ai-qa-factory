from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class ProgressItem(SchemaMixin):
    """One trackable progress item for a project."""

    id: str = field(default_factory=lambda: str(uuid4()))
    title: str = ""
    category: str = ""
    status: str = "pending"
    completion_pct: int = 0
    notes: str = ""
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProgressItem:
        return super().from_dict(data)


@dataclass
class ProgressTracker(SchemaMixin):
    """Progress tracking for all items in a project."""

    project_id: str
    items: List[ProgressItem] = field(default_factory=list)
    overall_pct: int = 0
    updated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "items": [i.to_dict() for i in self.items],
            "overall_pct": self.overall_pct,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ProgressTracker:
        items = [
            ProgressItem.from_dict(i) if isinstance(i, dict) else i
            for i in data.get("items", [])
        ]
        return cls(
            project_id=data["project_id"],
            items=items,
            overall_pct=data.get("overall_pct", 0),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )

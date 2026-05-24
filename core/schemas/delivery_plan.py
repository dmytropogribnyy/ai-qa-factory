from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class DeliveryItem(SchemaMixin):
    """One deliverable in a delivery plan."""

    id: str = field(default_factory=lambda: str(uuid4()))
    deliverable_type: str = "unknown"
    title: str = ""
    description: str = ""
    status: str = "pending"
    due_date: str = ""
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DeliveryItem:
        return super().from_dict(data)


@dataclass
class DeliveryPlan(SchemaMixin):
    """Planned deliverables for a project."""

    project_id: str
    items: List[DeliveryItem] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "items": [i.to_dict() for i in self.items],
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DeliveryPlan:
        items = [
            DeliveryItem.from_dict(i) if isinstance(i, dict) else i
            for i in data.get("items", [])
        ]
        return cls(
            project_id=data["project_id"],
            items=items,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )

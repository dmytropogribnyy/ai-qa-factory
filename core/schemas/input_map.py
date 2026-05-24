from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class InputSource(SchemaMixin):
    """One classified input item (file, URL, text block, etc.)."""

    id: str = field(default_factory=lambda: str(uuid4()))
    input_type: str = "unknown"
    label: str = ""
    raw_value: str = ""
    classification_notes: str = ""
    approved: bool = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InputSource:
        return super().from_dict(data)


@dataclass
class InputMap(SchemaMixin):
    """All classified inputs for a project, keyed by project_id."""

    project_id: str
    sources: List[InputSource] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "project_id": self.project_id,
            "sources": [s.to_dict() for s in self.sources],
            "created_at": self.created_at,
        }
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InputMap:
        sources = [
            InputSource.from_dict(s) if isinstance(s, dict) else s
            for s in data.get("sources", [])
        ]
        return cls(
            project_id=data["project_id"],
            sources=sources,
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )

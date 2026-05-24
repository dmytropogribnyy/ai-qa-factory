from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class MediaEvidenceItem(SchemaMixin):
    """One piece of media evidence (screenshot, video, trace) from a test run."""

    id: str = field(default_factory=lambda: str(uuid4()))
    media_type: str = "screenshot"
    file_path: str = ""
    test_name: str = ""
    captured_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    description: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MediaEvidenceItem:
        return super().from_dict(data)


@dataclass
class MediaEvidenceCollection(SchemaMixin):
    """Collection of all media evidence for a project run."""

    project_id: str
    run_id: str = ""
    items: List[MediaEvidenceItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "items": [i.to_dict() for i in self.items],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MediaEvidenceCollection:
        items = [
            MediaEvidenceItem.from_dict(i) if isinstance(i, dict) else i
            for i in data.get("items", [])
        ]
        return cls(
            project_id=data["project_id"],
            run_id=data.get("run_id", ""),
            items=items,
        )

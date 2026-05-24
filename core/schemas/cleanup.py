from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class CleanupCandidate(SchemaMixin):
    """One file or artifact flagged as a cleanup candidate."""

    id: str = field(default_factory=lambda: str(uuid4()))
    file_path: str = ""
    reason: str = ""
    risk: str = "low"
    approved_for_deletion: bool = False
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CleanupCandidate:
        return super().from_dict(data)


@dataclass
class CleanupReport(SchemaMixin):
    """Dry-run cleanup report — lists candidates, never deletes automatically."""

    project_id: str
    candidates: List[CleanupCandidate] = field(default_factory=list)
    dry_run: bool = True
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "candidates": [c.to_dict() for c in self.candidates],
            "dry_run": self.dry_run,
            "generated_at": self.generated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CleanupReport:
        candidates = [
            CleanupCandidate.from_dict(c) if isinstance(c, dict) else c
            for c in data.get("candidates", [])
        ]
        return cls(
            project_id=data["project_id"],
            candidates=candidates,
            dry_run=data.get("dry_run", True),
            generated_at=data.get("generated_at", datetime.now(timezone.utc).isoformat()),
        )

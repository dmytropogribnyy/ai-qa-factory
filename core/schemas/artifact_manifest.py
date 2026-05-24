from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class ArtifactRecord(SchemaMixin):
    """One artifact produced by the workbench for a project."""

    id: str = field(default_factory=lambda: str(uuid4()))
    artifact_type: str = "unknown"
    filename: str = ""
    relative_path: str = ""
    is_client_facing: bool = False
    is_internal: bool = True
    generated_by: str = ""
    generated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    notes: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ArtifactRecord:
        return super().from_dict(data)


@dataclass
class ArtifactManifest(SchemaMixin):
    """Registry of all artifacts produced for a project."""

    project_id: str
    artifacts: List[ArtifactRecord] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "artifacts": [a.to_dict() for a in self.artifacts],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ArtifactManifest:
        artifacts = [
            ArtifactRecord.from_dict(a) if isinstance(a, dict) else a
            for a in data.get("artifacts", [])
        ]
        return cls(
            project_id=data["project_id"],
            artifacts=artifacts,
        )

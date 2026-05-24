from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class ApprovalDecision(SchemaMixin):
    """One recorded approval or rejection decision."""

    id: str = field(default_factory=lambda: str(uuid4()))
    action_key: str = ""
    decision: str = "pending"
    risk_level: str = "safe_local"
    decided_by: str = ""
    reason: str = ""
    decided_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ApprovalDecision:
        return super().from_dict(data)


@dataclass
class ApprovalHistory(SchemaMixin):
    """All approval decisions for a project."""

    project_id: str
    decisions: List[ApprovalDecision] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "decisions": [d.to_dict() for d in self.decisions],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ApprovalHistory:
        decisions = [
            ApprovalDecision.from_dict(d) if isinstance(d, dict) else d
            for d in data.get("decisions", [])
        ]
        return cls(
            project_id=data["project_id"],
            decisions=decisions,
        )

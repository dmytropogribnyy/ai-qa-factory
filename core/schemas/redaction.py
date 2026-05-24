from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class SecretRedactionRule(SchemaMixin):
    """One rule specifying how a secret type should be redacted in a given target."""

    id: str = field(default_factory=lambda: str(uuid4()))
    target: str = ""
    pattern_type: str = "generic_secret"
    replacement: str = "[REDACTED]"
    enabled: bool = True
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SecretRedactionRule:
        return super().from_dict(data)


@dataclass
class RedactionReport(SchemaMixin):
    """Report summarising what redaction was applied for a project run."""

    project_id: str
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    rules_applied: List[SecretRedactionRule] = field(default_factory=list)
    redaction_performed: bool = False
    possible_secret_leaks_found: bool = False
    blocked_client_delivery: bool = False
    summary: str = ""
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "created_at": self.created_at,
            "rules_applied": [r.to_dict() for r in self.rules_applied],
            "redaction_performed": self.redaction_performed,
            "possible_secret_leaks_found": self.possible_secret_leaks_found,
            "blocked_client_delivery": self.blocked_client_delivery,
            "summary": self.summary,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RedactionReport:
        rules = [
            SecretRedactionRule.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("rules_applied", [])
        ]
        return cls(
            project_id=data["project_id"],
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            rules_applied=rules,
            redaction_performed=data.get("redaction_performed", False),
            possible_secret_leaks_found=data.get("possible_secret_leaks_found", False),
            blocked_client_delivery=data.get("blocked_client_delivery", False),
            summary=data.get("summary", ""),
            notes=data.get("notes", []),
        )

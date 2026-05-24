from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin


@dataclass
class SafetyCheck(SchemaMixin):
    """One safety rule evaluation for a run or action."""

    rule_id: str = ""
    rule_label: str = ""
    passed: bool = True
    violation_detail: str = ""
    checked_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SafetyCheck:
        return super().from_dict(data)


@dataclass
class SafetyReport(SchemaMixin):
    """Aggregated safety evaluation for a run."""

    project_id: str
    run_id: str = ""
    all_passed: bool = True
    checks: List[SafetyCheck] = field(default_factory=list)
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "all_passed": self.all_passed,
            "checks": [c.to_dict() for c in self.checks],
            "evaluated_at": self.evaluated_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SafetyReport:
        checks = [
            SafetyCheck.from_dict(c) if isinstance(c, dict) else c
            for c in data.get("checks", [])
        ]
        return cls(
            project_id=data["project_id"],
            run_id=data.get("run_id", ""),
            all_passed=data.get("all_passed", True),
            checks=checks,
            evaluated_at=data.get("evaluated_at", datetime.now(timezone.utc).isoformat()),
        )

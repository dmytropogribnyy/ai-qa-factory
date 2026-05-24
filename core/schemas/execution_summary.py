from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin


@dataclass
class EvidenceItem(SchemaMixin):
    """One piece of evidence from a test run (screenshot, trace, log snippet)."""

    id: str = field(default_factory=lambda: str(uuid4()))
    evidence_type: str = "unknown"
    label: str = ""
    file_path: str = ""
    description: str = ""
    captured_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> EvidenceItem:
        return super().from_dict(data)


@dataclass
class ExecutionSummary(SchemaMixin):
    """Summary of a completed test execution run."""

    project_id: str
    run_id: str = ""
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    skipped: int = 0
    duration_seconds: float = 0.0
    evidence: List[EvidenceItem] = field(default_factory=list)
    notes: str = ""
    executed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "run_id": self.run_id,
            "total_tests": self.total_tests,
            "passed": self.passed,
            "failed": self.failed,
            "skipped": self.skipped,
            "duration_seconds": self.duration_seconds,
            "evidence": [e.to_dict() for e in self.evidence],
            "notes": self.notes,
            "executed_at": self.executed_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionSummary:
        evidence = [
            EvidenceItem.from_dict(e) if isinstance(e, dict) else e
            for e in data.get("evidence", [])
        ]
        return cls(
            project_id=data["project_id"],
            run_id=data.get("run_id", ""),
            total_tests=data.get("total_tests", 0),
            passed=data.get("passed", 0),
            failed=data.get("failed", 0),
            skipped=data.get("skipped", 0),
            duration_seconds=data.get("duration_seconds", 0.0),
            evidence=evidence,
            notes=data.get("notes", ""),
            executed_at=data.get("executed_at", datetime.now(timezone.utc).isoformat()),
        )

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin

VALIDATION_STATUSES = {"pass", "fail", "warning", "unknown", "skipped"}
CHECK_STATUSES = {"pass", "fail", "warning", "skipped"}
SEVERITIES = {"info", "low", "medium", "high", "critical"}
CATEGORIES = {
    "structure", "metadata", "safety", "secrets", "urls",
    "package_json", "config", "env", "tests", "docs",
    "repository_boundary", "toolchain_plan",
}


@dataclass
class ScaffoldValidationCheck(SchemaMixin):
    id: str = ""
    name: str = ""
    category: str = "structure"
    status: str = "skipped"
    severity: str = "info"
    file_path: str = ""
    message: str = ""
    recommendation: str = ""
    blocks_next_phase: bool = False
    notes: List[str] = field(default_factory=list)


@dataclass
class ScaffoldValidationReport(SchemaMixin):
    project_id: str = ""
    scaffold_root: str = ""
    validation_status: str = "unknown"
    execution_performed: bool = False
    npm_performed: bool = False
    npx_performed: bool = False
    browser_performed: bool = False
    external_calls_performed: bool = False
    checks: List[ScaffoldValidationCheck] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    safe_to_proceed_to_toolchain_validation: bool = False
    safe_to_execute_tests: bool = False
    notes: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "scaffold_root": self.scaffold_root,
            "validation_status": self.validation_status,
            "execution_performed": self.execution_performed,
            "npm_performed": self.npm_performed,
            "npx_performed": self.npx_performed,
            "browser_performed": self.browser_performed,
            "external_calls_performed": self.external_calls_performed,
            "checks": [c.to_dict() for c in self.checks],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "safe_to_proceed_to_toolchain_validation": self.safe_to_proceed_to_toolchain_validation,
            "safe_to_execute_tests": self.safe_to_execute_tests,
            "notes": list(self.notes),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScaffoldValidationReport:
        known = {
            "project_id", "scaffold_root", "validation_status",
            "execution_performed", "npm_performed", "npx_performed",
            "browser_performed", "external_calls_performed",
            "blockers", "warnings",
            "safe_to_proceed_to_toolchain_validation", "safe_to_execute_tests",
            "notes", "created_at",
        }
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["checks"] = [
            ScaffoldValidationCheck.from_dict(c) if isinstance(c, dict) else c
            for c in data.get("checks", [])
        ]
        return cls(**kwargs)


@dataclass
class ToolchainValidationPlan(SchemaMixin):
    project_id: str = ""
    scaffold_root: str = ""
    proposed_commands: List[str] = field(default_factory=list)
    approval_required: bool = True
    network_access_required: bool = True
    browser_execution_required: bool = False
    safe_without_approval: bool = False
    notes: List[str] = field(default_factory=list)

"""Toolchain validation schemas — Phase 3C.

Approval-gated local toolchain validation (npm install, typecheck, discovery).

SAFETY DEFAULTS:
- approval_required = True
- approved = False
- npm_install_performed = False
- typecheck_performed = False
- playwright_discovery_performed = False
- browser_execution_performed = False
- external_url_used = False
- credentials_used = False
- safe_to_proceed_to_approved_execution = False
- safe_to_execute_tests = False
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.schemas.base import SchemaMixin

TOOLCHAIN_STATUSES = {"pass", "fail", "blocked", "skipped", "warning", "unknown"}
COMMAND_STATUSES = {"pass", "fail", "skipped", "blocked"}

ALLOWED_COMMAND_CATEGORIES = {"dependency_install", "typecheck", "discovery"}
BLOCKED_COMMAND_CATEGORIES = {"test_execution", "browser_launch", "external_call", "install_browsers"}


@dataclass
class ToolchainCommandResult(SchemaMixin):
    """Result of a single toolchain command execution or skip."""
    id: str = ""
    command: str = ""
    cwd: str = ""
    exit_code: Optional[int] = None
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    status: str = "skipped"
    duration_seconds: Optional[float] = None
    executed: bool = False
    skipped_reason: Optional[str] = None
    safety_notes: List[str] = field(default_factory=list)


@dataclass
class ToolchainApprovalRecord(SchemaMixin):
    """Records the approval decision for toolchain validation."""
    project_id: str = ""
    scaffold_root: str = ""
    approved: bool = False
    approval_source: str = ""
    approval_reason: str = ""
    approved_commands: List[str] = field(default_factory=list)
    denied_commands: List[str] = field(default_factory=list)
    safety_constraints: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


@dataclass
class ToolchainValidationReport(SchemaMixin):
    """Full report of Phase 3C local toolchain validation."""
    project_id: str = ""
    scaffold_root: str = ""
    validation_status: str = "unknown"
    approval_required: bool = True
    approved: bool = False
    npm_install_performed: bool = False
    typecheck_performed: bool = False
    playwright_discovery_performed: bool = False
    browser_execution_performed: bool = False
    external_url_used: bool = False
    credentials_used: bool = False
    commands: List[ToolchainCommandResult] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    safe_to_proceed_to_approved_execution: bool = False
    safe_to_execute_tests: bool = False
    notes: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        # Safety invariants: these four flags are hardcoded False in Phase 3C and must
        # never be rehydrated as True from deserialized data or caller construction.
        self.safe_to_execute_tests = False
        self.browser_execution_performed = False
        self.external_url_used = False
        self.credentials_used = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "scaffold_root": self.scaffold_root,
            "validation_status": self.validation_status,
            "approval_required": self.approval_required,
            "approved": self.approved,
            "npm_install_performed": self.npm_install_performed,
            "typecheck_performed": self.typecheck_performed,
            "playwright_discovery_performed": self.playwright_discovery_performed,
            "browser_execution_performed": self.browser_execution_performed,
            "external_url_used": self.external_url_used,
            "credentials_used": self.credentials_used,
            "commands": [c.to_dict() for c in self.commands],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "safe_to_proceed_to_approved_execution": self.safe_to_proceed_to_approved_execution,
            "safe_to_execute_tests": self.safe_to_execute_tests,
            "notes": list(self.notes),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolchainValidationReport:
        known = {
            "project_id", "scaffold_root", "validation_status",
            "approval_required", "approved",
            "npm_install_performed", "typecheck_performed",
            "playwright_discovery_performed", "browser_execution_performed",
            "external_url_used", "credentials_used",
            "blockers", "warnings",
            "safe_to_proceed_to_approved_execution", "safe_to_execute_tests",
            "notes", "created_at",
        }
        kwargs = {k: v for k, v in data.items() if k in known}
        kwargs["commands"] = [
            ToolchainCommandResult.from_dict(c) if isinstance(c, dict) else c
            for c in data.get("commands", [])
        ]
        return cls(**kwargs)

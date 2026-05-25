"""Browser execution schemas — Phase 4D.

SAFETY DEFAULTS:
- approved = False
- browser_execution_performed = False
- playwright_test_execution_performed = False
- production_target_used = False
- credentials_used = False
- external_calls_performed = False
- destructive_actions_performed = False
- client_delivery_created = False
- safe_to_deliver = False
- approved_for_client_delivery = False
- evidence internal_only = True / client_visible = False

__post_init__ and from_dict guards force delivery flags False.
browser_execution_performed and playwright_test_execution_performed may
become True only when approved execution actually ran (not forced False).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.schemas.base import SchemaMixin

EXECUTION_STATUSES = {"blocked", "skipped", "partial", "complete", "error"}
COMMAND_STATUSES = {"pass", "fail", "skipped", "blocked"}
EVIDENCE_TYPES = {
    "command_log", "playwright_report", "test_results",
    "screenshot", "trace", "video", "execution_summary", "unknown",
}
TARGET_CATEGORIES = {
    "local", "localhost", "public_demo_target",
    "real_public_readonly", "high_risk_marketplace_readonly",
    "production", "task_source", "unknown",
}
COMMAND_MODES = {"none", "list", "smoke", "readonly_smoke"}


@dataclass
class BrowserExecutionApproval(SchemaMixin):
    """Records the approval granted for a browser execution session."""
    project_id: str = ""
    approved: bool = False
    approval_source: str = ""
    approval_scope: str = ""
    approved_target_category: str = ""
    approved_target_url: Optional[str] = None
    demo_profile: Optional[str] = None
    readonly_profile: Optional[str] = None
    approved_commands: List[str] = field(default_factory=list)
    denied_commands: List[str] = field(default_factory=list)
    safety_constraints: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    notes: List[str] = field(default_factory=list)


@dataclass
class BrowserExecutionCommand(SchemaMixin):
    """A single command attempted during browser execution."""
    id: str = ""
    command: str = ""
    cwd: str = ""
    status: str = "skipped"
    exit_code: Optional[int] = None
    duration_seconds: Optional[float] = None
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    executed: bool = False
    skipped_reason: Optional[str] = None
    safety_notes: List[str] = field(default_factory=list)


@dataclass
class BrowserExecutionEvidence(SchemaMixin):
    """Reference to a piece of evidence collected during browser execution."""
    id: str = ""
    evidence_type: str = "unknown"
    path: str = ""
    title: str = ""
    description: str = ""
    internal_only: bool = True
    client_visible: bool = False
    requires_redaction: bool = True
    redacted: bool = False
    notes: List[str] = field(default_factory=list)


@dataclass
class BrowserExecutionReport(SchemaMixin):
    """Full report of a controlled browser execution session."""
    project_id: str = ""
    scaffold_root: str = ""
    execution_status: str = "blocked"
    approval_required: bool = True
    approved: bool = False
    target_category: str = "unknown"
    target_url: Optional[str] = None
    demo_profile: Optional[str] = None
    readonly_profile: Optional[str] = None
    command_mode: str = "none"
    browser_execution_performed: bool = False
    playwright_test_execution_performed: bool = False
    production_target_used: bool = False
    public_readonly_target_used: bool = False
    credentials_used: bool = False
    external_calls_performed: bool = False
    destructive_actions_performed: bool = False
    client_delivery_created: bool = False
    commands: List[BrowserExecutionCommand] = field(default_factory=list)
    evidence: List[BrowserExecutionEvidence] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    safe_to_deliver: bool = False
    approved_for_client_delivery: bool = False
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Delivery and credential flags are hardcoded False.
        # browser_execution_performed / playwright_test_execution_performed /
        # public_readonly_target_used are NOT forced here — they reflect real
        # execution state and may become True when approved execution runs.
        self.safe_to_deliver = False
        self.approved_for_client_delivery = False
        self.client_delivery_created = False
        self.credentials_used = False
        self.destructive_actions_performed = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "scaffold_root": self.scaffold_root,
            "execution_status": self.execution_status,
            "approval_required": self.approval_required,
            "approved": self.approved,
            "target_category": self.target_category,
            "target_url": self.target_url,
            "demo_profile": self.demo_profile,
            "readonly_profile": self.readonly_profile,
            "command_mode": self.command_mode,
            "browser_execution_performed": self.browser_execution_performed,
            "playwright_test_execution_performed": self.playwright_test_execution_performed,
            "production_target_used": self.production_target_used,
            "public_readonly_target_used": self.public_readonly_target_used,
            "credentials_used": self.credentials_used,
            "external_calls_performed": self.external_calls_performed,
            "destructive_actions_performed": self.destructive_actions_performed,
            "client_delivery_created": self.client_delivery_created,
            "commands": [c.to_dict() for c in self.commands],
            "evidence": [e.to_dict() for e in self.evidence],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "safe_to_deliver": self.safe_to_deliver,
            "approved_for_client_delivery": self.approved_for_client_delivery,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> BrowserExecutionReport:
        scalar_keys = {
            "project_id", "scaffold_root", "execution_status",
            "approval_required", "approved", "target_category",
            "target_url", "demo_profile", "readonly_profile", "command_mode",
            "browser_execution_performed", "playwright_test_execution_performed",
            "production_target_used", "public_readonly_target_used",
            "external_calls_performed",
            "blockers", "warnings", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in scalar_keys}
        kwargs["commands"] = [
            BrowserExecutionCommand.from_dict(c) if isinstance(c, dict) else c
            for c in data.get("commands", [])
        ]
        kwargs["evidence"] = [
            BrowserExecutionEvidence.from_dict(e) if isinstance(e, dict) else e
            for e in data.get("evidence", [])
        ]
        # Safety: delivery flags cannot be rehydrated from disk.
        kwargs["safe_to_deliver"] = False
        kwargs["approved_for_client_delivery"] = False
        kwargs["client_delivery_created"] = False
        kwargs["credentials_used"] = False
        kwargs["destructive_actions_performed"] = False
        return cls(**kwargs)

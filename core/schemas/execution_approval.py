"""Execution approval and readiness schemas — Phase 4A.

SAFETY DEFAULTS:
- approved_for_execution = False
- approved_for_browser_execution = False
- approved_for_external_calls = False
- approved_for_client_delivery = False
- evidence_plan_ready = False
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.schemas.base import SchemaMixin

READINESS_STATUSES = {"not_ready", "partial", "ready_for_review", "blocked"}
APPROVAL_CATEGORIES = {
    "target_url", "credentials", "test_account", "production_readonly",
    "payment_sandbox", "destructive_actions", "external_integrations",
    "browser_execution", "evidence_collection",
}
RISK_LEVELS = {"critical", "high", "medium", "low"}


@dataclass
class ExecutionApprovalRequirement(SchemaMixin):
    """A single approval requirement that must be satisfied before execution."""
    id: str = ""
    name: str = ""
    category: str = ""
    required: bool = True
    approved: bool = False
    approval_source: Optional[str] = None
    rationale: str = ""
    risk_level: str = "high"
    blocks_execution: bool = True
    notes: List[str] = field(default_factory=list)


@dataclass
class ExecutionApprovalChecklist(SchemaMixin):
    """Aggregated approval checklist — all items must be satisfied before execution."""
    project_id: str = ""
    target_environment: str = ""
    target_url_approved: bool = False
    credentials_approved: bool = False
    test_account_confirmed: bool = False
    production_readonly_approved: bool = False
    payment_sandbox_confirmed: bool = False
    destructive_actions_blocked: bool = True
    external_integrations_blocked: bool = True
    browser_execution_approved: bool = False
    evidence_collection_approved: bool = False
    requirements: List[ExecutionApprovalRequirement] = field(default_factory=list)
    approved_for_execution: bool = False
    approved_for_browser_execution: bool = False
    approved_for_client_delivery: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "target_environment": self.target_environment,
            "target_url_approved": self.target_url_approved,
            "credentials_approved": self.credentials_approved,
            "test_account_confirmed": self.test_account_confirmed,
            "production_readonly_approved": self.production_readonly_approved,
            "payment_sandbox_confirmed": self.payment_sandbox_confirmed,
            "destructive_actions_blocked": self.destructive_actions_blocked,
            "external_integrations_blocked": self.external_integrations_blocked,
            "browser_execution_approved": self.browser_execution_approved,
            "evidence_collection_approved": self.evidence_collection_approved,
            "requirements": [r.to_dict() for r in self.requirements],
            "approved_for_execution": self.approved_for_execution,
            "approved_for_browser_execution": self.approved_for_browser_execution,
            "approved_for_client_delivery": self.approved_for_client_delivery,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionApprovalChecklist:
        known = {
            "project_id", "target_environment", "target_url_approved",
            "credentials_approved", "test_account_confirmed",
            "production_readonly_approved", "payment_sandbox_confirmed",
            "destructive_actions_blocked", "external_integrations_blocked",
            "browser_execution_approved", "evidence_collection_approved",
            "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["requirements"] = [
            ExecutionApprovalRequirement.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("requirements", [])
        ]
        # Safety: execution and delivery approval cannot be rehydrated from disk.
        kwargs["approved_for_execution"] = False
        kwargs["approved_for_browser_execution"] = False
        kwargs["approved_for_client_delivery"] = False
        return cls(**kwargs)


@dataclass
class ExecutionReadinessReport(SchemaMixin):
    """Summary of execution readiness across all approval dimensions."""
    project_id: str = ""
    readiness_status: str = "not_ready"
    approved_for_execution: bool = False
    approved_for_browser_execution: bool = False
    approved_for_target_url: bool = False
    approved_for_credentials: bool = False
    approved_for_external_calls: bool = False
    approved_for_client_delivery: bool = False
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    required_approvals: List[str] = field(default_factory=list)
    safe_next_steps: List[str] = field(default_factory=list)
    evidence_plan_ready: bool = False
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionReadinessReport:
        known = {
            "project_id", "readiness_status",
            "blockers", "warnings", "required_approvals", "safe_next_steps",
            "evidence_plan_ready", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        # Safety: approval flags cannot be rehydrated from disk.
        kwargs["approved_for_execution"] = False
        kwargs["approved_for_browser_execution"] = False
        kwargs["approved_for_target_url"] = False
        kwargs["approved_for_credentials"] = False
        kwargs["approved_for_external_calls"] = False
        kwargs["approved_for_client_delivery"] = False
        return cls(**kwargs)

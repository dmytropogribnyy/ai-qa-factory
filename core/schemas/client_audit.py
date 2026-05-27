"""Phase 6.1/6.2 -- Client audit workflow schemas."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from core.schemas.finding import Finding


class ClientAuditMode(str, Enum):
    SAFE_AUDIT = "safe_audit"
    API_ONLY = "api_only"
    FRONTEND_READONLY = "frontend_readonly"
    DELIVERY_ONLY = "delivery_only"


@dataclass
class ClientAuditInputs:
    """Inputs for a client audit workflow run.

    Safety invariants (raw_secrets_allowed, destructive_actions_allowed,
    production_write_allowed, auto_send_allowed, client_delivery_auto_approved,
    human_review_required, approval_required_for_execution) are always enforced
    in __post_init__ regardless of what the caller sets.
    """

    project_id: str
    mode: ClientAuditMode = ClientAuditMode.SAFE_AUDIT
    target_url: str = ""
    spec_file: str = ""
    postman_collection: str = ""
    task_source_report_path: str = ""
    scaffold_root: str = ""
    outputs_root: str = "outputs"
    write_files: bool = True
    approve_public_readonly_execution: bool = False
    approve_browser_execution: bool = False
    # Safety invariants -- always reset by __post_init__
    raw_secrets_allowed: bool = False
    destructive_actions_allowed: bool = False
    production_write_allowed: bool = False
    auto_send_allowed: bool = False
    client_delivery_auto_approved: bool = False
    human_review_required: bool = True
    approval_required_for_execution: bool = True

    def __post_init__(self) -> None:
        self.raw_secrets_allowed = False
        self.destructive_actions_allowed = False
        self.production_write_allowed = False
        self.auto_send_allowed = False
        self.client_delivery_auto_approved = False
        self.human_review_required = True
        self.approval_required_for_execution = True

    @classmethod
    def from_dict(cls, data: dict) -> "ClientAuditInputs":
        return cls(
            project_id=data.get("project_id", ""),
            mode=ClientAuditMode(data.get("mode", "safe_audit")),
            target_url=data.get("target_url", ""),
            spec_file=data.get("spec_file", ""),
            postman_collection=data.get("postman_collection", ""),
            task_source_report_path=data.get("task_source_report_path", ""),
            scaffold_root=data.get("scaffold_root", ""),
            outputs_root=data.get("outputs_root", "outputs"),
            write_files=bool(data.get("write_files", True)),
            approve_public_readonly_execution=bool(
                data.get("approve_public_readonly_execution", False)
            ),
            approve_browser_execution=bool(data.get("approve_browser_execution", False)),
        )


@dataclass
class SkippedModule:
    name: str
    reason: str


@dataclass
class ClientAuditPlan:
    project_id: str
    mode: str
    detected_inputs: dict = field(default_factory=dict)
    enabled_modules: list[str] = field(default_factory=list)
    skipped_modules: list[SkippedModule] = field(default_factory=list)
    blocked_risky_actions: list[str] = field(default_factory=list)
    approval_required_steps: list[str] = field(default_factory=list)
    expected_artifact_paths: list[str] = field(default_factory=list)
    human_review_required: bool = True


@dataclass
class ModuleResult:
    name: str
    status: str
    artifacts: list[str] = field(default_factory=list)
    note: str = ""
    findings: list[Finding] = field(default_factory=list)


@dataclass
class ClientAuditResult:
    """Result of a completed client audit workflow run.

    Safety invariants (human_review_required, approved_for_client_delivery,
    raw_secrets_allowed, destructive_actions_allowed, production_write_allowed,
    auto_send_allowed, client_delivery_auto_approved) are always enforced in
    __post_init__ regardless of what the caller sets.
    """

    project_id: str
    mode: str
    status: str
    modules_executed: int = 0
    modules_planning_only: int = 0
    blocked_risky_actions: int = 0
    findings: int = 0  # total count (backward compat int)
    artifacts_root: str = ""
    delivery_dir: str = ""
    module_results: list[ModuleResult] = field(default_factory=list)
    # Phase 6.2: structured findings and risk matrix
    structured_findings: list[Finding] = field(default_factory=list)
    total_findings: int = 0
    findings_by_severity: dict = field(default_factory=dict)
    findings_by_category: dict = field(default_factory=dict)
    top_risks: list = field(default_factory=list)
    risk_summary: dict = field(default_factory=dict)
    # Safety invariants -- always reset by __post_init__
    human_review_required: bool = True
    approved_for_client_delivery: bool = False
    raw_secrets_allowed: bool = False
    destructive_actions_allowed: bool = False
    production_write_allowed: bool = False
    auto_send_allowed: bool = False
    client_delivery_auto_approved: bool = False

    def __post_init__(self) -> None:
        self.human_review_required = True
        self.approved_for_client_delivery = False
        self.raw_secrets_allowed = False
        self.destructive_actions_allowed = False
        self.production_write_allowed = False
        self.auto_send_allowed = False
        self.client_delivery_auto_approved = False

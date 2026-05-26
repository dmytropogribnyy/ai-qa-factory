"""Phase 5J — E2E Pipeline Runner schemas.

Orchestrates existing Phase runners in sequence:
  task_source → browser → api_smoke → google_auth → github_auth
  → mobile_viewport → visual_regression → db_smoke → qa_report

Each module is independently enabled/disabled. The pipeline aggregates
results from all enabled modules into a single PipelineRunReport.

Safety invariants (hardcoded in __post_init__ + from_dict):
- raw_secrets_allowed=False
- production_write_allowed=False
- client_delivery_allowed=False
- human_review_required=True
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.schemas.base import SchemaMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PIPELINE_MODULES = (
    "task_source",
    "browser",
    "api_smoke",
    "google_auth",
    "github_auth",
    "mobile_viewport",
    "visual_regression",
    "db_smoke",
    "qa_report",
)

PIPELINE_MODULE_STATUSES = ("pending", "complete", "failed", "blocked", "skipped")

PIPELINE_OVERALL_STATUSES = ("planned", "running", "complete", "partial", "failed", "blocked")

# Artifact directory suffix for each module (relative to outputs/<project_id>/)
PIPELINE_MODULE_ARTIFACT_DIRS: dict = {
    "task_source": "16_task_source",
    "browser": "07_execution",
    "api_smoke": "13_api_auth",
    "google_auth": "15_google_auth",
    "github_auth": "19_github_auth",
    "mobile_viewport": "17_mobile_viewport",
    "visual_regression": "18_visual_regression",
    "db_smoke": "21_db_smoke",
    "qa_report": "14_qa_report",
}

# CLI tool for each module
PIPELINE_MODULE_CLI_TOOLS: dict = {
    "task_source": "tools/run_task_source_fetch.py",
    "browser": "tools/run_browser_execution.py",
    "api_smoke": "tools/run_api_auth_smoke.py",
    "google_auth": "tools/run_google_auth_smoke.py",
    "github_auth": "tools/run_github_auth_smoke.py",
    "mobile_viewport": "tools/run_mobile_viewport_smoke.py",
    "visual_regression": "tools/run_visual_regression.py",
    "db_smoke": "tools/run_db_smoke.py",
    "qa_report": "tools/generate_qa_report.py",
}


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class PipelineModuleConfig(SchemaMixin):
    """Per-module runtime configuration for the E2E pipeline."""
    # task_source
    task_source_provider: str = ""
    task_source_token_env_var: str = ""
    task_source_project_id: str = ""
    # browser
    browser_target_url: str = ""
    browser_category: str = ""
    browser_approve: bool = False
    # api_smoke
    api_target_url: str = ""
    api_profile: str = ""
    api_approve: bool = False
    # google_auth
    google_auth_mode: str = "storage_state_reuse"
    google_storage_state_path: str = ""
    google_approve: bool = False
    google_dedicated_test_account_confirmed: bool = False
    # github_auth
    github_auth_mode: str = "storage_state_reuse"
    github_storage_state_path: str = ""
    github_approve: bool = False
    github_dedicated_test_account_confirmed: bool = False
    # mobile_viewport
    mobile_device: str = ""
    mobile_target_url: str = ""
    mobile_readonly_profile: str = ""
    mobile_approve: bool = False
    # visual_regression
    visual_target_url: str = ""
    visual_mode: str = "compare"
    visual_device: str = ""
    visual_approve: bool = False
    # db_smoke
    db_provider: str = ""
    db_url_env_var: str = ""
    db_table: str = ""
    db_approve: bool = False
    # qa_report (always runs last if enabled)
    qa_report_source_project_ids: List[str] = field(default_factory=list)


@dataclass
class PipelineModuleResult(SchemaMixin):
    """Result for a single pipeline module execution."""
    module_name: str = ""
    status: str = "pending"
    cli_tool: str = ""
    artifact_dir: str = ""
    exit_code: int = -1
    stdout_excerpt: str = ""
    duration_seconds: float = 0.0
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class PipelineRunPlan(SchemaMixin):
    """Execution plan produced before any modules run."""
    project_id: str = ""
    enabled_modules: List[str] = field(default_factory=list)
    blocked_modules: List[str] = field(default_factory=list)
    execution_order: List[str] = field(default_factory=list)
    planned_commands: List[str] = field(default_factory=list)
    approval_required: bool = True
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # Safety
    raw_secrets_allowed: bool = False
    production_write_allowed: bool = False
    client_delivery_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_secrets_allowed", False)
        object.__setattr__(self, "production_write_allowed", False)
        object.__setattr__(self, "client_delivery_allowed", False)
        object.__setattr__(self, "human_review_required", True)

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineRunPlan":
        obj = cls(
            project_id=str(data.get("project_id", "")),
            enabled_modules=list(data.get("enabled_modules", [])),
            blocked_modules=list(data.get("blocked_modules", [])),
            execution_order=list(data.get("execution_order", [])),
            planned_commands=list(data.get("planned_commands", [])),
            approval_required=bool(data.get("approval_required", True)),
            blockers=list(data.get("blockers", [])),
            notes=list(data.get("notes", [])),
        )
        object.__setattr__(obj, "raw_secrets_allowed", False)
        object.__setattr__(obj, "production_write_allowed", False)
        object.__setattr__(obj, "client_delivery_allowed", False)
        object.__setattr__(obj, "human_review_required", True)
        return obj


@dataclass
class PipelineRunReport(SchemaMixin):
    """Aggregate result of the full E2E pipeline run."""
    project_id: str = ""
    enabled_modules: List[str] = field(default_factory=list)
    execution_order: List[str] = field(default_factory=list)
    module_results: List[PipelineModuleResult] = field(default_factory=list)
    overall_status: str = "planned"
    total_duration_seconds: float = 0.0
    modules_complete: int = 0
    modules_failed: int = 0
    modules_blocked: int = 0
    modules_skipped: int = 0
    final_report_path: str = ""
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # Safety
    raw_secrets_allowed: bool = False
    production_write_allowed: bool = False
    client_delivery_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_secrets_allowed", False)
        object.__setattr__(self, "production_write_allowed", False)
        object.__setattr__(self, "client_delivery_allowed", False)
        object.__setattr__(self, "human_review_required", True)

    @classmethod
    def from_dict(cls, data: dict) -> "PipelineRunReport":
        results = [
            PipelineModuleResult(**r) if isinstance(r, dict) else r
            for r in data.get("module_results", [])
        ]
        obj = cls(
            project_id=str(data.get("project_id", "")),
            enabled_modules=list(data.get("enabled_modules", [])),
            execution_order=list(data.get("execution_order", [])),
            module_results=results,
            overall_status=str(data.get("overall_status", "planned")),
            total_duration_seconds=float(data.get("total_duration_seconds", 0.0)),
            modules_complete=int(data.get("modules_complete", 0)),
            modules_failed=int(data.get("modules_failed", 0)),
            modules_blocked=int(data.get("modules_blocked", 0)),
            modules_skipped=int(data.get("modules_skipped", 0)),
            final_report_path=str(data.get("final_report_path", "")),
            blockers=list(data.get("blockers", [])),
            notes=list(data.get("notes", [])),
        )
        object.__setattr__(obj, "raw_secrets_allowed", False)
        object.__setattr__(obj, "production_write_allowed", False)
        object.__setattr__(obj, "client_delivery_allowed", False)
        object.__setattr__(obj, "human_review_required", True)
        return obj

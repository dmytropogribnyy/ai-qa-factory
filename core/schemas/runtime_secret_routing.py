"""Runtime Secret Routing schemas — Phase 5AB.

SAFETY DEFAULTS (hardcoded, cannot be bypassed via constructor or from_dict):
- RuntimeSecretReference.raw_value_present=False       (ALWAYS)
- RuntimeSecretReference.value_materialized=False      (ALWAYS)
- RuntimeSecretReference.safe_to_persist=False         (ALWAYS)
- RuntimeSecretReference.safe_to_log=False             (ALWAYS)
- RuntimeSecretReference.safe_for_client_visibility=False (ALWAYS)
- TestAccountValidationResult.approved_for_execution_now=False (ALWAYS)
- DedicatedAuthSessionArtifact.internal_only=True      (ALWAYS)
- DedicatedAuthSessionArtifact.client_visible=False    (ALWAYS)
- DedicatedAuthSessionArtifact.requires_redaction=True (ALWAYS)
- DedicatedAuthSessionArtifact.approved_for_commit=False (ALWAYS)
- DedicatedAuthSessionArtifact.approved_for_client_view=False (ALWAYS)
- DedicatedAuthExecutionReport.raw_credentials_logged=False   (ALWAYS)
- DedicatedAuthExecutionReport.raw_credentials_serialized=False (ALWAYS)
- DedicatedAuthExecutionReport.personal_account_used=False    (ALWAYS)
- DedicatedAuthExecutionReport.production_account_used=False  (ALWAYS)
- DedicatedAuthExecutionReport.safe_to_deliver=False          (ALWAYS)
- DedicatedAuthExecutionReport.approved_for_client_delivery=False (ALWAYS)

No execution, no .env reading, no external calls in this module.
Phase 5AB: runtime secret routing and dedicated test-account auth execution (approval-gated).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.schemas.base import SchemaMixin

SECRET_TYPES = {
    "username",
    "password",
    "api_token",
    "oauth_client_secret",
    "session_cookie",
    "storage_state",
    "sandbox_key",
    "unknown",
}

SOURCE_ROUTES = {
    "runtime_env_reference",   # allowed now for dedicated auth
    "public_demo_profile",     # allowed now for demo lanes only
    "vault_reference_future",  # planned
    "client_secure_channel_future",  # planned
    "repo_file",               # blocked
    "chat_message",            # blocked
    "unknown",
}


# ---------------------------------------------------------------------------
# RuntimeSecretReference
# ---------------------------------------------------------------------------

@dataclass
class RuntimeSecretReference(SchemaMixin):
    """Reference to a runtime secret — never stores the raw value."""
    id: str = ""
    label: str = ""
    env_var_name: Optional[str] = None
    secret_type: str = "unknown"
    source_route: str = "unknown"
    raw_value_present: bool = False
    value_materialized: bool = False
    safe_to_persist: bool = False
    safe_to_log: bool = False
    safe_for_client_visibility: bool = False
    requires_redaction: bool = True
    approved_for_runtime_use: bool = False
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Raw values and materialisation are never safe to expose
        self.raw_value_present = False
        self.value_materialized = False
        self.safe_to_persist = False
        self.safe_to_log = False
        self.safe_for_client_visibility = False
        self.requires_redaction = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RuntimeSecretReference:
        from dataclasses import fields as dc_fields
        known = {f.name for f in dc_fields(cls)}
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["raw_value_present"] = False
        kwargs["value_materialized"] = False
        kwargs["safe_to_persist"] = False
        kwargs["safe_to_log"] = False
        kwargs["safe_for_client_visibility"] = False
        kwargs["requires_redaction"] = True
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# TestAccountIntakeRequest
# ---------------------------------------------------------------------------

@dataclass
class TestAccountIntakeRequest(SchemaMixin):
    """Describes a dedicated test-account configuration using env var references only."""
    project_id: str = ""
    target_url: Optional[str] = None
    target_category: str = ""
    scenario_lane: str = ""
    account_provider: str = ""
    account_type: str = ""
    username_env_var: Optional[str] = None
    password_env_var: Optional[str] = None
    token_env_var: Optional[str] = None
    requested_secret_types: List[str] = field(default_factory=list)
    dedicated_test_account_confirmed: bool = False
    personal_account_confirmed: bool = False
    production_account_confirmed: bool = False
    staging_environment_confirmed: bool = False
    client_scope_confirmed: bool = False
    notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# TestAccountValidationResult
# ---------------------------------------------------------------------------

@dataclass
class TestAccountValidationResult(SchemaMixin):
    """Result of validating a test-account intake request."""
    project_id: str = ""
    status: str = "pending"  # valid | invalid | blocked
    intake_request: Optional[TestAccountIntakeRequest] = None
    accepted_secret_references: List[RuntimeSecretReference] = field(default_factory=list)
    rejected_secret_references: List[RuntimeSecretReference] = field(default_factory=list)
    required_missing_items: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    safe_for_future_execution: bool = False
    approved_for_execution_now: bool = False
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Validation alone never grants execution approval
        self.approved_for_execution_now = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TestAccountValidationResult:
        scalar_keys = {
            "project_id", "status", "required_missing_items",
            "blockers", "warnings", "safe_for_future_execution", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in scalar_keys}
        kwargs["approved_for_execution_now"] = False
        req = data.get("intake_request")
        kwargs["intake_request"] = (
            TestAccountIntakeRequest.from_dict(req) if isinstance(req, dict) else None
        )
        kwargs["accepted_secret_references"] = [
            RuntimeSecretReference.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("accepted_secret_references", [])
        ]
        kwargs["rejected_secret_references"] = [
            RuntimeSecretReference.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("rejected_secret_references", [])
        ]
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# DedicatedAuthExecutionCommand
# ---------------------------------------------------------------------------

@dataclass
class DedicatedAuthExecutionCommand(SchemaMixin):
    """Record of a single Playwright command run during dedicated auth execution."""
    id: str = ""
    command: str = ""
    cwd: str = ""
    status: str = "pending"
    exit_code: Optional[int] = None
    duration_seconds: Optional[float] = None
    stdout_excerpt: str = ""
    stderr_excerpt: str = ""
    executed: bool = False
    skipped_reason: Optional[str] = None
    safety_notes: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# DedicatedAuthSessionArtifact
# ---------------------------------------------------------------------------

@dataclass
class DedicatedAuthSessionArtifact(SchemaMixin):
    """Reference to a session artifact produced during dedicated auth execution."""
    id: str = ""
    artifact_type: str = ""
    path: str = ""
    internal_only: bool = True
    client_visible: bool = False
    requires_redaction: bool = True
    approved_for_commit: bool = False
    approved_for_client_view: bool = False
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Session artifacts are always internal — cannot be bypassed
        self.internal_only = True
        self.client_visible = False
        self.requires_redaction = True
        self.approved_for_commit = False
        self.approved_for_client_view = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DedicatedAuthSessionArtifact:
        from dataclasses import fields as dc_fields
        known = {f.name for f in dc_fields(cls)}
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["internal_only"] = True
        kwargs["client_visible"] = False
        kwargs["requires_redaction"] = True
        kwargs["approved_for_commit"] = False
        kwargs["approved_for_client_view"] = False
        return cls(**kwargs)


# ---------------------------------------------------------------------------
# DedicatedAuthExecutionReport
# ---------------------------------------------------------------------------

@dataclass
class DedicatedAuthExecutionReport(SchemaMixin):
    """Full report for a dedicated test-account auth execution run."""
    project_id: str = ""
    scaffold_root: str = ""
    execution_status: str = "blocked"
    approval_required: bool = True
    approved: bool = False
    auth_execution_performed: bool = False
    browser_execution_performed: bool = False
    storage_state_created: bool = False
    credentials_used: bool = False
    raw_credentials_logged: bool = False
    raw_credentials_serialized: bool = False
    personal_account_used: bool = False
    production_account_used: bool = False
    target_url: Optional[str] = None
    scenario_lane: str = ""
    target_category: str = ""
    commands: List[DedicatedAuthExecutionCommand] = field(default_factory=list)
    session_artifacts: List[DedicatedAuthSessionArtifact] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    safe_to_deliver: bool = False
    approved_for_client_delivery: bool = False
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # These are never true regardless of what was passed
        self.raw_credentials_logged = False
        self.raw_credentials_serialized = False
        self.personal_account_used = False
        self.production_account_used = False
        self.safe_to_deliver = False
        self.approved_for_client_delivery = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> DedicatedAuthExecutionReport:
        scalar_keys = {
            "project_id", "scaffold_root", "execution_status",
            "approval_required", "approved",
            "auth_execution_performed", "browser_execution_performed",
            "storage_state_created", "credentials_used",
            "target_url", "scenario_lane", "target_category",
            "blockers", "warnings", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in scalar_keys}
        kwargs["raw_credentials_logged"] = False
        kwargs["raw_credentials_serialized"] = False
        kwargs["personal_account_used"] = False
        kwargs["production_account_used"] = False
        kwargs["safe_to_deliver"] = False
        kwargs["approved_for_client_delivery"] = False
        kwargs["commands"] = [
            DedicatedAuthExecutionCommand.from_dict(c) if isinstance(c, dict) else c
            for c in data.get("commands", [])
        ]
        kwargs["session_artifacts"] = [
            DedicatedAuthSessionArtifact.from_dict(a) if isinstance(a, dict) else a
            for a in data.get("session_artifacts", [])
        ]
        return cls(**kwargs)

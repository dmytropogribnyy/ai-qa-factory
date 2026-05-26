"""Auth execution schemas — Phase 4F.

SAFETY DEFAULTS (hardcoded, cannot be bypassed via constructor or from_dict):
- real_credentials_used=False      (ALWAYS — delivery gate)
- personal_account_used=False      (ALWAYS — delivery gate)
- production_account_used=False    (ALWAYS — delivery gate)
- safe_to_deliver=False            (ALWAYS — delivery gate)
- approved_for_client_delivery=False (ALWAYS — delivery gate)
- AuthCredentialProfile.personal_account=False    (ALWAYS)
- AuthCredentialProfile.production_account=False  (ALWAYS)
- AuthCredentialProfile.safe_to_store_in_repo=False (ALWAYS)
- AuthSessionArtifact.approved_for_commit=False   (ALWAYS)
- AuthSessionArtifact.approved_for_client_view=False (ALWAYS)
- AuthSessionArtifact.client_visible=False         (ALWAYS)

NOT forced — reflect real execution state when approved demo auth runs:
- auth_execution_performed      (may become True when approved demo auth ran)
- browser_execution_performed   (may become True when browser was launched)
- storage_state_created         (may become True when storageState generated)
- credentials_used              (may become True when public demo creds injected)

No real credentials are stored, logged, or committed by this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.schemas.base import SchemaMixin

CREDENTIAL_SOURCE_TYPES = {
    "public_demo_profile",
    "dedicated_test_account",
    "local_secret_reference",
    "env_reference",
    "vault_reference",
    "not_provided",
    "unknown",
}

AUTH_ARTIFACT_TYPES = {
    "storage_state",
    "auth_trace",
    "auth_screenshot",
    "auth_video",
    "auth_report",
    "command_log",
    "unknown",
}

AUTH_COMMAND_MODES = {"auth_smoke", "auth_setup"}


@dataclass
class AuthCredentialProfile(SchemaMixin):
    """Metadata about the credential profile used for demo auth execution.

    Never stores raw credential values — only labels, flags, and source classification.
    Credential values are injected into subprocess env only at execution time.
    """
    id: str = ""
    provider: str = ""
    target_category: str = ""
    target_url: str = ""
    credential_source_type: str = "unknown"
    username_label: str = ""
    password_label: str = ""
    public_demo_credentials: bool = False
    dedicated_test_account: bool = False
    personal_account: bool = False
    production_account: bool = False
    approved_for_demo_auth: bool = False
    approved_for_storage_state: bool = False
    safe_to_inject_runtime: bool = False
    safe_to_store_in_repo: bool = False
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Personal and production accounts are never allowed in Phase 4F
        self.personal_account = False
        self.production_account = False
        self.safe_to_store_in_repo = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuthCredentialProfile:
        from dataclasses import fields as dc_fields
        known = {f.name for f in dc_fields(cls)}
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["personal_account"] = False
        kwargs["production_account"] = False
        kwargs["safe_to_store_in_repo"] = False
        return cls(**kwargs)


@dataclass
class AuthExecutionCommand(SchemaMixin):
    """A single command attempted during demo auth execution."""
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
class AuthSessionArtifact(SchemaMixin):
    """Reference to an artifact produced during a demo auth session.

    Credential values must never appear in any artifact.
    internal_only=True, client_visible=False are the safe defaults.
    """
    id: str = ""
    artifact_type: str = "unknown"
    path: str = ""
    internal_only: bool = True
    client_visible: bool = False
    requires_redaction: bool = True
    approved_for_commit: bool = False
    approved_for_client_view: bool = False
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # These flags are hardcoded — human review required before changing
        self.approved_for_commit = False
        self.approved_for_client_view = False
        self.client_visible = False


@dataclass
class AuthExecutionReport(SchemaMixin):
    """Full report of a demo auth execution session."""
    project_id: str = ""
    scaffold_root: str = ""
    execution_status: str = "blocked"
    approval_required: bool = True
    approved: bool = False
    auth_execution_performed: bool = False
    browser_execution_performed: bool = False
    storage_state_created: bool = False
    credentials_used: bool = False
    real_credentials_used: bool = False
    personal_account_used: bool = False
    production_account_used: bool = False
    target_url: Optional[str] = None
    demo_profile: Optional[str] = None
    credential_profile: Optional[AuthCredentialProfile] = None
    commands: List[AuthExecutionCommand] = field(default_factory=list)
    session_artifacts: List[AuthSessionArtifact] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    safe_to_deliver: bool = False
    approved_for_client_delivery: bool = False
    notes: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        # Delivery and real-credential flags are hardcoded False.
        # auth_execution_performed, browser_execution_performed, storage_state_created,
        # credentials_used are NOT forced — they reflect real execution state.
        self.real_credentials_used = False
        self.personal_account_used = False
        self.production_account_used = False
        self.safe_to_deliver = False
        self.approved_for_client_delivery = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "scaffold_root": self.scaffold_root,
            "execution_status": self.execution_status,
            "approval_required": self.approval_required,
            "approved": self.approved,
            "auth_execution_performed": self.auth_execution_performed,
            "browser_execution_performed": self.browser_execution_performed,
            "storage_state_created": self.storage_state_created,
            "credentials_used": self.credentials_used,
            "real_credentials_used": self.real_credentials_used,
            "personal_account_used": self.personal_account_used,
            "production_account_used": self.production_account_used,
            "target_url": self.target_url,
            "demo_profile": self.demo_profile,
            "credential_profile": (
                self.credential_profile.to_dict() if self.credential_profile else None
            ),
            "commands": [c.to_dict() for c in self.commands],
            "session_artifacts": [a.to_dict() for a in self.session_artifacts],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "safe_to_deliver": self.safe_to_deliver,
            "approved_for_client_delivery": self.approved_for_client_delivery,
            "notes": list(self.notes),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AuthExecutionReport:
        scalar_keys = {
            "project_id", "scaffold_root", "execution_status",
            "approval_required", "approved",
            "auth_execution_performed", "browser_execution_performed",
            "storage_state_created", "credentials_used",
            "target_url", "demo_profile",
            "blockers", "warnings", "notes", "created_at",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in scalar_keys}
        # Nested reconstruction
        cp = data.get("credential_profile")
        kwargs["credential_profile"] = (
            AuthCredentialProfile.from_dict(cp) if isinstance(cp, dict) else None
        )
        kwargs["commands"] = [
            AuthExecutionCommand.from_dict(c) if isinstance(c, dict) else c
            for c in data.get("commands", [])
        ]
        kwargs["session_artifacts"] = [
            AuthSessionArtifact.from_dict(a) if isinstance(a, dict) else a
            for a in data.get("session_artifacts", [])
        ]
        # Safety: delivery and real-credential flags cannot be rehydrated to True
        kwargs["real_credentials_used"] = False
        kwargs["personal_account_used"] = False
        kwargs["production_account_used"] = False
        kwargs["safe_to_deliver"] = False
        kwargs["approved_for_client_delivery"] = False
        return cls(**kwargs)

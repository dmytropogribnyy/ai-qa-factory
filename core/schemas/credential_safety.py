"""Credential and test-account safety schemas — Phase 4E.

SAFETY DEFAULTS (hardcoded, cannot be bypassed via constructor or from_dict):
- allow_real_credentials=False
- allow_personal_accounts=False
- allow_production_accounts=False
- allow_repo_storage=False
- allow_logging=False
- allow_client_visible_credentials=False
- safe_for_auth_execution=False
- safe_for_client_visibility=False
- approved_for_commit=False
- AuthExecutionApproval.approved=False
- SandboxProfileClassification.blocked_in_current_phase=True

No real credentials are used, stored, read, or logged by this module.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.schemas.base import SchemaMixin

CREDENTIAL_TYPES_4E = {
    "username", "password", "api_token", "oauth", "session_cookie",
    "storage_state", "test_account", "payment_sandbox",
    "sandbox_buyer_account", "unknown",
}

SOURCE_TYPES_4E = {
    "not_provided", "placeholder", "fake_fixture", "public_demo_value",
    "local_secret_reference", "env_reference", "vault_reference",
    "user_supplied_runtime", "sandbox_portal", "unknown",
}

SANDBOX_CLASSIFICATIONS = {
    "public_demo",
    "official_payment_sandbox",
    "future_sandbox_integration",
    "blocked_production_retail",
    "blocked_personal_account",
    "blocked_task_source",
    "blocked_production_ecommerce",
    "unknown",
}


@dataclass
class CredentialReference(SchemaMixin):
    """A reference to a credential found or expected in the project scope.

    Never stores raw secret values — only metadata and source classification.
    """
    id: str = ""
    label: str = ""
    credential_type: str = "unknown"
    source_type: str = "not_provided"
    source_location: Optional[str] = None
    required: bool = False
    provided: bool = False
    approved_for_use: bool = False
    safe_to_store: bool = False
    safe_to_log: bool = False
    redaction_required: bool = True
    notes: List[str] = field(default_factory=list)


@dataclass
class TestAccountProfile(SchemaMixin):
    """Describes a test account and whether it is safe for use in execution."""
    id: str = ""
    label: str = ""
    account_type: str = "unknown"
    environment: str = "unknown"
    provider: str = "unknown"
    dedicated_test_account: bool = False
    personal_account: bool = False
    production_account: bool = False
    sandbox_account: bool = False
    approved_for_auth_execution: bool = False
    credentials_stored_in_repo: bool = False
    storage_state_allowed: bool = False
    notes: List[str] = field(default_factory=list)


@dataclass
class CredentialPolicy(SchemaMixin):
    """Project-level credential safety policy for Phase 4E inspection."""
    project_id: str = ""
    allow_real_credentials: bool = False
    allow_personal_accounts: bool = False
    allow_production_accounts: bool = False
    allow_repo_storage: bool = False
    allow_logging: bool = False
    allow_client_visible_credentials: bool = False
    allow_storage_state: bool = False
    allow_sandbox_credentials: bool = False
    require_dedicated_test_account: bool = True
    require_explicit_auth_approval: bool = True
    require_redaction: bool = True
    forbidden_sources: List[str] = field(default_factory=lambda: [
        "env_reference", "vault_reference", "user_supplied_runtime",
    ])
    allowed_sources: List[str] = field(default_factory=lambda: [
        "not_provided", "placeholder", "fake_fixture", "public_demo_value",
    ])
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.allow_real_credentials = False
        self.allow_personal_accounts = False
        self.allow_production_accounts = False
        self.allow_repo_storage = False
        self.allow_logging = False
        self.allow_client_visible_credentials = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CredentialPolicy:
        known = {
            "project_id", "allow_storage_state", "allow_sandbox_credentials",
            "require_dedicated_test_account", "require_explicit_auth_approval",
            "require_redaction", "forbidden_sources", "allowed_sources", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        # Safety: unsafe flags cannot be rehydrated from disk
        kwargs["allow_real_credentials"] = False
        kwargs["allow_personal_accounts"] = False
        kwargs["allow_production_accounts"] = False
        kwargs["allow_repo_storage"] = False
        kwargs["allow_logging"] = False
        kwargs["allow_client_visible_credentials"] = False
        return cls(**kwargs)


@dataclass
class CredentialSafetyReport(SchemaMixin):
    """Full credential safety inspection report for a project."""
    project_id: str = ""
    status: str = "blocked"
    credentials_detected: List[CredentialReference] = field(default_factory=list)
    test_accounts: List[TestAccountProfile] = field(default_factory=list)
    sandbox_profiles: List[SandboxProfileClassification] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    safe_for_auth_execution: bool = False
    safe_for_storage_state: bool = False
    safe_for_client_visibility: bool = False
    notes: List[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def __post_init__(self) -> None:
        self.safe_for_auth_execution = False
        self.safe_for_client_visibility = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "status": self.status,
            "credentials_detected": [c.to_dict() for c in self.credentials_detected],
            "test_accounts": [t.to_dict() for t in self.test_accounts],
            "sandbox_profiles": [s.to_dict() for s in self.sandbox_profiles],
            "blockers": list(self.blockers),
            "warnings": list(self.warnings),
            "safe_for_auth_execution": self.safe_for_auth_execution,
            "safe_for_storage_state": self.safe_for_storage_state,
            "safe_for_client_visibility": self.safe_for_client_visibility,
            "notes": list(self.notes),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CredentialSafetyReport:
        kwargs: Dict[str, Any] = {
            k: v for k, v in data.items()
            if k in {"project_id", "status", "blockers", "warnings", "notes",
                     "created_at", "safe_for_storage_state"}
        }
        kwargs["credentials_detected"] = [
            CredentialReference.from_dict(c) if isinstance(c, dict) else c
            for c in data.get("credentials_detected", [])
        ]
        kwargs["test_accounts"] = [
            TestAccountProfile.from_dict(t) if isinstance(t, dict) else t
            for t in data.get("test_accounts", [])
        ]
        kwargs["sandbox_profiles"] = [
            SandboxProfileClassification.from_dict(s) if isinstance(s, dict) else s
            for s in data.get("sandbox_profiles", [])
        ]
        # Safety: execution/visibility flags cannot be rehydrated
        kwargs["safe_for_auth_execution"] = False
        kwargs["safe_for_client_visibility"] = False
        return cls(**kwargs)


@dataclass
class StorageStatePolicy(SchemaMixin):
    """Policy governing Playwright storageState file handling."""
    project_id: str = ""
    storage_state_allowed: bool = False
    storage_state_path: str = ".auth/storageState.json"
    gitignored_required: bool = True
    internal_only: bool = True
    client_visible: bool = False
    requires_redaction: bool = True
    approved_for_use: bool = False
    approved_for_commit: bool = False
    notes: List[str] = field(default_factory=lambda: [
        "storageState files must never be committed to the repository.",
        "storageState is internal-only and requires explicit future phase approval.",
        "If found in repo: treat as a secret leak — rotate credentials immediately.",
    ])

    def __post_init__(self) -> None:
        self.approved_for_commit = False

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StorageStatePolicy:
        known = {
            "project_id", "storage_state_allowed", "storage_state_path",
            "gitignored_required", "internal_only", "client_visible",
            "requires_redaction", "approved_for_use", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["approved_for_commit"] = False
        return cls(**kwargs)


@dataclass
class AuthExecutionApproval(SchemaMixin):
    """Records (or blocks) approval for auth-gated execution in a future phase."""
    project_id: str = ""
    approved: bool = False
    approval_source: Optional[str] = None
    approval_scope: str = "none"
    provider: str = "unknown"
    target_environment: str = "unknown"
    dedicated_test_account_confirmed: bool = False
    real_credentials_allowed: bool = False
    personal_account_allowed: bool = False
    storage_state_allowed: bool = False
    evidence_internal_only: bool = True
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # Auth execution is never approved in Phase 4E
        self.approved = False
        self.real_credentials_allowed = False
        self.personal_account_allowed = False


@dataclass
class SandboxProfileClassification(SchemaMixin):
    """Classifies a sandbox/test-account profile for future auth/payment scope."""
    id: str = ""
    provider: str = "unknown"
    profile_type: str = "unknown"
    classification: str = "unknown"
    official_sandbox: bool = False
    production_retail_account: bool = False
    payment_sandbox: bool = False
    requires_merchant_setup: bool = False
    requires_dedicated_test_account: bool = True
    allowed_in_future_phase: bool = False
    blocked_in_current_phase: bool = True
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        # All sandbox profiles are blocked in Phase 4E
        self.blocked_in_current_phase = True

"""
Phase 5G — Google/OAuth Test Account Capability schemas.

Permissioned capability model:
- Personal Google accounts: always blocked.
- Production Google accounts: always blocked.
- Dedicated Google test accounts: allowed only with explicit approval flags.
- CAPTCHA bypass: always blocked.
- Anti-bot bypass: always blocked.
- Client delivery: always blocked.

Safety invariants (hardcoded in __post_init__ + from_dict):
- raw_secrets_allowed=False
- storage_state_content_read=False
- browser_profile_content_read=False
- captcha_bypass_allowed=False
- anti_bot_bypass_allowed=False
- client_delivery_allowed=False

Permissioned defaults (require explicit approval to enable):
- allowed_now=False
- approval_required=True
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from core.schemas.base import SchemaMixin


# Supported Google auth modes
GOOGLE_AUTH_MODES = (
    "manual_storage_state_capture",
    "storage_state_reuse",
    "cdp_attach",
    "dedicated_profile_context",
    "google_api_oauth_token_future",
    "google_service_account_future",
    "totp_test_account_future",
    "mock_oauth_provider_future",
)

# Modes implemented with real execution support in Phase 5G
GOOGLE_AUTH_MODES_EXECUTABLE_5G = (
    "manual_storage_state_capture",
    "storage_state_reuse",
)

# Modes that are planning/policy-only in Phase 5G (execution deferred)
GOOGLE_AUTH_MODES_PLANNING_ONLY_5G = (
    "cdp_attach",
    "dedicated_profile_context",
    "google_api_oauth_token_future",
    "google_service_account_future",
    "totp_test_account_future",
    "mock_oauth_provider_future",
)

# Target kinds — what the Google account is used to log into
GOOGLE_TARGET_KINDS = (
    "google_account_ui",            # Gmail/Drive UI on accounts.google.com
    "sign_in_with_google_oauth",    # Third-party site with "Sign in with Google"
    "google_api_endpoint",          # APIs requiring OAuth tokens
    "mock_oauth_endpoint",          # Mock OAuth provider for CI
)


@dataclass
class GoogleTestAccountProfile(SchemaMixin):
    """
    Identification of a dedicated Google test account.
    Stores only labels/references, never raw credential values.
    """
    account_email_label: str = ""          # display label only, e.g. "qa-test-001"
    account_type: str = "dedicated_test"   # "dedicated_test" | "personal" | "production"
    account_provider: str = "google"
    workspace_account: bool = False        # True if Google Workspace, False if consumer
    two_factor_enabled: Optional[bool] = None     # known state of 2FA on the account
    dedicated_test_account_confirmed: bool = False
    personal_account_confirmed: bool = False
    production_account_confirmed: bool = False
    google_test_account_confirmed: bool = False
    storage_state_path: str = ""
    notes: List[str] = field(default_factory=list)


@dataclass
class GoogleAuthModePolicy(SchemaMixin):
    """
    Policy decision for a single Google auth mode.
    Says whether the mode is allowed for this request and what approvals are required.
    """
    auth_mode: str = ""
    allowed_now: bool = False
    approval_required: bool = True
    required_approval_flags: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class GoogleStorageStatePolicy(SchemaMixin):
    """
    Policy for handling Google storageState files.
    storageState content is sensitive and must never be read/printed/scanned as text.
    Only path and metadata are recorded.
    """
    project_id: str = ""
    storage_state_path: str = ""           # path only, never content
    expected_directory: str = ""           # required internal directory
    internal_only: bool = True
    approved_for_commit: bool = False
    client_visible: bool = False
    storage_state_content_read: bool = False
    storage_state_present: bool = False    # path existence check only
    storage_state_size_bytes: int = 0      # size check only, content not read
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.internal_only = True
        self.approved_for_commit = False
        self.client_visible = False
        self.storage_state_content_read = False

    @classmethod
    def from_dict(cls, data: dict) -> "GoogleStorageStatePolicy":
        obj = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        obj.internal_only = True
        obj.approved_for_commit = False
        obj.client_visible = False
        obj.storage_state_content_read = False
        return obj


@dataclass
class GoogleAuthCapability(SchemaMixin):
    """
    Top-level capability plan: which Google modes are permitted under what approvals
    for a given project. This is planning/policy, not execution.
    """
    project_id: str = ""
    capability_type: str = "google_oauth_test_account_capability"
    account_profile: Optional[GoogleTestAccountProfile] = None
    mode_policies: List[GoogleAuthModePolicy] = field(default_factory=list)
    storage_state_policy: Optional[GoogleStorageStatePolicy] = None

    # Hardcoded safety invariants
    raw_secrets_allowed: bool = False
    storage_state_content_read: bool = False
    browser_profile_content_read: bool = False
    captcha_bypass_allowed: bool = False
    anti_bot_bypass_allowed: bool = False
    client_delivery_allowed: bool = False

    # Always-blocked URL/account categories acknowledged in plan
    personal_account_always_blocked: bool = True
    production_account_always_blocked: bool = True
    stealth_live_login_as_core_path: bool = False

    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.raw_secrets_allowed = False
        self.storage_state_content_read = False
        self.browser_profile_content_read = False
        self.captcha_bypass_allowed = False
        self.anti_bot_bypass_allowed = False
        self.client_delivery_allowed = False
        self.personal_account_always_blocked = True
        self.production_account_always_blocked = True
        self.stealth_live_login_as_core_path = False

    @classmethod
    def from_dict(cls, data: dict) -> "GoogleAuthCapability":
        obj = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        obj.raw_secrets_allowed = False
        obj.storage_state_content_read = False
        obj.browser_profile_content_read = False
        obj.captcha_bypass_allowed = False
        obj.anti_bot_bypass_allowed = False
        obj.client_delivery_allowed = False
        obj.personal_account_always_blocked = True
        obj.production_account_always_blocked = True
        obj.stealth_live_login_as_core_path = False
        return obj


@dataclass
class GoogleAuthExecutionDecision(SchemaMixin):
    """
    Per-request decision: should this specific Google auth attempt run now?
    Combines target URL + auth mode + account profile + approval flags into
    a single allow/block verdict with the reasons.
    """
    project_id: str = ""
    target_url: str = ""
    target_kind: str = ""
    auth_mode: str = ""
    account_email_label: str = ""

    # Approval gate state for this request
    approve_google_test_account: bool = False
    google_test_account_confirmed: bool = False
    dedicated_test_account_confirmed: bool = False
    personal_account_confirmed: bool = False
    production_account_confirmed: bool = False

    # Resource references (paths/labels only, never raw values)
    storage_state_path: str = ""
    cdp_port: Optional[int] = None
    user_data_dir: str = ""
    api_token_env_var: str = ""
    service_account_reference: str = ""
    totp_seed_env_var: str = ""

    # Decision
    allowed_now: bool = False
    approval_required: bool = True
    required_approval_flags: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    # Hardcoded invariants
    raw_secrets_allowed: bool = False
    storage_state_content_read: bool = False
    browser_profile_content_read: bool = False
    captcha_bypass_allowed: bool = False
    anti_bot_bypass_allowed: bool = False
    client_delivery_allowed: bool = False

    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.raw_secrets_allowed = False
        self.storage_state_content_read = False
        self.browser_profile_content_read = False
        self.captcha_bypass_allowed = False
        self.anti_bot_bypass_allowed = False
        self.client_delivery_allowed = False

    @classmethod
    def from_dict(cls, data: dict) -> "GoogleAuthExecutionDecision":
        obj = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        obj.raw_secrets_allowed = False
        obj.storage_state_content_read = False
        obj.browser_profile_content_read = False
        obj.captcha_bypass_allowed = False
        obj.anti_bot_bypass_allowed = False
        obj.client_delivery_allowed = False
        return obj


@dataclass
class GoogleAuthEvidenceReport(SchemaMixin):
    """
    Evidence report for an executed Google auth flow (or planned-only flow).
    Contains commands attempted, results, safety boundary. Never contains
    raw cookies, tokens, account passwords, or storageState content.
    """
    project_id: str = ""
    report_type: str = "google_auth_evidence_report"
    auth_mode: str = ""
    target_url: str = ""
    target_kind: str = ""
    account_email_label: str = ""

    # Execution state
    execution_performed: bool = False
    storage_state_captured: bool = False
    storage_state_path: str = ""              # path only
    storage_state_present_after_run: bool = False
    storage_state_size_bytes: int = 0
    smoke_commands: List[str] = field(default_factory=list)  # commands attempted
    smoke_results: List[str] = field(default_factory=list)   # results, no raw data
    duration_seconds: float = 0.0

    # Safety boundary (all hardcoded)
    raw_credentials_logged: bool = False
    raw_credentials_serialized: bool = False
    cookies_logged: bool = False
    tokens_logged: bool = False
    storage_state_content_read: bool = False
    browser_profile_content_read: bool = False
    captcha_bypass_attempted: bool = False
    anti_bot_bypass_attempted: bool = False
    personal_account_used: bool = False
    production_account_used: bool = False
    safe_to_deliver: bool = False
    approved_for_client_delivery: bool = False
    client_visible: bool = False
    internal_only: bool = True
    human_review_required: bool = True

    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.raw_credentials_logged = False
        self.raw_credentials_serialized = False
        self.cookies_logged = False
        self.tokens_logged = False
        self.storage_state_content_read = False
        self.browser_profile_content_read = False
        self.captcha_bypass_attempted = False
        self.anti_bot_bypass_attempted = False
        self.personal_account_used = False
        self.production_account_used = False
        self.safe_to_deliver = False
        self.approved_for_client_delivery = False
        self.client_visible = False
        self.internal_only = True
        self.human_review_required = True

    @classmethod
    def from_dict(cls, data: dict) -> "GoogleAuthEvidenceReport":
        obj = cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})
        obj.raw_credentials_logged = False
        obj.raw_credentials_serialized = False
        obj.cookies_logged = False
        obj.tokens_logged = False
        obj.storage_state_content_read = False
        obj.browser_profile_content_read = False
        obj.captcha_bypass_attempted = False
        obj.anti_bot_bypass_attempted = False
        obj.personal_account_used = False
        obj.production_account_used = False
        obj.safe_to_deliver = False
        obj.approved_for_client_delivery = False
        obj.client_visible = False
        obj.internal_only = True
        obj.human_review_required = True
        return obj

"""
Phase 5I — GitHub OAuth / Test Account Capability schemas.

Permissioned capability model (mirrors Phase 5G Google auth):
- Personal GitHub accounts: always blocked.
- Production org accounts: always blocked.
- Dedicated GitHub test accounts: allowed only with explicit approval flags.
- CAPTCHA bypass: always blocked.
- Raw secrets in CLI args: always blocked.

Safety invariants (hardcoded in __post_init__ + from_dict):
- personal_account_always_blocked=True
- production_account_always_blocked=True
- captcha_bypass_allowed=False
- raw_secrets_allowed=False
- storage_state_content_read=False
- client_delivery_allowed=False
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from core.schemas.base import SchemaMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

GITHUB_AUTH_MODES = (
    "manual_storage_state_capture",    # user logs in manually; system saves storageState
    "storage_state_reuse",             # headless smoke reusing saved storageState
    "cdp_attach",                      # attach to already-running Chrome via CDP
    "dedicated_profile_context",       # launch Chromium with persistent user-data-dir
    "github_api_token_future",         # API token auth — planning only
    "github_app_future",               # GitHub App auth — planning only
)

GITHUB_AUTH_MODES_EXECUTABLE_5I = (
    "manual_storage_state_capture",
    "storage_state_reuse",
)

GITHUB_AUTH_MODES_PLANNING_ONLY_5I = (
    "cdp_attach",               # executable in Phase 5H for Google — GitHub deferred
    "dedicated_profile_context",
    "github_api_token_future",
    "github_app_future",
)

GITHUB_TARGET_KINDS = (
    "github_login_ui",           # github.com login page
    "github_protected_resource", # github.com page requiring auth
    "github_api_endpoint",       # api.github.com — future
)

# Allowed GitHub URL prefixes for smoke targets
GITHUB_ALLOWED_URL_PREFIXES = (
    "https://github.com",
    "https://gist.github.com",
)

# Always-blocked GitHub URL patterns (even within approved profiles)
GITHUB_BLOCKED_URL_PATTERNS = (
    "/settings/",
    "/admin/",
    "/orgs/",
    "/enterprises/",
    "/billing/",
    "/security/",
    "/new",        # creating repos
    "/delete",
    "/fork",
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

@dataclass
class GitHubTestAccountProfile(SchemaMixin):
    """Identification of a dedicated GitHub test account (label only, never raw credentials)."""
    account_label: str = ""          # e.g. "qa_bot_github"
    target_kind: str = ""            # from GITHUB_TARGET_KINDS
    storage_state_path: str = ""     # path reference (metadata only; content never read)
    is_dedicated_test_account: bool = False
    is_personal_account: bool = False   # hardcoded False
    is_production_account: bool = False # hardcoded False

    def __post_init__(self) -> None:
        object.__setattr__(self, "is_personal_account", False)
        object.__setattr__(self, "is_production_account", False)

    @classmethod
    def from_dict(cls, data: dict) -> "GitHubTestAccountProfile":
        obj = cls(
            account_label=str(data.get("account_label", "")),
            target_kind=str(data.get("target_kind", "")),
            storage_state_path=str(data.get("storage_state_path", "")),
            is_dedicated_test_account=bool(data.get("is_dedicated_test_account", False)),
        )
        object.__setattr__(obj, "is_personal_account", False)
        object.__setattr__(obj, "is_production_account", False)
        return obj


@dataclass
class GitHubAuthModePolicy(SchemaMixin):
    """Policy decision for a single GitHub auth mode."""
    mode: str = ""
    allowed_now: bool = False
    approval_required: bool = True
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict) -> "GitHubAuthModePolicy":
        return cls(
            mode=str(data.get("mode", "")),
            allowed_now=bool(data.get("allowed_now", False)),
            approval_required=bool(data.get("approval_required", True)),
            blockers=list(data.get("blockers", [])),
            notes=list(data.get("notes", [])),
        )


@dataclass
class GitHubStorageStatePolicy(SchemaMixin):
    """Policy for GitHub storageState files (path/metadata only — content never read)."""
    storage_state_path: str = ""
    path_exists: bool = False
    file_size_bytes: int = 0
    internal_only: bool = True
    approved_for_commit: bool = False
    client_visible: bool = False
    storage_state_content_read: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "internal_only", True)
        object.__setattr__(self, "approved_for_commit", False)
        object.__setattr__(self, "client_visible", False)
        object.__setattr__(self, "storage_state_content_read", False)

    @classmethod
    def from_dict(cls, data: dict) -> "GitHubStorageStatePolicy":
        obj = cls(
            storage_state_path=str(data.get("storage_state_path", "")),
            path_exists=bool(data.get("path_exists", False)),
            file_size_bytes=int(data.get("file_size_bytes", 0)),
        )
        object.__setattr__(obj, "internal_only", True)
        object.__setattr__(obj, "approved_for_commit", False)
        object.__setattr__(obj, "client_visible", False)
        object.__setattr__(obj, "storage_state_content_read", False)
        return obj


@dataclass
class GitHubAuthCapability(SchemaMixin):
    """Top-level capability plan covering all GitHub auth modes."""
    project_id: str = ""
    account_profile: Optional[GitHubTestAccountProfile] = None
    mode_policies: List[GitHubAuthModePolicy] = field(default_factory=list)
    storage_state_policy: Optional[GitHubStorageStatePolicy] = None
    executable_modes: List[str] = field(default_factory=list)
    planning_only_modes: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    # Hardcoded safety invariants
    personal_account_always_blocked: bool = True
    production_account_always_blocked: bool = True
    captcha_bypass_allowed: bool = False
    raw_secrets_allowed: bool = False
    storage_state_content_read: bool = False
    client_delivery_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "personal_account_always_blocked", True)
        object.__setattr__(self, "production_account_always_blocked", True)
        object.__setattr__(self, "captcha_bypass_allowed", False)
        object.__setattr__(self, "raw_secrets_allowed", False)
        object.__setattr__(self, "storage_state_content_read", False)
        object.__setattr__(self, "client_delivery_allowed", False)

    @classmethod
    def from_dict(cls, data: dict) -> "GitHubAuthCapability":
        obj = cls(
            project_id=str(data.get("project_id", "")),
            executable_modes=list(data.get("executable_modes", [])),
            planning_only_modes=list(data.get("planning_only_modes", [])),
            blockers=list(data.get("blockers", [])),
            notes=list(data.get("notes", [])),
        )
        object.__setattr__(obj, "personal_account_always_blocked", True)
        object.__setattr__(obj, "production_account_always_blocked", True)
        object.__setattr__(obj, "captcha_bypass_allowed", False)
        object.__setattr__(obj, "raw_secrets_allowed", False)
        object.__setattr__(obj, "storage_state_content_read", False)
        object.__setattr__(obj, "client_delivery_allowed", False)
        return obj


@dataclass
class GitHubAuthExecutionDecision(SchemaMixin):
    """Per-request decision: can this specific GitHub auth request run now?"""
    project_id: str = ""
    auth_mode: str = ""
    target_url: str = ""
    target_kind: str = ""
    allowed_now: bool = False
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    # Hardcoded safety
    personal_account_always_blocked: bool = True
    production_account_always_blocked: bool = True
    captcha_bypass_allowed: bool = False
    raw_secrets_allowed: bool = False
    storage_state_content_read: bool = False
    client_delivery_allowed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "personal_account_always_blocked", True)
        object.__setattr__(self, "production_account_always_blocked", True)
        object.__setattr__(self, "captcha_bypass_allowed", False)
        object.__setattr__(self, "raw_secrets_allowed", False)
        object.__setattr__(self, "storage_state_content_read", False)
        object.__setattr__(self, "client_delivery_allowed", False)

    @classmethod
    def from_dict(cls, data: dict) -> "GitHubAuthExecutionDecision":
        obj = cls(
            project_id=str(data.get("project_id", "")),
            auth_mode=str(data.get("auth_mode", "")),
            target_url=str(data.get("target_url", "")),
            target_kind=str(data.get("target_kind", "")),
            allowed_now=bool(data.get("allowed_now", False)),
            blockers=list(data.get("blockers", [])),
            notes=list(data.get("notes", [])),
        )
        object.__setattr__(obj, "personal_account_always_blocked", True)
        object.__setattr__(obj, "production_account_always_blocked", True)
        object.__setattr__(obj, "captcha_bypass_allowed", False)
        object.__setattr__(obj, "raw_secrets_allowed", False)
        object.__setattr__(obj, "storage_state_content_read", False)
        object.__setattr__(obj, "client_delivery_allowed", False)
        return obj


@dataclass
class GitHubAuthEvidenceReport(SchemaMixin):
    """Evidence report for an executed (or planned-only) GitHub auth flow."""
    project_id: str = ""
    auth_mode: str = ""
    target_url: str = ""
    target_kind: str = ""
    execution_status: str = "pending"
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    page_title: str = ""
    page_response_status: int = 0
    screenshot_path: str = ""
    storage_state_path: str = ""

    # Hardcoded safety
    raw_credentials_logged: bool = False
    cookies_logged: bool = False
    tokens_logged: bool = False
    storage_state_content_read: bool = False
    captcha_bypass_attempted: bool = False
    personal_account_used: bool = False
    production_account_used: bool = False
    safe_to_deliver: bool = False
    approved_for_client_delivery: bool = False
    internal_only: bool = True
    human_review_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_credentials_logged", False)
        object.__setattr__(self, "cookies_logged", False)
        object.__setattr__(self, "tokens_logged", False)
        object.__setattr__(self, "storage_state_content_read", False)
        object.__setattr__(self, "captcha_bypass_attempted", False)
        object.__setattr__(self, "personal_account_used", False)
        object.__setattr__(self, "production_account_used", False)
        object.__setattr__(self, "safe_to_deliver", False)
        object.__setattr__(self, "approved_for_client_delivery", False)
        object.__setattr__(self, "internal_only", True)
        object.__setattr__(self, "human_review_required", True)

    @classmethod
    def from_dict(cls, data: dict) -> "GitHubAuthEvidenceReport":
        obj = cls(
            project_id=str(data.get("project_id", "")),
            auth_mode=str(data.get("auth_mode", "")),
            target_url=str(data.get("target_url", "")),
            target_kind=str(data.get("target_kind", "")),
            execution_status=str(data.get("execution_status", "pending")),
            blockers=list(data.get("blockers", [])),
            notes=list(data.get("notes", [])),
            page_title=str(data.get("page_title", "")),
            page_response_status=int(data.get("page_response_status", 0)),
            screenshot_path=str(data.get("screenshot_path", "")),
            storage_state_path=str(data.get("storage_state_path", "")),
        )
        object.__setattr__(obj, "raw_credentials_logged", False)
        object.__setattr__(obj, "cookies_logged", False)
        object.__setattr__(obj, "tokens_logged", False)
        object.__setattr__(obj, "storage_state_content_read", False)
        object.__setattr__(obj, "captcha_bypass_attempted", False)
        object.__setattr__(obj, "personal_account_used", False)
        object.__setattr__(obj, "production_account_used", False)
        object.__setattr__(obj, "safe_to_deliver", False)
        object.__setattr__(obj, "approved_for_client_delivery", False)
        object.__setattr__(obj, "internal_only", True)
        object.__setattr__(obj, "human_review_required", True)
        return obj

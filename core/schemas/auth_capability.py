"""Phase 7A -- Auth Capability schema for the AI QA Factory.

Defines auth method types, readiness classifications, and the
AuthCapabilityPlan dataclass. Safety invariants are always enforced
via __post_init__ regardless of caller-supplied values.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AuthMethodType(str, Enum):
    EMAIL_PASSWORD = "email_password"
    GOOGLE_OAUTH = "google_oauth"
    GITHUB_OAUTH = "github_oauth"
    MICROSOFT_OAUTH = "microsoft_oauth"
    SSO_SAML_OIDC = "sso_saml_oidc"
    MAGIC_LINK = "magic_link"
    EMAIL_OTP = "email_otp"
    TOTP_MFA = "totp_mfa"
    STORAGE_STATE_REUSE = "storage_state_reuse"
    CDP_ATTACH = "cdp_attach"
    DEDICATED_PROFILE_CONTEXT = "dedicated_profile_context"
    API_TOKEN = "api_token"
    BEARER_TOKEN = "bearer_token"
    BASIC_AUTH = "basic_auth"
    SESSION_COOKIE_REUSE = "session_cookie_reuse"


class AuthReadiness(str, Enum):
    ALLOWED_NOW = "allowed_now"
    PLANNING_ONLY = "planning_only"
    BLOCKED = "blocked"
    REQUIRES_MANUAL_STEP = "requires_manual_step"
    REQUIRES_TEST_ACCOUNT = "requires_test_account"
    REQUIRES_ENV_VAR_SECRET = "requires_env_var_secret"
    REQUIRES_CLIENT_CONFIRMATION = "requires_client_confirmation"


@dataclass
class AuthMethodCapability:
    """Classification result for a single auth method."""

    method: AuthMethodType
    readiness: AuthReadiness
    reason: str = ""
    required_inputs: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "method": self.method.value,
            "readiness": self.readiness.value,
            "reason": self.reason,
            "required_inputs": self.required_inputs,
            "blocked_reasons": self.blocked_reasons,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AuthMethodCapability":
        return cls(
            method=AuthMethodType(data.get("method", "email_password")),
            readiness=AuthReadiness(data.get("readiness", "planning_only")),
            reason=data.get("reason", ""),
            required_inputs=data.get("required_inputs", []),
            blocked_reasons=data.get("blocked_reasons", []),
            notes=data.get("notes", ""),
        )


@dataclass
class AuthCapabilityInputs:
    """Inputs for the auth capability planner.

    Safety invariants (personal_account_allowed, production_account_allowed,
    captcha_bypass_allowed, storage_state_content_read, auth_bypass_allowed,
    client_delivery_auto_approved, human_review_required) are always enforced
    in __post_init__ regardless of what the caller sets.
    """

    project_id: str
    target_url: str = ""
    has_dedicated_test_account: bool = False
    password_env_var: str = ""
    api_token_env_var: str = ""
    bearer_token_env_var: str = ""
    totp_seed_env_var: str = ""
    storage_state_file: str = ""
    has_storage_state: bool = False
    has_google_account: bool = False
    has_github_account: bool = False
    has_microsoft_account: bool = False
    outputs_root: str = "outputs"
    write_files: bool = True
    # Safety invariants -- always reset by __post_init__
    personal_account_allowed: bool = False
    production_account_allowed: bool = False
    captcha_bypass_allowed: bool = False
    storage_state_content_read: bool = False
    auth_bypass_allowed: bool = False
    client_delivery_auto_approved: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.personal_account_allowed = False
        self.production_account_allowed = False
        self.captcha_bypass_allowed = False
        self.storage_state_content_read = False
        self.auth_bypass_allowed = False
        self.client_delivery_auto_approved = False
        self.human_review_required = True

    @classmethod
    def from_dict(cls, data: dict) -> "AuthCapabilityInputs":
        return cls(
            project_id=data.get("project_id", ""),
            target_url=data.get("target_url", ""),
            has_dedicated_test_account=bool(data.get("has_dedicated_test_account", False)),
            password_env_var=data.get("password_env_var", ""),
            api_token_env_var=data.get("api_token_env_var", ""),
            bearer_token_env_var=data.get("bearer_token_env_var", ""),
            totp_seed_env_var=data.get("totp_seed_env_var", ""),
            storage_state_file=data.get("storage_state_file", ""),
            has_storage_state=bool(data.get("has_storage_state", False)),
            has_google_account=bool(data.get("has_google_account", False)),
            has_github_account=bool(data.get("has_github_account", False)),
            has_microsoft_account=bool(data.get("has_microsoft_account", False)),
            outputs_root=data.get("outputs_root", "outputs"),
            write_files=bool(data.get("write_files", True)),
        )


@dataclass
class AuthCapabilityPlan:
    """Complete auth capability plan for a project.

    Safety invariants are always enforced in __post_init__.
    """

    project_id: str
    target_url: str = ""
    capabilities: list[AuthMethodCapability] = field(default_factory=list)
    blocked_methods: list[str] = field(default_factory=list)
    allowed_now_methods: list[str] = field(default_factory=list)
    planning_only_methods: list[str] = field(default_factory=list)
    requires_action_methods: list[str] = field(default_factory=list)
    recommended_next_steps: list[str] = field(default_factory=list)
    # Safety invariants -- always reset by __post_init__
    human_review_required: bool = True
    personal_account_allowed: bool = False
    production_account_allowed: bool = False
    captcha_bypass_allowed: bool = False
    auth_bypass_allowed: bool = False

    def __post_init__(self) -> None:
        self.human_review_required = True
        self.personal_account_allowed = False
        self.production_account_allowed = False
        self.captcha_bypass_allowed = False
        self.auth_bypass_allowed = False

    @classmethod
    def from_dict(cls, data: dict) -> "AuthCapabilityPlan":
        return cls(
            project_id=data.get("project_id", ""),
            target_url=data.get("target_url", ""),
            capabilities=[AuthMethodCapability.from_dict(c) for c in data.get("capabilities", [])],
            blocked_methods=data.get("blocked_methods", []),
            allowed_now_methods=data.get("allowed_now_methods", []),
            planning_only_methods=data.get("planning_only_methods", []),
            requires_action_methods=data.get("requires_action_methods", []),
            recommended_next_steps=data.get("recommended_next_steps", []),
        )

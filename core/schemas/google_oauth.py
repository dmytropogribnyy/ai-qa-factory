"""Phase 7C — Google OAuth Runner schemas."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List


class GoogleOAuthMode(str, Enum):
    STORAGE_STATE_REUSE = "storage_state_reuse"
    MANUAL_CAPTURE = "manual_storage_state_capture"
    GOOGLE_API_TOKEN = "google_api_oauth_token"
    SERVICE_ACCOUNT = "google_service_account"
    TOTP_TEST_ACCOUNT = "totp_test_account"
    MOCK_OAUTH = "mock_oauth_provider"


class GoogleOAuthModeReadiness(str, Enum):
    EXECUTABLE = "executable"
    PLANNING_ONLY = "planning_only"
    BLOCKED = "blocked"


class GoogleOAuthRunStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    PLANNING_ONLY = "planning_only"
    SKIPPED = "skipped"


EXECUTABLE_OAUTH_MODES: set[GoogleOAuthMode] = {GoogleOAuthMode.STORAGE_STATE_REUSE}
PLANNING_ONLY_OAUTH_MODES: set[GoogleOAuthMode] = {
    GoogleOAuthMode.MANUAL_CAPTURE,
    GoogleOAuthMode.GOOGLE_API_TOKEN,
    GoogleOAuthMode.SERVICE_ACCOUNT,
    GoogleOAuthMode.TOTP_TEST_ACCOUNT,
    GoogleOAuthMode.MOCK_OAUTH,
}


@dataclass
class GoogleOAuthInputs:
    """Inputs for Phase 7C Google OAuth runner. Safety invariants always reset by __post_init__."""

    project_id: str
    target_url: str = "https://accounts.google.com"
    storage_state_path: str = ""
    account_email_label: str = ""
    dedicated_test_account_confirmed: bool = False
    google_test_account_confirmed: bool = False
    approve_execution: bool = False

    # Safety invariants — always reset by __post_init__ regardless of caller
    raw_secrets_allowed: bool = False
    storage_state_content_read: bool = False
    captcha_bypass_allowed: bool = False
    anti_bot_bypass_allowed: bool = False
    personal_account_allowed: bool = False
    production_account_allowed: bool = False
    client_delivery_allowed: bool = False
    browser_automation_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.raw_secrets_allowed = False
        self.storage_state_content_read = False
        self.captcha_bypass_allowed = False
        self.anti_bot_bypass_allowed = False
        self.personal_account_allowed = False
        self.production_account_allowed = False
        self.client_delivery_allowed = False
        self.browser_automation_allowed = False
        self.human_review_required = True

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "target_url": self.target_url,
            "storage_state_path": self.storage_state_path,
            "account_email_label": self.account_email_label,
            "dedicated_test_account_confirmed": self.dedicated_test_account_confirmed,
            "google_test_account_confirmed": self.google_test_account_confirmed,
            "approve_execution": self.approve_execution,
            "safety": {
                "raw_secrets_allowed": self.raw_secrets_allowed,
                "storage_state_content_read": self.storage_state_content_read,
                "captcha_bypass_allowed": self.captcha_bypass_allowed,
                "anti_bot_bypass_allowed": self.anti_bot_bypass_allowed,
                "personal_account_allowed": self.personal_account_allowed,
                "production_account_allowed": self.production_account_allowed,
                "client_delivery_allowed": self.client_delivery_allowed,
                "browser_automation_allowed": self.browser_automation_allowed,
                "human_review_required": self.human_review_required,
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "GoogleOAuthInputs":
        return cls(
            project_id=data.get("project_id", ""),
            target_url=data.get("target_url", "https://accounts.google.com"),
            storage_state_path=data.get("storage_state_path", ""),
            account_email_label=data.get("account_email_label", ""),
            dedicated_test_account_confirmed=data.get(
                "dedicated_test_account_confirmed", False
            ),
            google_test_account_confirmed=data.get("google_test_account_confirmed", False),
            approve_execution=data.get("approve_execution", False),
        )  # __post_init__ always resets safety invariants


@dataclass
class GoogleOAuthPlan:
    """Phase 7C planning artifact — describes which modes are available."""

    project_id: str
    target_url: str
    selected_mode: GoogleOAuthMode = GoogleOAuthMode.STORAGE_STATE_REUSE
    mode_readiness: GoogleOAuthModeReadiness = GoogleOAuthModeReadiness.PLANNING_ONLY
    storage_state_available: bool = False
    storage_state_path: str = ""
    account_email_label: str = ""
    executable_modes: List[str] = field(default_factory=list)
    planning_only_modes: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    recommended_next_steps: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    # Safety invariants
    raw_secrets_allowed: bool = False
    storage_state_content_read: bool = False
    captcha_bypass_allowed: bool = False
    anti_bot_bypass_allowed: bool = False
    personal_account_allowed: bool = False
    production_account_allowed: bool = False
    client_delivery_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.raw_secrets_allowed = False
        self.storage_state_content_read = False
        self.captcha_bypass_allowed = False
        self.anti_bot_bypass_allowed = False
        self.personal_account_allowed = False
        self.production_account_allowed = False
        self.client_delivery_allowed = False
        self.human_review_required = True

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "target_url": self.target_url,
            "selected_mode": self.selected_mode.value,
            "mode_readiness": self.mode_readiness.value,
            "storage_state_available": self.storage_state_available,
            "storage_state_path": self.storage_state_path,
            "account_email_label": self.account_email_label,
            "executable_modes": self.executable_modes,
            "planning_only_modes": self.planning_only_modes,
            "blockers": self.blockers,
            "recommended_next_steps": self.recommended_next_steps,
            "notes": self.notes,
            "safety": {
                "raw_secrets_allowed": self.raw_secrets_allowed,
                "storage_state_content_read": self.storage_state_content_read,
                "captcha_bypass_allowed": self.captcha_bypass_allowed,
                "anti_bot_bypass_allowed": self.anti_bot_bypass_allowed,
                "personal_account_allowed": self.personal_account_allowed,
                "production_account_allowed": self.production_account_allowed,
                "client_delivery_allowed": self.client_delivery_allowed,
                "human_review_required": self.human_review_required,
            },
        }


@dataclass
class GoogleOAuthRunResult:
    """Phase 7C execution result."""

    project_id: str
    target_url: str
    mode: GoogleOAuthMode = GoogleOAuthMode.STORAGE_STATE_REUSE
    status: GoogleOAuthRunStatus = GoogleOAuthRunStatus.PLANNING_ONLY
    account_email_label: str = ""
    storage_state_path: str = ""
    storage_state_present: bool = False
    smoke_commands: List[str] = field(default_factory=list)
    smoke_results: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    artifacts: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    auth_coverage_summary: str = ""

    # Safety invariants
    raw_secrets_allowed: bool = False
    storage_state_content_read: bool = False
    captcha_bypass_allowed: bool = False
    anti_bot_bypass_allowed: bool = False
    personal_account_allowed: bool = False
    production_account_allowed: bool = False
    client_delivery_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.raw_secrets_allowed = False
        self.storage_state_content_read = False
        self.captcha_bypass_allowed = False
        self.anti_bot_bypass_allowed = False
        self.personal_account_allowed = False
        self.production_account_allowed = False
        self.client_delivery_allowed = False
        self.human_review_required = True

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "target_url": self.target_url,
            "mode": self.mode.value,
            "status": self.status.value,
            "account_email_label": self.account_email_label,
            "storage_state_path": self.storage_state_path,
            "storage_state_present": self.storage_state_present,
            "smoke_commands": self.smoke_commands,
            "smoke_results": self.smoke_results,
            "duration_seconds": self.duration_seconds,
            "artifacts": self.artifacts,
            "notes": self.notes,
            "blockers": self.blockers,
            "auth_coverage_summary": self.auth_coverage_summary,
            "safety": {
                "raw_secrets_allowed": self.raw_secrets_allowed,
                "storage_state_content_read": self.storage_state_content_read,
                "captcha_bypass_allowed": self.captcha_bypass_allowed,
                "anti_bot_bypass_allowed": self.anti_bot_bypass_allowed,
                "personal_account_allowed": self.personal_account_allowed,
                "production_account_allowed": self.production_account_allowed,
                "client_delivery_allowed": self.client_delivery_allowed,
                "human_review_required": self.human_review_required,
            },
        }

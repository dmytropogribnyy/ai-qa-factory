"""Phase 7D — Email/Password Auth Runner schemas."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import List

ORANGEHRM_DEFAULT_LOGIN_URL = (
    "https://opensource-demo.orangehrmlive.com/web/index.php/auth/login"
)
ORANGEHRM_DEFAULT_SUCCESS_URL = (
    "https://opensource-demo.orangehrmlive.com/web/index.php/dashboard/index"
)

SUPPORTED_TARGETS: set[str] = {"orangehrm_demo"}


class EmailPasswordRunStatus(str, Enum):
    PASSED = "passed"
    FAILED = "failed"
    BLOCKED = "blocked"
    PLANNING_ONLY = "planning_only"
    SKIPPED = "skipped"


class EmailPasswordModeReadiness(str, Enum):
    EXECUTABLE = "executable"
    PLANNING_ONLY = "planning_only"
    BLOCKED = "blocked"


@dataclass
class EmailPasswordInputs:
    """
    Inputs for Phase 7D Email/Password runner.
    Credentials are never stored here — only env var NAMES.
    Safety invariants always reset by __post_init__ regardless of caller.
    """

    project_id: str
    target_name: str = "orangehrm_demo"
    login_url: str = ORANGEHRM_DEFAULT_LOGIN_URL
    success_url: str = ORANGEHRM_DEFAULT_SUCCESS_URL
    username_env_var: str = "ORANGEHRM_USERNAME"
    password_env_var: str = "ORANGEHRM_PASSWORD"
    account_label: str = ""
    dedicated_test_account_confirmed: bool = False
    approve_execution: bool = False

    # Safety invariants — always reset by __post_init__
    raw_secrets_allowed: bool = False
    personal_account_allowed: bool = False
    production_account_allowed: bool = False
    captcha_bypass_allowed: bool = False
    credential_logging_allowed: bool = False
    client_delivery_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.raw_secrets_allowed = False
        self.personal_account_allowed = False
        self.production_account_allowed = False
        self.captcha_bypass_allowed = False
        self.credential_logging_allowed = False
        self.client_delivery_allowed = False
        self.human_review_required = True

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "target_name": self.target_name,
            "login_url": self.login_url,
            "success_url": self.success_url,
            "username_env_var": self.username_env_var,
            "password_env_var": self.password_env_var,
            "account_label": self.account_label,
            "dedicated_test_account_confirmed": self.dedicated_test_account_confirmed,
            "approve_execution": self.approve_execution,
            "safety": {
                "raw_secrets_allowed": self.raw_secrets_allowed,
                "personal_account_allowed": self.personal_account_allowed,
                "production_account_allowed": self.production_account_allowed,
                "captcha_bypass_allowed": self.captcha_bypass_allowed,
                "credential_logging_allowed": self.credential_logging_allowed,
                "client_delivery_allowed": self.client_delivery_allowed,
                "human_review_required": self.human_review_required,
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> "EmailPasswordInputs":
        return cls(
            project_id=data.get("project_id", ""),
            target_name=data.get("target_name", "orangehrm_demo"),
            login_url=data.get("login_url", ORANGEHRM_DEFAULT_LOGIN_URL),
            success_url=data.get("success_url", ORANGEHRM_DEFAULT_SUCCESS_URL),
            username_env_var=data.get("username_env_var", "ORANGEHRM_USERNAME"),
            password_env_var=data.get("password_env_var", "ORANGEHRM_PASSWORD"),
            account_label=data.get("account_label", ""),
            dedicated_test_account_confirmed=data.get(
                "dedicated_test_account_confirmed", False
            ),
            approve_execution=data.get("approve_execution", False),
        )


@dataclass
class EmailPasswordPlan:
    """Phase 7D planning artifact — env var presence check, mode readiness."""

    project_id: str
    target_name: str
    login_url: str
    success_url: str
    username_env_var: str
    password_env_var: str
    mode_readiness: EmailPasswordModeReadiness = EmailPasswordModeReadiness.PLANNING_ONLY
    username_env_set: bool = False
    password_env_set: bool = False
    account_label: str = ""
    blockers: List[str] = field(default_factory=list)
    recommended_next_steps: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    # Safety invariants
    raw_secrets_allowed: bool = False
    personal_account_allowed: bool = False
    production_account_allowed: bool = False
    captcha_bypass_allowed: bool = False
    credential_logging_allowed: bool = False
    client_delivery_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.raw_secrets_allowed = False
        self.personal_account_allowed = False
        self.production_account_allowed = False
        self.captcha_bypass_allowed = False
        self.credential_logging_allowed = False
        self.client_delivery_allowed = False
        self.human_review_required = True

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "target_name": self.target_name,
            "login_url": self.login_url,
            "success_url": self.success_url,
            "username_env_var": self.username_env_var,
            "password_env_var": self.password_env_var,
            "mode_readiness": self.mode_readiness.value,
            "username_env_set": self.username_env_set,
            "password_env_set": self.password_env_set,
            "account_label": self.account_label,
            "blockers": self.blockers,
            "recommended_next_steps": self.recommended_next_steps,
            "notes": self.notes,
            "safety": {
                "raw_secrets_allowed": self.raw_secrets_allowed,
                "personal_account_allowed": self.personal_account_allowed,
                "production_account_allowed": self.production_account_allowed,
                "captcha_bypass_allowed": self.captcha_bypass_allowed,
                "credential_logging_allowed": self.credential_logging_allowed,
                "client_delivery_allowed": self.client_delivery_allowed,
                "human_review_required": self.human_review_required,
            },
        }


@dataclass
class EmailPasswordRunResult:
    """Phase 7D execution result. Credential values are never stored."""

    project_id: str
    target_name: str
    login_url: str
    success_url: str
    status: EmailPasswordRunStatus = EmailPasswordRunStatus.PLANNING_ONLY
    account_label: str = ""
    username_env_var: str = ""
    password_env_var: str = ""
    smoke_commands: List[str] = field(default_factory=list)
    smoke_results: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    artifacts: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    auth_coverage_summary: str = ""
    approved_for_client_delivery: bool = False

    # Safety invariants
    raw_secrets_allowed: bool = False
    personal_account_allowed: bool = False
    production_account_allowed: bool = False
    captcha_bypass_allowed: bool = False
    credential_logging_allowed: bool = False
    client_delivery_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.raw_secrets_allowed = False
        self.personal_account_allowed = False
        self.production_account_allowed = False
        self.captcha_bypass_allowed = False
        self.credential_logging_allowed = False
        self.client_delivery_allowed = False
        self.human_review_required = True
        self.approved_for_client_delivery = False

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "target_name": self.target_name,
            "login_url": self.login_url,
            "success_url": self.success_url,
            "status": self.status.value,
            "account_label": self.account_label,
            "username_env_var": self.username_env_var,
            "password_env_var": self.password_env_var,
            "smoke_commands": self.smoke_commands,
            "smoke_results": self.smoke_results,
            "duration_seconds": self.duration_seconds,
            "artifacts": self.artifacts,
            "notes": self.notes,
            "blockers": self.blockers,
            "auth_coverage_summary": self.auth_coverage_summary,
            "approved_for_client_delivery": self.approved_for_client_delivery,
            "safety": {
                "raw_secrets_allowed": self.raw_secrets_allowed,
                "personal_account_allowed": self.personal_account_allowed,
                "production_account_allowed": self.production_account_allowed,
                "captcha_bypass_allowed": self.captcha_bypass_allowed,
                "credential_logging_allowed": self.credential_logging_allowed,
                "client_delivery_allowed": self.client_delivery_allowed,
                "human_review_required": self.human_review_required,
            },
        }

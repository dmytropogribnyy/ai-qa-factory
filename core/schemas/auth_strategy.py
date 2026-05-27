"""Phase 7B -- Auth Strategy Decision schema for the AI QA Factory.

Defines decision status types and the AuthStrategyDecision dataclass.
Safety invariants are always enforced via __post_init__ regardless of caller.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class DecisionStatus(str, Enum):
    READY_FOR_EXECUTION = "ready_for_execution"
    MISSING_REQUIRED_INPUT = "missing_required_input"
    PLANNING_ONLY = "planning_only"
    BLOCKED = "blocked"
    NO_METHODS_AVAILABLE = "no_methods_available"


@dataclass
class AuthStrategyDecision:
    """Selector output: the chosen auth strategy or explanation of why none is available.

    Safety invariants are always reset by __post_init__ regardless of caller-supplied values.
    """

    project_id: str
    selected_method: str = ""
    selected_provider: str = ""
    selected_mode: str = ""
    decision_status: DecisionStatus = DecisionStatus.PLANNING_ONLY
    reason: str = ""
    required_inputs: list[str] = field(default_factory=list)
    missing_inputs: list[str] = field(default_factory=list)
    blocked_reasons: list[str] = field(default_factory=list)
    safe_to_execute: bool = False
    next_runner: str | None = None
    requires_human_approval: bool = True
    requires_dedicated_test_account: bool = True
    # Safety invariants -- always reset by __post_init__
    raw_secrets_allowed: bool = False
    browser_execution_allowed: bool = False
    credential_usage_allowed: bool = False
    storage_state_content_read: bool = False
    personal_account_allowed: bool = False
    production_account_allowed: bool = False
    captcha_bypass_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.raw_secrets_allowed = False
        self.browser_execution_allowed = False
        self.credential_usage_allowed = False
        self.storage_state_content_read = False
        self.personal_account_allowed = False
        self.production_account_allowed = False
        self.captcha_bypass_allowed = False
        self.human_review_required = True

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "selected_method": self.selected_method,
            "selected_provider": self.selected_provider,
            "selected_mode": self.selected_mode,
            "decision_status": self.decision_status.value,
            "reason": self.reason,
            "required_inputs": self.required_inputs,
            "missing_inputs": self.missing_inputs,
            "blocked_reasons": self.blocked_reasons,
            "safe_to_execute": self.safe_to_execute,
            "next_runner": self.next_runner,
            "requires_human_approval": self.requires_human_approval,
            "requires_dedicated_test_account": self.requires_dedicated_test_account,
            "raw_secrets_allowed": self.raw_secrets_allowed,
            "browser_execution_allowed": self.browser_execution_allowed,
            "credential_usage_allowed": self.credential_usage_allowed,
            "storage_state_content_read": self.storage_state_content_read,
            "personal_account_allowed": self.personal_account_allowed,
            "production_account_allowed": self.production_account_allowed,
            "captcha_bypass_allowed": self.captcha_bypass_allowed,
            "human_review_required": self.human_review_required,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "AuthStrategyDecision":
        return cls(
            project_id=data.get("project_id", ""),
            selected_method=data.get("selected_method", ""),
            selected_provider=data.get("selected_provider", ""),
            selected_mode=data.get("selected_mode", ""),
            decision_status=DecisionStatus(data.get("decision_status", "planning_only")),
            reason=data.get("reason", ""),
            required_inputs=data.get("required_inputs", []),
            missing_inputs=data.get("missing_inputs", []),
            blocked_reasons=data.get("blocked_reasons", []),
            safe_to_execute=bool(data.get("safe_to_execute", False)),
            next_runner=data.get("next_runner"),
            requires_human_approval=bool(data.get("requires_human_approval", True)),
            requires_dedicated_test_account=bool(data.get("requires_dedicated_test_account", True)),
        )

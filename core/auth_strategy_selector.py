"""Phase 7B -- Auth Strategy Selector for the AI QA Factory.

Takes an AuthCapabilityPlan (from Phase 7A) and selects the safest
executable auth strategy using a fixed priority order.

No auth flows are executed -- selection and decision only.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.schemas.auth_capability import AuthCapabilityPlan, AuthMethodCapability
from core.schemas.auth_strategy import AuthStrategyDecision, DecisionStatus

_STRATEGY_DIR_NAME = "35_auth_strategy"

_PRIORITY_ORDER: list[str] = [
    "storage_state_reuse",
    "google_oauth",
    "github_oauth",
    "microsoft_oauth",
    "api_token",
    "bearer_token",
    "dedicated_profile_context",
    "email_password",
    "basic_auth",
    "totp_mfa",
    "cdp_attach",
    "session_cookie_reuse",
    "magic_link",
    "email_otp",
    "sso_saml_oidc",
]

_METHOD_METADATA: dict[str, dict] = {
    "storage_state_reuse": {
        "provider": "generic", "mode": "storage_state_reuse", "runner": "storage_state_runner",
    },
    "google_oauth": {
        "provider": "google", "mode": "storage_state_reuse", "runner": "google_oauth_runner",
    },
    "github_oauth": {
        "provider": "github", "mode": "storage_state_reuse", "runner": "github_oauth_runner",
    },
    "microsoft_oauth": {
        "provider": "microsoft", "mode": "storage_state_reuse", "runner": "microsoft_oauth_runner",
    },
    "api_token": {
        "provider": "api", "mode": "api_token", "runner": "api_token_runner",
    },
    "bearer_token": {
        "provider": "api", "mode": "bearer_token", "runner": "bearer_token_runner",
    },
    "dedicated_profile_context": {
        "provider": "browser", "mode": "dedicated_profile_context", "runner": "browser_profile_runner",
    },
    "email_password": {
        "provider": "email", "mode": "email_password", "runner": "email_password_runner",
    },
    "basic_auth": {
        "provider": "email", "mode": "basic_auth", "runner": "basic_auth_runner",
    },
    "totp_mfa": {
        "provider": "totp", "mode": "totp_mfa", "runner": "totp_runner",
    },
    "cdp_attach": {
        "provider": "browser", "mode": "cdp_attach", "runner": "cdp_attach_runner",
    },
    "session_cookie_reuse": {
        "provider": "generic", "mode": "session_cookie_reuse", "runner": "session_cookie_runner",
    },
    "magic_link": {
        "provider": "email", "mode": "magic_link", "runner": None,
    },
    "email_otp": {
        "provider": "email", "mode": "email_otp", "runner": None,
    },
    "sso_saml_oidc": {
        "provider": "sso", "mode": "sso_saml_oidc", "runner": None,
    },
}


def _decision_to_dict(decision: AuthStrategyDecision) -> dict:
    return decision.to_dict()


def _build_summary_md(decision: AuthStrategyDecision) -> str:
    lines = [
        "# Auth Strategy Decision",
        "",
        f"Project: {decision.project_id}",
        f"Status:  {decision.decision_status.value}",
        f"Safe to execute: {decision.safe_to_execute}",
        "",
        "## Safety Invariants",
        "",
        f"- personal_account_allowed:   {decision.personal_account_allowed}",
        f"- production_account_allowed: {decision.production_account_allowed}",
        f"- captcha_bypass_allowed:     {decision.captcha_bypass_allowed}",
        f"- raw_secrets_allowed:        {decision.raw_secrets_allowed}",
        f"- browser_execution_allowed:  {decision.browser_execution_allowed}",
        f"- credential_usage_allowed:   {decision.credential_usage_allowed}",
        f"- storage_state_content_read: {decision.storage_state_content_read}",
        f"- human_review_required:      {decision.human_review_required}",
        "",
        "## Selected Strategy",
        "",
        f"- method:      {decision.selected_method or '(none)'}",
        f"- provider:    {decision.selected_provider or '(none)'}",
        f"- mode:        {decision.selected_mode or '(none)'}",
        f"- next_runner: {decision.next_runner or '(none)'}",
        f"- reason:      {decision.reason}",
    ]
    if decision.required_inputs:
        lines += ["", "## Required Inputs", ""]
        lines += [f"- {inp}" for inp in decision.required_inputs]
    if decision.missing_inputs:
        lines += ["", "## Missing Inputs", ""]
        lines += [f"- {inp}" for inp in decision.missing_inputs]
    if decision.blocked_reasons:
        lines += ["", "## Blocked Reasons", ""]
        lines += [f"- {r}" for r in decision.blocked_reasons]
    return "\n".join(lines) + "\n"


class AuthStrategySelector:
    """Select the highest-priority safe executable auth strategy from a capability plan."""

    def __init__(
        self,
        plan: AuthCapabilityPlan,
        outputs_root: str = "outputs",
        write_files: bool = True,
    ) -> None:
        self._plan = plan
        self._write_files = write_files
        self._strategy_dir = Path(outputs_root) / plan.project_id / _STRATEGY_DIR_NAME

    def _get_capability(self, method: str) -> AuthMethodCapability | None:
        for cap in self._plan.capabilities:
            if cap.method.value == method:
                return cap
        return None

    def select(self) -> AuthStrategyDecision:
        plan = self._plan

        # 1. Try allowed_now_methods in priority order
        for method in _PRIORITY_ORDER:
            if method in plan.allowed_now_methods:
                meta = _METHOD_METADATA.get(method, {})
                cap = self._get_capability(method)
                return AuthStrategyDecision(
                    project_id=plan.project_id,
                    selected_method=method,
                    selected_provider=meta.get("provider", ""),
                    selected_mode=meta.get("mode", ""),
                    decision_status=DecisionStatus.READY_FOR_EXECUTION,
                    reason=(
                        cap.reason if cap and cap.reason
                        else f"{method} is available -- all required inputs present"
                    ),
                    required_inputs=cap.required_inputs if cap else [],
                    missing_inputs=[],
                    blocked_reasons=[],
                    safe_to_execute=True,
                    next_runner=meta.get("runner"),
                    requires_human_approval=True,
                    requires_dedicated_test_account=True,
                )

        # 2. Try requires_action_methods in priority order
        for method in _PRIORITY_ORDER:
            if method in plan.requires_action_methods:
                meta = _METHOD_METADATA.get(method, {})
                cap = self._get_capability(method)
                required = cap.required_inputs if cap else []
                return AuthStrategyDecision(
                    project_id=plan.project_id,
                    selected_method=method,
                    selected_provider=meta.get("provider", ""),
                    selected_mode=meta.get("mode", ""),
                    decision_status=DecisionStatus.MISSING_REQUIRED_INPUT,
                    reason=(
                        cap.reason if cap and cap.reason
                        else f"{method} requires additional inputs before execution"
                    ),
                    required_inputs=required,
                    missing_inputs=required,
                    blocked_reasons=[],
                    safe_to_execute=False,
                    next_runner=None,
                    requires_human_approval=True,
                    requires_dedicated_test_account=True,
                )

        # 3. Check planning_only
        if plan.planning_only_methods:
            return AuthStrategyDecision(
                project_id=plan.project_id,
                decision_status=DecisionStatus.PLANNING_ONLY,
                reason=(
                    "No executable auth method available. "
                    "All known methods are in planning_only state."
                ),
                safe_to_execute=False,
                next_runner=None,
            )

        # 4. Everything blocked
        if plan.blocked_methods:
            return AuthStrategyDecision(
                project_id=plan.project_id,
                decision_status=DecisionStatus.BLOCKED,
                reason="All auth methods are blocked by safety rules.",
                blocked_reasons=["All methods blocked -- check safety invariants"],
                safe_to_execute=False,
                next_runner=None,
            )

        # 5. Empty plan
        return AuthStrategyDecision(
            project_id=plan.project_id,
            decision_status=DecisionStatus.NO_METHODS_AVAILABLE,
            reason="No auth methods found in the capability plan.",
            safe_to_execute=False,
            next_runner=None,
        )

    def run(self) -> AuthStrategyDecision:
        """Select strategy and write artifacts if write_files=True."""
        decision = self.select()
        if self._write_files:
            self._strategy_dir.mkdir(parents=True, exist_ok=True)
            (self._strategy_dir / "auth_strategy_decision.json").write_text(
                json.dumps(_decision_to_dict(decision), indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
            (self._strategy_dir / "auth_strategy_summary.md").write_text(
                _build_summary_md(decision),
                encoding="utf-8",
            )
        return decision

"""Phase 7A -- Auth Capability Planner.

Classifies authentication methods based on inputs and returns an
AuthCapabilityPlan. No execution -- planning and classification only.

For each supported auth method, determines:
  allowed_now             -- can be safely executed with provided inputs
  planning_only           -- method known but no inputs to execute
  blocked                 -- explicitly blocked (e.g. enterprise SSO auto-config)
  requires_manual_step    -- execution requires human interaction first
  requires_test_account   -- no dedicated test account confirmed
  requires_env_var_secret -- test account exists but credential env var not named
  requires_client_confirmation -- needs client to confirm test environment

Safety invariants never change regardless of caller inputs.
Raw secrets are never accepted. Storage state file existence may be
checked (by path), but content is never read.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.schemas.auth_capability import (
    AuthCapabilityInputs,
    AuthCapabilityPlan,
    AuthMethodCapability,
    AuthMethodType,
    AuthReadiness,
)

_AUTH_DIR_NAME = "34_auth_capability"


class AuthCapabilityPlanner:
    """Classify auth methods and produce an AuthCapabilityPlan."""

    def __init__(self, inputs: AuthCapabilityInputs) -> None:
        self._inputs = inputs
        self._audit_dir = (
            Path(inputs.outputs_root) / inputs.project_id / _AUTH_DIR_NAME
        )

    def build_plan(self) -> AuthCapabilityPlan:
        """Build the auth capability plan (no I/O)."""
        inp = self._inputs
        caps: list[AuthMethodCapability] = [
            _classify_email_password(inp),
            _classify_google_oauth(inp),
            _classify_github_oauth(inp),
            _classify_microsoft_oauth(inp),
            _classify_sso_saml_oidc(),
            _classify_magic_link(),
            _classify_email_otp(),
            _classify_totp_mfa(inp),
            _classify_storage_state_reuse(inp),
            _classify_cdp_attach(inp),
            _classify_dedicated_profile_context(inp),
            _classify_api_token(inp),
            _classify_bearer_token(inp),
            _classify_basic_auth(inp),
            _classify_session_cookie_reuse(inp),
        ]

        allowed_now = [c.method.value for c in caps if c.readiness == AuthReadiness.ALLOWED_NOW]
        planning_only = [c.method.value for c in caps if c.readiness == AuthReadiness.PLANNING_ONLY]
        blocked = [c.method.value for c in caps if c.readiness == AuthReadiness.BLOCKED]
        requires_action = [
            c.method.value for c in caps
            if c.readiness not in {
                AuthReadiness.ALLOWED_NOW,
                AuthReadiness.PLANNING_ONLY,
                AuthReadiness.BLOCKED,
            }
        ]

        return AuthCapabilityPlan(
            project_id=inp.project_id,
            target_url=inp.target_url,
            capabilities=caps,
            blocked_methods=blocked,
            allowed_now_methods=allowed_now,
            planning_only_methods=planning_only,
            requires_action_methods=requires_action,
            recommended_next_steps=_next_steps(caps, inp),
        )

    def run(self) -> AuthCapabilityPlan:
        """Build plan and write artifacts if write_files=True."""
        plan = self.build_plan()
        if self._inputs.write_files:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            (self._audit_dir / "auth_capability_plan.json").write_text(
                json.dumps(_plan_to_dict(plan), indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
            _write_summary_md(self._audit_dir / "auth_capability_summary.md", plan)
        return plan


# ---------------------------------------------------------------------------
# Per-method classifiers
# ---------------------------------------------------------------------------

def _classify_email_password(inp: AuthCapabilityInputs) -> AuthMethodCapability:
    if inp.has_dedicated_test_account and inp.password_env_var:
        return AuthMethodCapability(
            method=AuthMethodType.EMAIL_PASSWORD,
            readiness=AuthReadiness.ALLOWED_NOW,
            reason="Dedicated test account confirmed and password env var name provided",
            required_inputs=["dedicated test account", f"env: {inp.password_env_var}"],
            notes="Personal and production accounts are always blocked",
        )
    if inp.has_dedicated_test_account:
        return AuthMethodCapability(
            method=AuthMethodType.EMAIL_PASSWORD,
            readiness=AuthReadiness.REQUIRES_ENV_VAR_SECRET,
            reason="Test account confirmed but no password env var name provided",
            required_inputs=["--password-env-var ENV_VAR_NAME"],
        )
    return AuthMethodCapability(
        method=AuthMethodType.EMAIL_PASSWORD,
        readiness=AuthReadiness.REQUIRES_TEST_ACCOUNT,
        reason="No dedicated test account confirmed",
        required_inputs=["dedicated test account (not personal, not production)", "--password-env-var ENV_VAR_NAME"],
        blocked_reasons=["personal_account_allowed=False", "production_account_allowed=False"],
    )


def _classify_google_oauth(inp: AuthCapabilityInputs) -> AuthMethodCapability:
    has_ss = inp.has_storage_state or bool(inp.storage_state_file)
    if inp.has_google_account and has_ss:
        return AuthMethodCapability(
            method=AuthMethodType.GOOGLE_OAUTH,
            readiness=AuthReadiness.ALLOWED_NOW,
            reason="Google test account confirmed and storageState available",
            required_inputs=["Google test account storageState file"],
            notes="Phase 5G runner supports storageState reuse",
        )
    if inp.has_google_account:
        return AuthMethodCapability(
            method=AuthMethodType.GOOGLE_OAUTH,
            readiness=AuthReadiness.REQUIRES_MANUAL_STEP,
            reason="Google test account confirmed but storageState not yet captured",
            required_inputs=["manual storageState capture (run once with browser visible)"],
            notes="Use Phase 5G manual capture mode or CDP attach to capture storageState first",
        )
    return AuthMethodCapability(
        method=AuthMethodType.GOOGLE_OAUTH,
        readiness=AuthReadiness.REQUIRES_TEST_ACCOUNT,
        reason="No Google dedicated test account confirmed",
        required_inputs=["Google dedicated test account (not personal Gmail)"],
        blocked_reasons=["personal_account_allowed=False"],
    )


def _classify_github_oauth(inp: AuthCapabilityInputs) -> AuthMethodCapability:
    if inp.has_github_account and (inp.has_storage_state or inp.storage_state_file):
        return AuthMethodCapability(
            method=AuthMethodType.GITHUB_OAUTH,
            readiness=AuthReadiness.ALLOWED_NOW,
            reason="GitHub test account confirmed and storageState available",
            required_inputs=["GitHub test account storageState file"],
        )
    if inp.has_github_account:
        return AuthMethodCapability(
            method=AuthMethodType.GITHUB_OAUTH,
            readiness=AuthReadiness.REQUIRES_MANUAL_STEP,
            reason="GitHub test account confirmed but storageState not yet captured",
            required_inputs=["manual storageState capture"],
        )
    return AuthMethodCapability(
        method=AuthMethodType.GITHUB_OAUTH,
        readiness=AuthReadiness.REQUIRES_TEST_ACCOUNT,
        reason="No GitHub dedicated test account confirmed",
        required_inputs=["GitHub dedicated test account (not personal)"],
        blocked_reasons=["personal_account_allowed=False"],
    )


def _classify_microsoft_oauth(inp: AuthCapabilityInputs) -> AuthMethodCapability:
    if inp.has_microsoft_account and (inp.has_storage_state or inp.storage_state_file):
        return AuthMethodCapability(
            method=AuthMethodType.MICROSOFT_OAUTH,
            readiness=AuthReadiness.ALLOWED_NOW,
            reason="Microsoft test account confirmed and storageState available",
            required_inputs=["Microsoft test account storageState file"],
            notes="Requires dedicated M365 test tenant, not personal Microsoft account",
        )
    if inp.has_microsoft_account:
        return AuthMethodCapability(
            method=AuthMethodType.MICROSOFT_OAUTH,
            readiness=AuthReadiness.REQUIRES_MANUAL_STEP,
            reason="Microsoft test account confirmed but storageState not yet captured",
            required_inputs=["manual storageState capture from M365 test tenant"],
            notes="Personal Microsoft accounts are blocked",
        )
    return AuthMethodCapability(
        method=AuthMethodType.MICROSOFT_OAUTH,
        readiness=AuthReadiness.REQUIRES_TEST_ACCOUNT,
        reason="No Microsoft dedicated test account confirmed",
        required_inputs=["M365 test tenant account (not personal, not production tenant)"],
        blocked_reasons=["personal_account_allowed=False", "production_account_allowed=False"],
        notes="Phase 7C will add the Microsoft OAuth runner once a test tenant is available",
    )


def _classify_sso_saml_oidc() -> AuthMethodCapability:
    return AuthMethodCapability(
        method=AuthMethodType.SSO_SAML_OIDC,
        readiness=AuthReadiness.REQUIRES_CLIENT_CONFIRMATION,
        reason="SSO/SAML/OIDC requires client-specific configuration and a dedicated test IdP",
        required_inputs=["client IdP configuration", "test user in SSO directory", "client confirmation of test environment"],
        notes="Enterprise SSO setup is always client-specific. Planned for future phase.",
    )


def _classify_magic_link() -> AuthMethodCapability:
    return AuthMethodCapability(
        method=AuthMethodType.MAGIC_LINK,
        readiness=AuthReadiness.REQUIRES_MANUAL_STEP,
        reason="Magic link auth requires access to a test email inbox (e.g. Mailosaur)",
        required_inputs=["test email inbox (Mailosaur or similar)", "email inbox API key env var"],
        notes="Email inbox integration planned for Phase 7-R or later",
    )


def _classify_email_otp() -> AuthMethodCapability:
    return AuthMethodCapability(
        method=AuthMethodType.EMAIL_OTP,
        readiness=AuthReadiness.REQUIRES_MANUAL_STEP,
        reason="Email OTP requires live email inbox access to capture the OTP code",
        required_inputs=["test email inbox", "OTP extraction logic"],
        notes="Email inbox integration planned for Phase 7-R or later",
    )


def _classify_totp_mfa(inp: AuthCapabilityInputs) -> AuthMethodCapability:
    if inp.totp_seed_env_var:
        return AuthMethodCapability(
            method=AuthMethodType.TOTP_MFA,
            readiness=AuthReadiness.ALLOWED_NOW,
            reason="TOTP seed env var name provided for dedicated test account",
            required_inputs=[f"env: {inp.totp_seed_env_var}"],
            notes="Raw TOTP seed is never accepted in CLI args or logs",
        )
    if inp.has_dedicated_test_account:
        return AuthMethodCapability(
            method=AuthMethodType.TOTP_MFA,
            readiness=AuthReadiness.REQUIRES_ENV_VAR_SECRET,
            reason="Test account confirmed but no TOTP seed env var name provided",
            required_inputs=["--totp-seed-env-var ENV_VAR_NAME"],
            notes="Only dedicated test accounts may use TOTP automation",
        )
    return AuthMethodCapability(
        method=AuthMethodType.TOTP_MFA,
        readiness=AuthReadiness.REQUIRES_TEST_ACCOUNT,
        reason="TOTP requires a dedicated test account with MFA configured",
        required_inputs=["dedicated test account with TOTP", "--totp-seed-env-var ENV_VAR_NAME"],
        blocked_reasons=["personal_account_allowed=False"],
    )


def _classify_storage_state_reuse(inp: AuthCapabilityInputs) -> AuthMethodCapability:
    has_ss = inp.has_storage_state or bool(inp.storage_state_file)
    if has_ss:
        return AuthMethodCapability(
            method=AuthMethodType.STORAGE_STATE_REUSE,
            readiness=AuthReadiness.ALLOWED_NOW,
            reason="StorageState file available for reuse",
            required_inputs=["storageState file path"],
            notes="StorageState content is never read or logged -- only path is used",
        )
    return AuthMethodCapability(
        method=AuthMethodType.STORAGE_STATE_REUSE,
        readiness=AuthReadiness.REQUIRES_MANUAL_STEP,
        reason="No storageState file provided",
        required_inputs=["manual browser login + storageState capture", "--storage-state-file PATH"],
        notes="Capture storageState once via a manual browser session, then reuse",
    )


def _classify_cdp_attach(inp: AuthCapabilityInputs) -> AuthMethodCapability:
    if inp.target_url:
        return AuthMethodCapability(
            method=AuthMethodType.CDP_ATTACH,
            readiness=AuthReadiness.REQUIRES_MANUAL_STEP,
            reason="CDP attach requires a running browser with remote debugging enabled",
            required_inputs=["Chrome launched with --remote-debugging-port", f"target URL: {inp.target_url}"],
            notes="Manual step: launch browser first, then run CDP attach runner",
        )
    return AuthMethodCapability(
        method=AuthMethodType.CDP_ATTACH,
        readiness=AuthReadiness.PLANNING_ONLY,
        reason="No target URL provided; CDP attach is available when a URL and running browser are provided",
        required_inputs=["--target-url URL", "browser with remote debugging enabled"],
    )


def _classify_dedicated_profile_context(inp: AuthCapabilityInputs) -> AuthMethodCapability:
    if inp.target_url:
        return AuthMethodCapability(
            method=AuthMethodType.DEDICATED_PROFILE_CONTEXT,
            readiness=AuthReadiness.ALLOWED_NOW,
            reason="Dedicated browser profile context can be created for any target URL",
            required_inputs=[f"target URL: {inp.target_url}"],
            notes="Requires browser execution approval (--approve-browser-execution)",
        )
    return AuthMethodCapability(
        method=AuthMethodType.DEDICATED_PROFILE_CONTEXT,
        readiness=AuthReadiness.PLANNING_ONLY,
        reason="No target URL provided",
        required_inputs=["--target-url URL"],
    )


def _classify_api_token(inp: AuthCapabilityInputs) -> AuthMethodCapability:
    if inp.api_token_env_var:
        return AuthMethodCapability(
            method=AuthMethodType.API_TOKEN,
            readiness=AuthReadiness.ALLOWED_NOW,
            reason="API token env var name provided",
            required_inputs=[f"env: {inp.api_token_env_var}"],
            notes="Raw API token is never accepted in CLI args",
        )
    return AuthMethodCapability(
        method=AuthMethodType.API_TOKEN,
        readiness=AuthReadiness.REQUIRES_ENV_VAR_SECRET,
        reason="No API token env var name provided",
        required_inputs=["--api-token-env-var ENV_VAR_NAME"],
    )


def _classify_bearer_token(inp: AuthCapabilityInputs) -> AuthMethodCapability:
    if inp.bearer_token_env_var:
        return AuthMethodCapability(
            method=AuthMethodType.BEARER_TOKEN,
            readiness=AuthReadiness.ALLOWED_NOW,
            reason="Bearer token env var name provided",
            required_inputs=[f"env: {inp.bearer_token_env_var}"],
            notes="Raw bearer token is never accepted in CLI args",
        )
    return AuthMethodCapability(
        method=AuthMethodType.BEARER_TOKEN,
        readiness=AuthReadiness.REQUIRES_ENV_VAR_SECRET,
        reason="No bearer token env var name provided",
        required_inputs=["--bearer-token-env-var ENV_VAR_NAME"],
    )


def _classify_basic_auth(inp: AuthCapabilityInputs) -> AuthMethodCapability:
    if inp.has_dedicated_test_account and inp.password_env_var:
        return AuthMethodCapability(
            method=AuthMethodType.BASIC_AUTH,
            readiness=AuthReadiness.ALLOWED_NOW,
            reason="Dedicated test account and password env var name provided",
            required_inputs=["dedicated test account", f"env: {inp.password_env_var}"],
        )
    if inp.has_dedicated_test_account:
        return AuthMethodCapability(
            method=AuthMethodType.BASIC_AUTH,
            readiness=AuthReadiness.REQUIRES_ENV_VAR_SECRET,
            reason="Test account confirmed but no password env var name provided",
            required_inputs=["--password-env-var ENV_VAR_NAME"],
        )
    return AuthMethodCapability(
        method=AuthMethodType.BASIC_AUTH,
        readiness=AuthReadiness.REQUIRES_TEST_ACCOUNT,
        reason="No dedicated test account confirmed for basic auth",
        required_inputs=["dedicated test account", "--password-env-var ENV_VAR_NAME"],
        blocked_reasons=["personal_account_allowed=False"],
    )


def _classify_session_cookie_reuse(inp: AuthCapabilityInputs) -> AuthMethodCapability:
    has_ss = inp.has_storage_state or bool(inp.storage_state_file)
    if has_ss:
        return AuthMethodCapability(
            method=AuthMethodType.SESSION_COOKIE_REUSE,
            readiness=AuthReadiness.ALLOWED_NOW,
            reason="StorageState (including cookies) available for reuse",
            required_inputs=["storageState file path"],
            notes="Cookie content is never read or logged",
        )
    return AuthMethodCapability(
        method=AuthMethodType.SESSION_COOKIE_REUSE,
        readiness=AuthReadiness.REQUIRES_MANUAL_STEP,
        reason="No storageState/cookie file provided",
        required_inputs=["manual browser session + cookie/storageState capture"],
    )


# ---------------------------------------------------------------------------
# Next steps recommendation
# ---------------------------------------------------------------------------

def _next_steps(caps: list[AuthMethodCapability], inp: AuthCapabilityInputs) -> list[str]:
    steps: list[str] = []
    allowed = [c.method.value for c in caps if c.readiness == AuthReadiness.ALLOWED_NOW]
    if allowed:
        steps.append(
            f"These auth methods are ready to run: {', '.join(allowed)}. "
            "Enable them with explicit approval flags."
        )
    needs_ss = any(
        c.readiness == AuthReadiness.REQUIRES_MANUAL_STEP
        and c.method in {AuthMethodType.GOOGLE_OAUTH, AuthMethodType.GITHUB_OAUTH, AuthMethodType.MICROSOFT_OAUTH}
        for c in caps
    )
    if needs_ss:
        steps.append(
            "OAuth providers need a one-time manual storageState capture. "
            "Launch the browser, log in with your test account, and save storageState. "
            "Then re-run with --has-storage-state or --storage-state-file PATH."
        )
    if not inp.has_dedicated_test_account:
        steps.append(
            "Provide a dedicated test account (not personal, not production) "
            "to enable email/password, basic auth, and TOTP flows."
        )
    if not inp.api_token_env_var and not inp.bearer_token_env_var:
        steps.append(
            "If the target system supports API token or bearer token auth, "
            "set --api-token-env-var or --bearer-token-env-var to enable those flows."
        )
    if not steps:
        steps.append(
            "Auth capability plan complete. Review each method's readiness and "
            "provide the required inputs to enable execution."
        )
    return steps


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def _plan_to_dict(plan: AuthCapabilityPlan) -> dict:
    return {
        "project_id": plan.project_id,
        "target_url": plan.target_url,
        "capabilities": [c.to_dict() for c in plan.capabilities],
        "blocked_methods": plan.blocked_methods,
        "allowed_now_methods": plan.allowed_now_methods,
        "planning_only_methods": plan.planning_only_methods,
        "requires_action_methods": plan.requires_action_methods,
        "recommended_next_steps": plan.recommended_next_steps,
        "human_review_required": plan.human_review_required,
        "personal_account_allowed": plan.personal_account_allowed,
        "production_account_allowed": plan.production_account_allowed,
        "captcha_bypass_allowed": plan.captcha_bypass_allowed,
        "auth_bypass_allowed": plan.auth_bypass_allowed,
    }


def _write_summary_md(path: Path, plan: AuthCapabilityPlan) -> None:
    lines = [
        "# Auth Capability Plan",
        "",
        f"Project: {plan.project_id}",
        f"Target URL: {plan.target_url or 'not provided'}",
        "",
        "## Safety Invariants",
        "",
        f"- personal_account_allowed:    {plan.personal_account_allowed}",
        f"- production_account_allowed:  {plan.production_account_allowed}",
        f"- captcha_bypass_allowed:      {plan.captcha_bypass_allowed}",
        f"- auth_bypass_allowed:         {plan.auth_bypass_allowed}",
        f"- human_review_required:       {plan.human_review_required}",
        "",
        "## Auth Method Readiness",
        "",
        "| Method | Readiness | Reason |",
        "|---|---|---|",
    ]
    for c in plan.capabilities:
        reason = c.reason[:60] + "..." if len(c.reason) > 60 else c.reason
        lines.append(f"| {c.method.value} | {c.readiness.value} | {reason} |")
    lines += ["", "## Allowed Now", ""]
    for m in plan.allowed_now_methods:
        lines.append(f"- {m}")
    if not plan.allowed_now_methods:
        lines.append("- (none with current inputs)")
    lines += ["", "## Requires Action", ""]
    for m in plan.requires_action_methods:
        cap = next((c for c in plan.capabilities if c.method.value == m), None)
        if cap and cap.required_inputs:
            lines.append(f"- {m}: {', '.join(cap.required_inputs[:2])}")
        else:
            lines.append(f"- {m}")
    lines += ["", "## Recommended Next Steps", ""]
    for step in plan.recommended_next_steps:
        lines.append(f"- {step}")
    lines += ["", "Human review required: yes", ""]
    path.write_text("\n".join(lines), encoding="utf-8")

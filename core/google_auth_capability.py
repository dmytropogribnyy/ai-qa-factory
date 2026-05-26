"""
Phase 5G — Google/OAuth Test Account Capability planner.

Planning and policy decisions ONLY. No browser. No subprocess. No network.
No reading of storageState content. No reading of Chrome profile content.
No env var values read (only env var names referenced).

Replaces blanket-block-everything with a permissioned capability model:
- personal Google account → always blocked
- production Google account → always blocked
- dedicated Google test account → allowed under explicit approvals + dedicated modes
- CAPTCHA bypass → always blocked
- anti-bot bypass → always blocked
- raw secret values in artifacts → always blocked

This module decides WHICH modes are allowed for a given request and produces
a capability plan + decision artifact. It never executes anything.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from core.schemas.google_auth import (
    GOOGLE_AUTH_MODES,
    GOOGLE_AUTH_MODES_EXECUTABLE_5G,
    GOOGLE_AUTH_MODES_PLANNING_ONLY_5G,
    GOOGLE_TARGET_KINDS,
    GoogleAuthCapability,
    GoogleAuthExecutionDecision,
    GoogleAuthModePolicy,
    GoogleStorageStatePolicy,
    GoogleTestAccountProfile,
)


# Required approval flags for any Google test-account auth mode
_BASE_REQUIRED_APPROVALS = [
    "--approve-google-test-account",
    "--google-test-account-confirmed",
    "--dedicated-test-account-confirmed",
]

# Per-mode extra approval flags
_MODE_EXTRA_APPROVALS = {
    "manual_storage_state_capture": ["--auth-mode manual_storage_state_capture"],
    "storage_state_reuse": ["--auth-mode storage_state_reuse", "--storage-state-path"],
    "cdp_attach": ["--auth-mode cdp_attach", "--cdp-port"],
    "dedicated_profile_context": ["--auth-mode dedicated_profile_context", "--user-data-dir"],
    "google_api_oauth_token_future": ["--auth-mode google_api_oauth_token_future", "--api-token-env-var"],
    "google_service_account_future": ["--auth-mode google_service_account_future", "--service-account-reference"],
    "totp_test_account_future": ["--auth-mode totp_test_account_future", "--totp-seed-env-var"],
    "mock_oauth_provider_future": ["--auth-mode mock_oauth_provider_future"],
}

# Allowed expected output directory templates (relative to outputs/<project_id>/)
_ALLOWED_STORAGE_STATE_DIR = "15_google_auth/.auth"
_ALLOWED_USER_DATA_DIR = "15_google_auth/user-data-dir"

# Allowlist of permitted Google test account email labels (display labels only,
# never the raw email itself used as credential). Production/personal accounts
# must never appear here.
_PERMITTED_TEST_ACCOUNT_LABELS = frozenset({
    "danrobinson_artist_gmail",          # dedicated QA test account label
})


class GoogleAuthCapabilityPlanner:
    """
    Plans Google/OAuth test account capability for a project.
    Planning and policy only — no execution, no browser, no network, no secrets.
    """

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self.outputs_root = outputs_root or Path("outputs")

    # ------------------------------------------------------------------
    # Capability planning
    # ------------------------------------------------------------------

    def build_capability(
        self,
        project_id: str,
        account_email_label: str = "",
        account_type: str = "dedicated_test",
        workspace_account: bool = False,
        two_factor_enabled: Optional[bool] = None,
        dedicated_test_account_confirmed: bool = False,
        google_test_account_confirmed: bool = False,
        personal_account_confirmed: bool = False,
        production_account_confirmed: bool = False,
    ) -> GoogleAuthCapability:
        """Build a full capability plan covering all 8 supported modes."""
        profile = GoogleTestAccountProfile(
            account_email_label=account_email_label,
            account_type=account_type,
            account_provider="google",
            workspace_account=workspace_account,
            two_factor_enabled=two_factor_enabled,
            dedicated_test_account_confirmed=dedicated_test_account_confirmed,
            personal_account_confirmed=personal_account_confirmed,
            production_account_confirmed=production_account_confirmed,
            google_test_account_confirmed=google_test_account_confirmed,
        )

        mode_policies: List[GoogleAuthModePolicy] = []
        for mode in GOOGLE_AUTH_MODES:
            mode_policies.append(self._build_mode_policy(mode, profile))

        storage_state_policy = self.build_storage_state_policy(project_id)

        notes = [
            "Personal and production Google accounts are always blocked.",
            "CAPTCHA bypass and anti-bot bypass are always blocked.",
            "Raw cookies, tokens, and storageState content are never logged.",
            "Stealth/undetected-browser is not a core path of this system.",
            f"Implemented executable modes (Phase 5G): {', '.join(GOOGLE_AUTH_MODES_EXECUTABLE_5G)}.",
            f"Planning-only modes (deferred execution): {', '.join(GOOGLE_AUTH_MODES_PLANNING_ONLY_5G)}.",
        ]

        return GoogleAuthCapability(
            project_id=project_id,
            account_profile=profile,
            mode_policies=mode_policies,
            storage_state_policy=storage_state_policy,
            notes=notes,
        )

    def _build_mode_policy(
        self,
        mode: str,
        profile: GoogleTestAccountProfile,
    ) -> GoogleAuthModePolicy:
        blockers: List[str] = []
        warnings: List[str] = []
        notes: List[str] = []

        # Hard blocks (regardless of mode)
        if profile.personal_account_confirmed:
            blockers.append(
                "personal_account_confirmed=True: personal Google accounts are always blocked."
            )
        if profile.production_account_confirmed:
            blockers.append(
                "production_account_confirmed=True: production Google accounts are always blocked."
            )

        # Required approvals
        required = list(_BASE_REQUIRED_APPROVALS) + list(_MODE_EXTRA_APPROVALS.get(mode, []))

        if not profile.dedicated_test_account_confirmed:
            blockers.append("dedicated_test_account_confirmed=False")
        if not profile.google_test_account_confirmed:
            blockers.append("google_test_account_confirmed=False")
        if profile.account_type != "dedicated_test":
            blockers.append(f"account_type='{profile.account_type}' is not 'dedicated_test'")

        # Account label allowlist check (label only, not the raw email)
        if (
            profile.account_email_label
            and profile.account_email_label not in _PERMITTED_TEST_ACCOUNT_LABELS
        ):
            warnings.append(
                f"account_email_label='{profile.account_email_label}' is not in the "
                "permitted test account labels allowlist. Manual review required before execution."
            )

        # 2FA notes
        if profile.two_factor_enabled is True:
            warnings.append(
                "2FA enabled on test account: only manual handling or future TOTP test-account "
                "flow is permitted. No CAPTCHA/anti-bot bypass."
            )

        # Mode-specific blockers/warnings
        if mode == "manual_storage_state_capture":
            notes.append("User manually logs into dedicated Google test account; Playwright saves storageState only to internal path.")
            notes.append("Password entry must be manual. Do not automate password typing. Do not bypass CAPTCHA or 2FA challenges.")
        elif mode == "storage_state_reuse":
            notes.append("Reuses previously captured storageState from approved internal path. storageState content is never read by the planner.")
        elif mode == "cdp_attach":
            notes.append("Planning-only in Phase 5G. Attaches to a user-started Chrome session via remote debugging. Read-only smoke only.")
            warnings.append("cdp_attach is planning-only in Phase 5G — execution is deferred to a later phase.")
        elif mode == "dedicated_profile_context":
            notes.append("Planning-only in Phase 5G. Uses dedicated user-data-dir under internal path. Main Chrome profile is never copied or read.")
            warnings.append("dedicated_profile_context is planning-only in Phase 5G — execution is deferred to a later phase.")
        elif mode == "google_api_oauth_token_future":
            notes.append("Planning-only. Google API access via OAuth token env var reference. No raw token values in artifacts.")
            warnings.append("google_api_oauth_token_future is future-planned — not yet implemented.")
        elif mode == "google_service_account_future":
            notes.append("Planning-only. Google Workspace server-to-server API via service account JSON. JSON key never committed.")
            warnings.append("google_service_account_future is future-planned — not yet implemented.")
        elif mode == "totp_test_account_future":
            notes.append("Planning-only. TOTP generation from test-account seed env var. No seed in repo/artifacts/logs.")
            warnings.append("totp_test_account_future is future-planned — not yet implemented.")
        elif mode == "mock_oauth_provider_future":
            notes.append("Planning-only. Mock OAuth provider replaces Google in CI. No real Google interaction.")
            warnings.append("mock_oauth_provider_future is future-planned — not yet implemented.")

        # Always blocked sub-paths (informational note attached to every mode)
        notes.append("CAPTCHA bypass: always blocked.")
        notes.append("Anti-bot bypass: always blocked.")
        notes.append("Reading sensitive Gmail/Drive content: blocked.")
        notes.append("Writing/deleting Google account data: blocked.")
        notes.append("Copying main Chrome profile silently: blocked.")

        # Only manual_storage_state_capture and storage_state_reuse are
        # potentially executable in Phase 5G; rest are planning-only.
        is_executable_in_5g = mode in GOOGLE_AUTH_MODES_EXECUTABLE_5G

        allowed_now = (
            is_executable_in_5g
            and not blockers
            and profile.account_type == "dedicated_test"
        )

        return GoogleAuthModePolicy(
            auth_mode=mode,
            allowed_now=allowed_now,
            approval_required=True,
            required_approval_flags=required,
            blockers=blockers,
            warnings=warnings,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Storage state policy
    # ------------------------------------------------------------------

    def build_storage_state_policy(
        self,
        project_id: str,
        storage_state_path: Optional[str] = None,
    ) -> GoogleStorageStatePolicy:
        """Build a storage state policy. Reads only path metadata, never content."""
        expected_dir = str(
            (self.outputs_root / project_id / _ALLOWED_STORAGE_STATE_DIR).resolve()
        )
        path = storage_state_path or str(
            (self.outputs_root / project_id / _ALLOWED_STORAGE_STATE_DIR / "google-storageState.json").resolve()
        )

        present = False
        size_bytes = 0
        try:
            p = Path(path)
            if p.exists() and p.is_file():
                present = True
                size_bytes = p.stat().st_size  # size only, content not read
        except Exception:
            present = False
            size_bytes = 0

        return GoogleStorageStatePolicy(
            project_id=project_id,
            storage_state_path=path,
            expected_directory=expected_dir,
            storage_state_present=present,
            storage_state_size_bytes=size_bytes,
            notes=[
                "storageState content is sensitive and must never be read or printed.",
                "Only path existence and size metadata are recorded.",
                "Path must be inside outputs/<project_id>/15_google_auth/.auth/",
                "Must not be committed. .gitignore enforces this.",
            ],
        )

    # ------------------------------------------------------------------
    # Per-request decision
    # ------------------------------------------------------------------

    def decide_execution(
        self,
        project_id: str,
        target_url: str,
        target_kind: str,
        auth_mode: str,
        account_email_label: str = "",
        approve_google_test_account: bool = False,
        google_test_account_confirmed: bool = False,
        dedicated_test_account_confirmed: bool = False,
        personal_account_confirmed: bool = False,
        production_account_confirmed: bool = False,
        storage_state_path: str = "",
        cdp_port: Optional[int] = None,
        user_data_dir: str = "",
        api_token_env_var: str = "",
        service_account_reference: str = "",
        totp_seed_env_var: str = "",
    ) -> GoogleAuthExecutionDecision:
        """
        Decide whether a specific Google auth request can run now.
        No execution, no browser, no network. Path/label inspection only.
        """
        blockers: List[str] = []
        warnings: List[str] = []
        required: List[str] = list(_BASE_REQUIRED_APPROVALS) + list(
            _MODE_EXTRA_APPROVALS.get(auth_mode, [])
        )
        notes: List[str] = []

        # Hard always-blocks
        if personal_account_confirmed:
            blockers.append("personal_account_confirmed=True: blocked.")
        if production_account_confirmed:
            blockers.append("production_account_confirmed=True: blocked.")

        # Approval flags
        if not approve_google_test_account:
            blockers.append("Missing --approve-google-test-account.")
        if not google_test_account_confirmed:
            blockers.append("Missing --google-test-account-confirmed.")
        if not dedicated_test_account_confirmed:
            blockers.append("Missing --dedicated-test-account-confirmed.")

        # Mode allowlist
        if auth_mode not in GOOGLE_AUTH_MODES:
            blockers.append(f"Unknown auth_mode '{auth_mode}'.")
        elif auth_mode not in GOOGLE_AUTH_MODES_EXECUTABLE_5G:
            blockers.append(
                f"auth_mode '{auth_mode}' is planning-only in Phase 5G — execution deferred."
            )

        # Target kind allowlist
        if target_kind and target_kind not in GOOGLE_TARGET_KINDS:
            warnings.append(
                f"target_kind '{target_kind}' is not in the known set: {GOOGLE_TARGET_KINDS}."
            )

        # Target URL safety
        if target_url:
            lurl = target_url.lower()
            captcha_terms = ("recaptcha", "captcha", "challenge")
            if any(t in lurl for t in captcha_terms):
                warnings.append(
                    "Target URL contains a CAPTCHA/challenge marker. "
                    "CAPTCHA/anti-bot bypass is always blocked. Manual challenge handling only."
                )

        # Account label allowlist (display labels only, never raw email values)
        if (
            account_email_label
            and account_email_label not in _PERMITTED_TEST_ACCOUNT_LABELS
        ):
            warnings.append(
                f"account_email_label='{account_email_label}' is not in the permitted "
                "test account labels allowlist. Manual review required before execution."
            )

        # Per-mode resource validation
        if auth_mode == "storage_state_reuse":
            if not storage_state_path:
                blockers.append(
                    "storage_state_reuse mode requires storage_state_path (--storage-state-path)."
                )
            else:
                allowed_dir = str(
                    (self.outputs_root / project_id / _ALLOWED_STORAGE_STATE_DIR).resolve()
                )
                try:
                    ssp = Path(storage_state_path).resolve()
                    if not str(ssp).startswith(allowed_dir):
                        blockers.append(
                            f"storage_state_path must be inside {allowed_dir}/."
                        )
                    if not ssp.exists():
                        blockers.append(
                            f"storage_state_path does not exist: {ssp} (path check only, content not read)."
                        )
                except Exception as exc:
                    blockers.append(f"storage_state_path invalid: {exc}")

        if auth_mode == "manual_storage_state_capture":
            # Output path is fixed under outputs/<project_id>/15_google_auth/.auth/
            notes.append(
                "Manual capture will save storageState to "
                f"outputs/{project_id}/15_google_auth/.auth/google-storageState.json — gitignored."
            )

        if auth_mode == "cdp_attach":
            if cdp_port is not None and (cdp_port < 1024 or cdp_port > 65535):
                blockers.append("cdp_port must be in 1024..65535.")
            blockers.append("cdp_attach is planning-only in Phase 5G — execution deferred.")

        if auth_mode == "dedicated_profile_context":
            if not user_data_dir:
                blockers.append("dedicated_profile_context requires --user-data-dir.")
            else:
                allowed_dir = str(
                    (self.outputs_root / project_id / _ALLOWED_USER_DATA_DIR).resolve()
                )
                try:
                    udd = Path(user_data_dir).resolve()
                    if not str(udd).startswith(allowed_dir):
                        blockers.append(
                            f"user_data_dir must be inside {allowed_dir}/. "
                            "Main Chrome profile cannot be silently reused."
                        )
                except Exception as exc:
                    blockers.append(f"user_data_dir invalid: {exc}")
            blockers.append("dedicated_profile_context is planning-only in Phase 5G — execution deferred.")

        # Future-only modes always blocked from execution in Phase 5G
        if auth_mode in GOOGLE_AUTH_MODES_PLANNING_ONLY_5G and not any(
            b.endswith("execution deferred.") for b in blockers
        ):
            blockers.append(
                f"auth_mode '{auth_mode}' is planning-only in Phase 5G — execution deferred."
            )

        # Env-var name format checks (names only, never values)
        for env_name, label in (
            (api_token_env_var, "api_token_env_var"),
            (totp_seed_env_var, "totp_seed_env_var"),
        ):
            if env_name and not _is_valid_env_var_name(env_name):
                blockers.append(
                    f"{label}='{env_name}' is not a valid env var name "
                    "(uppercase ASCII, digits, underscore; ≤80 chars)."
                )

        allowed_now = not blockers

        notes.append(
            "Decision is planning/policy only. Execution is not performed by this call."
        )
        notes.append(
            "CAPTCHA bypass: blocked. Anti-bot bypass: blocked. Raw secrets: never in artifacts."
        )

        return GoogleAuthExecutionDecision(
            project_id=project_id,
            target_url=target_url,
            target_kind=target_kind,
            auth_mode=auth_mode,
            account_email_label=account_email_label,
            approve_google_test_account=approve_google_test_account,
            google_test_account_confirmed=google_test_account_confirmed,
            dedicated_test_account_confirmed=dedicated_test_account_confirmed,
            personal_account_confirmed=personal_account_confirmed,
            production_account_confirmed=production_account_confirmed,
            storage_state_path=storage_state_path,
            cdp_port=cdp_port,
            user_data_dir=user_data_dir,
            api_token_env_var=api_token_env_var,
            service_account_reference=service_account_reference,
            totp_seed_env_var=totp_seed_env_var,
            allowed_now=allowed_now,
            approval_required=True,
            required_approval_flags=required,
            blockers=blockers,
            warnings=warnings,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Artifact rendering
    # ------------------------------------------------------------------

    def render_capability_artifacts(
        self,
        capability: GoogleAuthCapability,
        project_id: str,
    ) -> dict:
        """Render planning artifacts to outputs/<project_id>/15_google_auth/. No execution."""
        import json

        out_dir = self.outputs_root / project_id / "15_google_auth"
        out_dir.mkdir(parents=True, exist_ok=True)

        paths: dict = {}

        # Capability plan (JSON + MD)
        cap_json = out_dir / "GOOGLE_AUTH_CAPABILITY_PLAN.json"
        cap_json.write_text(
            json.dumps(capability.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        paths["capability_plan_json"] = str(cap_json)

        cap_md = out_dir / "GOOGLE_AUTH_CAPABILITY_PLAN.md"
        cap_md.write_text(self._render_capability_md(capability), encoding="utf-8")
        paths["capability_plan_md"] = str(cap_md)

        # Storage state policy
        if capability.storage_state_policy is not None:
            ssp_json = out_dir / "GOOGLE_STORAGE_STATE_POLICY.json"
            ssp_json.write_text(
                json.dumps(capability.storage_state_policy.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
            paths["storage_state_policy_json"] = str(ssp_json)

            ssp_md = out_dir / "GOOGLE_STORAGE_STATE_POLICY.md"
            ssp_md.write_text(
                self._render_storage_state_policy_md(capability.storage_state_policy),
                encoding="utf-8",
            )
            paths["storage_state_policy_md"] = str(ssp_md)

        # Redaction checklist (always)
        rc_md = out_dir / "GOOGLE_AUTH_REDACTION_CHECKLIST.md"
        rc_md.write_text(self._render_redaction_checklist(), encoding="utf-8")
        paths["redaction_checklist_md"] = str(rc_md)

        return paths

    def render_decision_artifacts(
        self,
        decision: GoogleAuthExecutionDecision,
        project_id: str,
    ) -> dict:
        import json

        out_dir = self.outputs_root / project_id / "15_google_auth"
        out_dir.mkdir(parents=True, exist_ok=True)

        paths: dict = {}

        dec_json = out_dir / "GOOGLE_AUTH_EXECUTION_DECISION.json"
        dec_json.write_text(
            json.dumps(decision.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        paths["decision_json"] = str(dec_json)

        dec_md = out_dir / "GOOGLE_AUTH_EXECUTION_DECISION.md"
        dec_md.write_text(self._render_decision_md(decision), encoding="utf-8")
        paths["decision_md"] = str(dec_md)

        return paths

    # ------------------------------------------------------------------
    # Markdown renderers
    # ------------------------------------------------------------------

    def _render_capability_md(self, cap: GoogleAuthCapability) -> str:
        profile = cap.account_profile
        prof_lines = []
        if profile:
            prof_lines = [
                f"- **account_email_label:** `{profile.account_email_label or '(none)'}`",
                f"- **account_type:** `{profile.account_type}`",
                f"- **workspace_account:** `{profile.workspace_account}`",
                f"- **two_factor_enabled:** `{profile.two_factor_enabled}`",
                f"- **dedicated_test_account_confirmed:** `{profile.dedicated_test_account_confirmed}`",
                f"- **google_test_account_confirmed:** `{profile.google_test_account_confirmed}`",
                f"- **personal_account_confirmed:** `{profile.personal_account_confirmed}`",
                f"- **production_account_confirmed:** `{profile.production_account_confirmed}`",
            ]

        mode_rows = []
        for mp in cap.mode_policies:
            sym = "ALLOWED" if mp.allowed_now else "BLOCKED"
            mode_rows.append(
                f"| `{mp.auth_mode}` | {sym} | {len(mp.blockers)} | {len(mp.warnings)} |"
            )

        return f"""# Google/OAuth Test Account Capability Plan

**Project:** `{cap.project_id}`
**Type:** `{cap.capability_type}`
**Internal only:** human review required before any execution

---

## Account profile

{chr(10).join(prof_lines) if prof_lines else "_no profile provided_"}

---

## Mode summary

| Mode | Status | Blockers | Warnings |
|---|---|---|---|
{chr(10).join(mode_rows)}

---

## Safety invariants (hardcoded)

- `raw_secrets_allowed: {cap.raw_secrets_allowed}`
- `storage_state_content_read: {cap.storage_state_content_read}`
- `browser_profile_content_read: {cap.browser_profile_content_read}`
- `captcha_bypass_allowed: {cap.captcha_bypass_allowed}`
- `anti_bot_bypass_allowed: {cap.anti_bot_bypass_allowed}`
- `client_delivery_allowed: {cap.client_delivery_allowed}`
- `personal_account_always_blocked: {cap.personal_account_always_blocked}`
- `production_account_always_blocked: {cap.production_account_always_blocked}`
- `stealth_live_login_as_core_path: {cap.stealth_live_login_as_core_path}`

---

## Notes

{chr(10).join(f"- {n}" for n in cap.notes) if cap.notes else "_none_"}
"""

    def _render_storage_state_policy_md(
        self, policy: GoogleStorageStatePolicy
    ) -> str:
        return f"""# Google Storage State Policy

**Project:** `{policy.project_id}`

| Field | Value |
|---|---|
| storage_state_path | `{policy.storage_state_path}` |
| expected_directory | `{policy.expected_directory}` |
| internal_only | `{policy.internal_only}` |
| approved_for_commit | `{policy.approved_for_commit}` |
| client_visible | `{policy.client_visible}` |
| storage_state_content_read | `{policy.storage_state_content_read}` |
| storage_state_present | `{policy.storage_state_present}` |
| storage_state_size_bytes | `{policy.storage_state_size_bytes}` |

## Rules

{chr(10).join(f"- {n}" for n in policy.notes)}
"""

    def _render_decision_md(self, dec: GoogleAuthExecutionDecision) -> str:
        sym = "ALLOWED" if dec.allowed_now else "BLOCKED"
        return f"""# Google Auth Execution Decision — {sym}

**Project:** `{dec.project_id}`
**Mode:** `{dec.auth_mode}`
**Target URL:** `{dec.target_url}`
**Target kind:** `{dec.target_kind}`
**Account label:** `{dec.account_email_label or '(none)'}`

## Approval state

| Flag | Value |
|---|---|
| approve_google_test_account | `{dec.approve_google_test_account}` |
| google_test_account_confirmed | `{dec.google_test_account_confirmed}` |
| dedicated_test_account_confirmed | `{dec.dedicated_test_account_confirmed}` |
| personal_account_confirmed | `{dec.personal_account_confirmed}` |
| production_account_confirmed | `{dec.production_account_confirmed}` |

## Resources referenced (path/label only)

- storage_state_path: `{dec.storage_state_path or '(none)'}`
- cdp_port: `{dec.cdp_port}`
- user_data_dir: `{dec.user_data_dir or '(none)'}`
- api_token_env_var: `{dec.api_token_env_var or '(none)'}`
- service_account_reference: `{dec.service_account_reference or '(none)'}`
- totp_seed_env_var: `{dec.totp_seed_env_var or '(none)'}`

## Required approval flags

{chr(10).join(f"- `{f}`" for f in dec.required_approval_flags)}

## Blockers

{chr(10).join(f"- {b}" for b in dec.blockers) if dec.blockers else "_none_"}

## Warnings

{chr(10).join(f"- {w}" for w in dec.warnings) if dec.warnings else "_none_"}

## Safety invariants (hardcoded)

- raw_secrets_allowed: `{dec.raw_secrets_allowed}`
- storage_state_content_read: `{dec.storage_state_content_read}`
- browser_profile_content_read: `{dec.browser_profile_content_read}`
- captcha_bypass_allowed: `{dec.captcha_bypass_allowed}`
- anti_bot_bypass_allowed: `{dec.anti_bot_bypass_allowed}`
- client_delivery_allowed: `{dec.client_delivery_allowed}`

## Notes

{chr(10).join(f"- {n}" for n in dec.notes)}
"""

    def _render_redaction_checklist(self) -> str:
        return """# Google Auth Redaction Checklist

Before any artifact is reviewed or delivered, confirm:

- [ ] No raw Google account email values in JSON/MD outside of explicit display labels.
- [ ] No raw passwords, cookies, tokens, refresh tokens, or storageState content.
- [ ] No service-account JSON key content.
- [ ] No TOTP seed values.
- [ ] No screenshots containing inbox content, full email addresses, or sensitive data.
- [ ] No copied Chrome profile files in outputs/.
- [ ] storageState file (if present) is under `15_google_auth/.auth/` and gitignored.
- [ ] CAPTCHA bypass not attempted in any artifact.
- [ ] Anti-bot bypass not attempted in any artifact.
- [ ] Personal Google account not referenced.
- [ ] Production Google account not referenced.

If any of the above is violated: STOP. Remove the artifact and rotate the test account.
"""


def _is_valid_env_var_name(name: str) -> bool:
    if not name or len(name) > 80:
        return False
    if not name[0].isalpha() or not name[0].isupper():
        return False
    for ch in name:
        if not (ch.isupper() or ch.isdigit() or ch == "_"):
            return False
    return True

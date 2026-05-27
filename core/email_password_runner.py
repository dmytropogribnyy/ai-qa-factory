"""
Phase 7D — Email/Password Auth Runner (OrangeHRM demo smoke).

Credentials are read from env vars only inside the Node.js subprocess.
Python never reads, logs, or serialises credential values.

Safety contract:
- Never accepts raw username/password values — only env var NAMES.
- Credentials read by Node.js from process.env; Python only checks presence.
- Never logs credential values.
- Never writes credential values to artifacts, reports, or logs.
- Personal and production accounts always blocked.
- CAPTCHA bypass always blocked.
- approved_for_client_delivery always False.
- human_review_required always True.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from core.schemas.email_password import (
    SUPPORTED_TARGETS,
    EmailPasswordInputs,
    EmailPasswordModeReadiness,
    EmailPasswordPlan,
    EmailPasswordRunResult,
    EmailPasswordRunStatus,
)

_ALLOWED_LOGIN_URL_PREFIXES = (
    "https://",
    "http://localhost",
    "http://127.0.0.1",
)

_ALWAYS_BLOCKED_SUBSTRINGS = ("captcha", "recaptcha", "anti-bot")


class EmailPasswordRunner:
    """Phase 7D — Email/Password dedicated test-account login runner."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self.outputs_root = outputs_root or Path("outputs")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_env_vars(self, inputs: EmailPasswordInputs) -> tuple[bool, bool]:
        """Return (username_set, password_set). Values are never returned."""
        username_set = bool(os.environ.get(inputs.username_env_var))
        password_set = bool(os.environ.get(inputs.password_env_var))
        return username_set, password_set

    def build_plan(self, inputs: EmailPasswordInputs) -> EmailPasswordPlan:
        """Build a planning artifact — checks env var presence, classifies readiness."""
        username_set, password_set = self.check_env_vars(inputs)
        blockers: list[str] = []

        if inputs.target_name not in SUPPORTED_TARGETS:
            blockers.append(
                f"target_name '{inputs.target_name}' not in supported targets: "
                f"{sorted(SUPPORTED_TARGETS)}"
            )

        if not inputs.dedicated_test_account_confirmed:
            blockers.append("--dedicated-test-account-confirmed not set.")

        if not username_set:
            blockers.append(
                f"Env var '{inputs.username_env_var}' is not set. "
                "Set it at the OS level — never pass values via CLI."
            )

        if not password_set:
            blockers.append(
                f"Env var '{inputs.password_env_var}' is not set. "
                "Set it at the OS level — never pass values via CLI."
            )

        if not self._is_allowed_url(inputs.login_url):
            blockers.append(
                f"login_url '{inputs.login_url}' must start with https:// "
                "or http://localhost."
            )

        if blockers:
            readiness = EmailPasswordModeReadiness.PLANNING_ONLY
            next_steps = [
                f"Set env var: $env:{inputs.username_env_var} = 'your_username'  (PowerShell)",
                f"Set env var: $env:{inputs.password_env_var} = 'your_password'  (PowerShell)",
                "Add --dedicated-test-account-confirmed flag.",
                "Add --approve-execution flag to run the smoke.",
            ]
        else:
            readiness = EmailPasswordModeReadiness.EXECUTABLE
            next_steps = ["Add --approve-execution to run the login smoke."]

        return EmailPasswordPlan(
            project_id=inputs.project_id,
            target_name=inputs.target_name,
            login_url=inputs.login_url,
            success_url=inputs.success_url,
            username_env_var=inputs.username_env_var,
            password_env_var=inputs.password_env_var,
            mode_readiness=readiness,
            username_env_set=username_set,
            password_env_set=password_set,
            account_label=inputs.account_label,
            blockers=blockers,
            recommended_next_steps=next_steps,
            notes=[
                "Credentials read from env vars only — never from CLI flags.",
                "Credential values are never logged or written to artifacts.",
                "Only dedicated test accounts are permitted.",
            ],
        )

    def run(self, inputs: EmailPasswordInputs) -> EmailPasswordRunResult:
        """Run the email/password login smoke or return planning-only result."""
        plan = self.build_plan(inputs)

        if plan.mode_readiness != EmailPasswordModeReadiness.EXECUTABLE:
            return EmailPasswordRunResult(
                project_id=inputs.project_id,
                target_name=inputs.target_name,
                login_url=inputs.login_url,
                success_url=inputs.success_url,
                status=EmailPasswordRunStatus.PLANNING_ONLY,
                account_label=inputs.account_label,
                username_env_var=inputs.username_env_var,
                password_env_var=inputs.password_env_var,
                blockers=plan.blockers,
                notes=plan.recommended_next_steps,
                auth_coverage_summary=(
                    f"Email/password ({inputs.target_name}): "
                    "planning only — prerequisites not met."
                ),
            )

        if not inputs.approve_execution:
            return EmailPasswordRunResult(
                project_id=inputs.project_id,
                target_name=inputs.target_name,
                login_url=inputs.login_url,
                success_url=inputs.success_url,
                status=EmailPasswordRunStatus.BLOCKED,
                account_label=inputs.account_label,
                username_env_var=inputs.username_env_var,
                password_env_var=inputs.password_env_var,
                blockers=["--approve-execution flag not set."],
                notes=["Re-run with --approve-execution to perform the login smoke."],
                auth_coverage_summary=(
                    f"Email/password ({inputs.target_name}): blocked — approval missing."
                ),
            )

        return self._execute_login_smoke(inputs)

    def render_artifacts(
        self,
        plan: EmailPasswordPlan,
        result: EmailPasswordRunResult,
        project_id: str,
    ) -> dict[str, str]:
        """Write 3 output artifacts to outputs/<project_id>/37_email_password_auth/."""
        out_dir = self.outputs_root / project_id / "37_email_password_auth"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: dict[str, str] = {}

        plan_path = out_dir / "email_password_plan.json"
        plan_path.write_text(
            json.dumps(plan.to_dict(), indent=2, default=str), encoding="utf-8"
        )
        paths["email_password_plan_json"] = str(plan_path)

        report_path = out_dir / "email_password_report.json"
        report_path.write_text(
            json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8"
        )
        paths["email_password_report_json"] = str(report_path)

        summary_path = out_dir / "email_password_summary.md"
        summary_path.write_text(
            self._render_summary_md(plan, result), encoding="utf-8"
        )
        paths["email_password_summary_md"] = str(summary_path)

        return paths

    def format_auth_coverage_section(self, result: EmailPasswordRunResult) -> str:
        """Return an Authentication Coverage block for use in client delivery reports."""
        lines = [
            "## Authentication Coverage — Email/Password",
            "",
            f"**Target:** `{result.target_name}`",
            f"**Status:** `{result.status.value}`",
            f"**Account label:** `{result.account_label or '(none)'}`",
            f"**Login URL:** `{result.login_url}`",
            "",
            result.auth_coverage_summary,
            "",
            "**Safety boundary:** credential values never logged or serialised; "
            "personal/production accounts blocked; CAPTCHA bypass blocked; "
            "approved_for_client_delivery=False.",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_login_smoke(
        self, inputs: EmailPasswordInputs
    ) -> EmailPasswordRunResult:
        scaffold_root = self._find_playwright_scaffold(inputs.project_id).resolve()
        script_path = (scaffold_root / "email_password_smoke_7d.cjs").resolve()

        script_content = self._build_login_script(
            login_url=inputs.login_url,
            success_url=inputs.success_url,
            username_env_var=inputs.username_env_var,
            password_env_var=inputs.password_env_var,
        )
        script_path.write_text(script_content, encoding="utf-8")

        node_exe = shutil.which("node") or "node"
        if sys.platform == "win32":
            node_exe = shutil.which("node") or "node"

        # Pass env through — Node reads credentials via process.env[EP_USERNAME_ENV_VAR]
        # Python never reads the credential values, only checks presence via check_env_vars()
        proc_env = dict(os.environ)
        proc_env["EP_USERNAME_ENV_VAR"] = inputs.username_env_var
        proc_env["EP_PASSWORD_ENV_VAR"] = inputs.password_env_var

        start = time.monotonic()
        try:
            proc = subprocess.run(
                [node_exe, str(script_path)],
                cwd=str(scaffold_root),
                env=proc_env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            duration = time.monotonic() - start
            exit_code = proc.returncode
            stdout_tail = (proc.stdout or "")[-800:]
            stderr_tail = (proc.stderr or "")[-400:]
            success = exit_code == 0
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            exit_code = 124
            stdout_tail = ""
            stderr_tail = "TimeoutExpired"
            success = False
        except Exception as exc:
            duration = time.monotonic() - start
            exit_code = 1
            stdout_tail = ""
            stderr_tail = f"{type(exc).__name__}: {exc}"[:400]
            success = False

        status = (
            EmailPasswordRunStatus.PASSED if success else EmailPasswordRunStatus.FAILED
        )
        return EmailPasswordRunResult(
            project_id=inputs.project_id,
            target_name=inputs.target_name,
            login_url=inputs.login_url,
            success_url=inputs.success_url,
            status=status,
            account_label=inputs.account_label,
            username_env_var=inputs.username_env_var,
            password_env_var=inputs.password_env_var,
            smoke_commands=[f"node {script_path.name}"],
            smoke_results=[
                f"exit_code={exit_code}",
                f"duration={round(duration, 2)}s",
                *(
                    [f"stdout={stdout_tail}"]
                    if stdout_tail
                    else ["no_stdout"]
                ),
                *(
                    [f"stderr={stderr_tail}"]
                    if stderr_tail
                    else ["no_stderr"]
                ),
            ],
            duration_seconds=round(duration, 3),
            notes=[
                "Credential values were NOT read by Python — only env var names used.",
                "Credentials read by Node.js from process.env at runtime only.",
                "No credential values in artifacts, logs, or reports.",
                f"Result: {'PASSED' if success else 'FAILED'}",
            ],
            auth_coverage_summary=(
                f"Email/password ({inputs.target_name}): "
                f"{'PASSED' if success else 'FAILED'}"
            ),
        )

    def _find_playwright_scaffold(self, project_id: str) -> Path:
        """Find any Playwright scaffold with node_modules installed."""
        candidates = [
            self.outputs_root / project_id / "03_framework" / "playwright",
            *sorted(self.outputs_root.glob("*/03_framework/playwright")),
        ]
        for candidate in candidates:
            if (candidate / "node_modules").exists():
                return candidate
        return self.outputs_root

    def _is_allowed_url(self, url: str) -> bool:
        if not url:
            return False
        lurl = url.lower()
        if any(s in lurl for s in _ALWAYS_BLOCKED_SUBSTRINGS):
            return False
        return any(lurl.startswith(p) for p in _ALLOWED_LOGIN_URL_PREFIXES)

    def _render_summary_md(
        self, plan: EmailPasswordPlan, result: EmailPasswordRunResult
    ) -> str:
        blockers_md = (
            "\n".join(f"- {b}" for b in result.blockers)
            if result.blockers
            else "_none_"
        )
        notes_md = (
            "\n".join(f"- {n}" for n in result.notes) if result.notes else "_none_"
        )
        return f"""# Email/Password Auth Smoke Summary

**Project:** `{result.project_id}`
**Target:** `{result.target_name}`
**Status:** `{result.status.value}`
**Login URL:** `{result.login_url}`
**Account label:** `{result.account_label or "(none)"}`
**Duration:** `{result.duration_seconds}s`

## Auth Coverage

{result.auth_coverage_summary}

## Env Var Status

| Var | Set |
|---|---|
| `{plan.username_env_var}` | `{plan.username_env_set}` |
| `{plan.password_env_var}` | `{plan.password_env_set}` |

## Safety Boundary

| Flag | Value |
|---|---|
| raw_secrets_allowed | `False` |
| credential_logging_allowed | `False` |
| personal_account_allowed | `False` |
| production_account_allowed | `False` |
| captcha_bypass_allowed | `False` |
| client_delivery_allowed | `False` |
| approved_for_client_delivery | `False` |
| human_review_required | `True` |

## Blockers

{blockers_md}

## Notes

{notes_md}
"""

    def _build_login_script(
        self,
        login_url: str,
        success_url: str,
        username_env_var: str,
        password_env_var: str,
    ) -> str:
        return f"""// Phase 7D -- Email/Password Login Smoke
// AUTO-GENERATED. Credentials read from process.env only. Never logged.
// Username env var: {username_env_var}
// Password env var: {password_env_var}

const {{ chromium }} = require('@playwright/test');

const LOGIN_URL = {json.dumps(login_url)};
const SUCCESS_URL = {json.dumps(success_url)};
const USERNAME_ENV_VAR = process.env.EP_USERNAME_ENV_VAR;
const PASSWORD_ENV_VAR = process.env.EP_PASSWORD_ENV_VAR;
const USERNAME = process.env[USERNAME_ENV_VAR];
const PASSWORD = process.env[PASSWORD_ENV_VAR];

if (!USERNAME || !PASSWORD) {{
  console.error('[7D] env_var_missing: ' + (!USERNAME ? USERNAME_ENV_VAR : PASSWORD_ENV_VAR));
  process.exit(2);
}}

(async () => {{
  const browser = await chromium.launch({{ headless: true }});
  const context = await browser.newContext({{ viewport: {{ width: 1280, height: 800 }} }});
  const page = await context.newPage();

  try {{
    await page.goto(LOGIN_URL, {{ waitUntil: 'domcontentloaded', timeout: 30000 }});
    console.log('[7D] login_page_loaded');
  }} catch (e) {{
    console.error('[7D] navigation_error=' + e.message);
    await browser.close();
    process.exit(1);
  }}

  try {{
    await page.fill('input[name="username"]', USERNAME);
    await page.fill('input[name="password"]', PASSWORD);
    await page.click('button[type="submit"]');
    console.log('[7D] credentials_submitted');
  }} catch (e) {{
    console.error('[7D] fill_error=' + e.message);
    await browser.close();
    process.exit(1);
  }}

  try {{
    await page.waitForURL('**' + SUCCESS_URL.split('/').pop() + '**', {{ timeout: 20000 }});
    console.log('[7D] login_success=true');
    console.log('[7D] url=' + page.url());
  }} catch (e) {{
    const currentUrl = page.url();
    console.error('[7D] login_success=false');
    console.error('[7D] url=' + currentUrl);
    console.error('[7D] waitForURL_error=' + e.message);
    await browser.close();
    process.exit(1);
  }}

  await browser.close();
  process.exit(0);
}})();
"""

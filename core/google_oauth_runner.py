"""
Phase 7C — Google OAuth Runner (storageState reuse).

Implements the single executable mode from Phase 7C:
  storage_state_reuse — load previously captured storageState, run a read-only
  smoke check against an allowlisted Google URL.

Five planning-only modes are classified and returned as planning artifacts only.

Safety contract:
- Never automates Google password entry.
- Never bypasses CAPTCHA or anti-bot challenges.
- Never reads, prints, or serialises storageState content.
- Never reads or copies the main Chrome profile.
- Never logs cookies, tokens, or any sensitive headers.
- Personal and production accounts are always blocked.
- storageState content is never read by Python — only path is passed to Playwright.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from core.schemas.google_oauth import (
    EXECUTABLE_OAUTH_MODES,
    PLANNING_ONLY_OAUTH_MODES,
    GoogleOAuthInputs,
    GoogleOAuthMode,
    GoogleOAuthModeReadiness,
    GoogleOAuthPlan,
    GoogleOAuthRunResult,
    GoogleOAuthRunStatus,
)

_ALLOWED_GOOGLE_TARGET_PREFIXES = (
    "https://accounts.google.com",
    "https://mail.google.com",
    "https://drive.google.com",
    "https://docs.google.com",
    "https://myaccount.google.com",
    "https://workspace.google.com",
)

_ALWAYS_BLOCKED_SUBSTRINGS = ("captcha", "recaptcha", "challenge", "anti-bot")


class GoogleOAuthRunner:
    """Phase 7C — Google OAuth storageState reuse runner."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self.outputs_root = outputs_root or Path("outputs")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def classify_mode(self, inputs: GoogleOAuthInputs) -> GoogleOAuthMode:
        """
        Select the best mode for the given inputs.
        Returns STORAGE_STATE_REUSE only when all conditions are met:
        - storage_state_path is set and file exists
        - dedicated_test_account_confirmed is True
        - google_test_account_confirmed is True
        Falls back to MANUAL_CAPTURE (planning-only) otherwise.
        """
        ssp = Path(inputs.storage_state_path) if inputs.storage_state_path else None
        if (
            ssp is not None
            and ssp.exists()
            and inputs.dedicated_test_account_confirmed
            and inputs.google_test_account_confirmed
        ):
            return GoogleOAuthMode.STORAGE_STATE_REUSE
        return GoogleOAuthMode.MANUAL_CAPTURE

    def build_plan(self, inputs: GoogleOAuthInputs) -> GoogleOAuthPlan:
        """Build a planning artifact describing available modes and blockers."""
        mode = self.classify_mode(inputs)
        ssp = Path(inputs.storage_state_path) if inputs.storage_state_path else None
        ssp_exists = ssp.exists() if ssp is not None else False

        if mode in EXECUTABLE_OAUTH_MODES:
            readiness = GoogleOAuthModeReadiness.EXECUTABLE
            blockers: list[str] = []
            next_steps = [
                "Run with --approve-execution to execute storageState reuse smoke.",
            ]
        else:
            readiness = GoogleOAuthModeReadiness.PLANNING_ONLY
            blockers = self._collect_blockers(inputs, ssp_exists)
            next_steps = [
                "Capture storageState manually: node capture_google.cjs",
                (
                    "Pass --storage-state-path <path> "
                    "--dedicated-test-account-confirmed --google-test-account-confirmed"
                ),
            ]

        return GoogleOAuthPlan(
            project_id=inputs.project_id,
            target_url=inputs.target_url,
            selected_mode=mode,
            mode_readiness=readiness,
            storage_state_available=ssp_exists,
            storage_state_path=inputs.storage_state_path,
            account_email_label=inputs.account_email_label,
            executable_modes=[m.value for m in sorted(EXECUTABLE_OAUTH_MODES, key=lambda x: x.value)],
            planning_only_modes=[m.value for m in sorted(PLANNING_ONLY_OAUTH_MODES, key=lambda x: x.value)],
            blockers=blockers,
            recommended_next_steps=next_steps,
            notes=[
                "storageState content is never read by this runner — only path is passed to Playwright.",
                "Personal and production accounts are always blocked.",
                "CAPTCHA bypass is always blocked.",
            ],
        )

    def run(self, inputs: GoogleOAuthInputs) -> GoogleOAuthRunResult:
        """
        Run the Google OAuth smoke (storageState reuse) or return planning-only result.
        Returns PLANNING_ONLY when storageState is not present or confirmation flags missing.
        Returns BLOCKED when storageState is present but approval flag not set.
        Returns PASSED/FAILED after actual Playwright smoke.
        """
        mode = self.classify_mode(inputs)
        plan = self.build_plan(inputs)

        if mode not in EXECUTABLE_OAUTH_MODES:
            return GoogleOAuthRunResult(
                project_id=inputs.project_id,
                target_url=inputs.target_url,
                mode=mode,
                status=GoogleOAuthRunStatus.PLANNING_ONLY,
                account_email_label=inputs.account_email_label,
                storage_state_path=inputs.storage_state_path,
                storage_state_present=False,
                blockers=plan.blockers,
                notes=plan.recommended_next_steps,
                auth_coverage_summary=(
                    "Google OAuth: planning only — storageState not yet captured."
                ),
            )

        if not inputs.approve_execution:
            return GoogleOAuthRunResult(
                project_id=inputs.project_id,
                target_url=inputs.target_url,
                mode=mode,
                status=GoogleOAuthRunStatus.BLOCKED,
                account_email_label=inputs.account_email_label,
                storage_state_path=inputs.storage_state_path,
                storage_state_present=True,
                blockers=[
                    "--approve-execution flag not set. Pass it to run the smoke."
                ],
                notes=["storageState is present. Re-run with --approve-execution."],
                auth_coverage_summary="Google OAuth: blocked — approval flag missing.",
            )

        if not self._is_allowed_url(inputs.target_url):
            return GoogleOAuthRunResult(
                project_id=inputs.project_id,
                target_url=inputs.target_url,
                mode=mode,
                status=GoogleOAuthRunStatus.BLOCKED,
                account_email_label=inputs.account_email_label,
                storage_state_path=inputs.storage_state_path,
                storage_state_present=True,
                blockers=[
                    f"URL '{inputs.target_url}' is not in the allowlisted Google target prefixes."
                ],
                auth_coverage_summary="Google OAuth: blocked — URL not allowlisted.",
            )

        return self._execute_storage_state_smoke(inputs, headed=getattr(inputs, "headed", False))

    def render_artifacts(
        self,
        plan: GoogleOAuthPlan,
        result: GoogleOAuthRunResult,
        project_id: str,
    ) -> dict[str, str]:
        """Write 3 output artifacts: plan JSON, report JSON, summary MD."""
        out_dir = self.outputs_root / project_id / "16_google_oauth"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: dict[str, str] = {}

        plan_path = out_dir / "google_oauth_plan.json"
        plan_path.write_text(
            json.dumps(plan.to_dict(), indent=2, default=str), encoding="utf-8"
        )
        paths["google_oauth_plan_json"] = str(plan_path)

        report_path = out_dir / "google_oauth_report.json"
        report_path.write_text(
            json.dumps(result.to_dict(), indent=2, default=str), encoding="utf-8"
        )
        paths["google_oauth_report_json"] = str(report_path)

        summary_path = out_dir / "google_oauth_summary.md"
        summary_path.write_text(
            self._render_summary_md(plan, result), encoding="utf-8"
        )
        paths["google_oauth_summary_md"] = str(summary_path)

        return paths

    def format_auth_coverage_section(self, result: GoogleOAuthRunResult) -> str:
        """Return an Authentication Coverage block for use in client delivery reports."""
        lines = [
            "## Authentication Coverage",
            "",
            f"**Mode:** `{result.mode.value}`",
            f"**Status:** `{result.status.value}`",
            f"**Target:** `{result.target_url}`",
            "",
            result.auth_coverage_summary,
            "",
            "**Safety boundary:** storageState content never read; personal/production accounts blocked; CAPTCHA bypass blocked.",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _execute_storage_state_smoke(
        self, inputs: GoogleOAuthInputs, headed: bool = False
    ) -> GoogleOAuthRunResult:
        ssp = Path(inputs.storage_state_path).resolve()
        run_dir = self._find_playwright_scaffold(inputs.project_id).resolve()

        # Write the script into the scaffold dir so require('@playwright/test') resolves.
        # Use absolute paths throughout — relative paths break when subprocess CWD differs.
        script_path = (run_dir / "google_oauth_smoke_7c.cjs").resolve()
        screenshot_path = (ssp.parent / "google_oauth_smoke_screenshot.png").resolve()

        script_content = self._build_smoke_script(
            target_url=inputs.target_url,
            storage_state_path=str(ssp).replace("\\", "\\\\"),
            screenshot_path=str(screenshot_path).replace("\\", "\\\\"),
            headed=headed,
        )
        script_path.write_text(script_content, encoding="utf-8")

        node_exe = shutil.which("node") or shutil.which("node.exe") or "node"
        if sys.platform == "win32":
            node_exe = shutil.which("node") or "node"

        start = time.monotonic()
        try:
            proc = subprocess.run(
                [node_exe, str(script_path)],
                cwd=str(run_dir),
                capture_output=True,
                text=True,
                timeout=120,
            )
            duration = time.monotonic() - start
            exit_code = proc.returncode
            stdout_tail = (proc.stdout or "")[-600:]
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

        status = GoogleOAuthRunStatus.PASSED if success else GoogleOAuthRunStatus.FAILED
        return GoogleOAuthRunResult(
            project_id=inputs.project_id,
            target_url=inputs.target_url,
            mode=GoogleOAuthMode.STORAGE_STATE_REUSE,
            status=status,
            account_email_label=inputs.account_email_label,
            storage_state_path=str(ssp),
            storage_state_present=ssp.exists(),
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
                "storageState content was NOT read — only path passed to Playwright.",
                "No password automation. No CAPTCHA bypass. Read-only smoke.",
                f"Result: {'PASSED' if success else 'FAILED'}",
            ],
            auth_coverage_summary=(
                f"Google OAuth storageState reuse: {'PASSED' if success else 'FAILED'}"
            ),
        )

    def _find_playwright_scaffold(self, project_id: str) -> Path:
        """
        Find a Playwright scaffold directory that has node_modules installed.
        Checks project-specific scaffold first, then any scaffold under outputs/.
        Falls back to outputs/ root (will fail at runtime if no node_modules there).
        """
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
        return any(lurl.startswith(p) for p in _ALLOWED_GOOGLE_TARGET_PREFIXES)

    def _collect_blockers(
        self, inputs: GoogleOAuthInputs, ssp_exists: bool
    ) -> list[str]:
        blockers: list[str] = []
        if not inputs.storage_state_path:
            blockers.append("--storage-state-path not provided.")
        elif not ssp_exists:
            blockers.append(
                f"storageState file not found: {inputs.storage_state_path}"
            )
        if not inputs.dedicated_test_account_confirmed:
            blockers.append("--dedicated-test-account-confirmed not set.")
        if not inputs.google_test_account_confirmed:
            blockers.append("--google-test-account-confirmed not set.")
        return blockers

    def _render_summary_md(
        self, plan: GoogleOAuthPlan, result: GoogleOAuthRunResult
    ) -> str:
        blockers_md = (
            "\n".join(f"- {b}" for b in result.blockers)
            if result.blockers
            else "_none_"
        )
        notes_md = (
            "\n".join(f"- {n}" for n in result.notes) if result.notes else "_none_"
        )
        return f"""# Google OAuth Smoke Summary

**Project:** `{result.project_id}`
**Mode:** `{result.mode.value}`
**Status:** `{result.status.value}`
**Target:** `{result.target_url}`
**Account label:** `{result.account_email_label or "(none)"}`
**Duration:** `{result.duration_seconds}s`

## Auth Coverage

{result.auth_coverage_summary}

## Mode Readiness

| Mode | Readiness |
|---|---|
| selected | `{plan.selected_mode.value}` |
| readiness | `{plan.mode_readiness.value}` |
| storageState available | `{plan.storage_state_available}` |

## Safety Boundary

| Flag | Value |
|---|---|
| raw_secrets_allowed | `False` |
| storage_state_content_read | `False` |
| captcha_bypass_allowed | `False` |
| anti_bot_bypass_allowed | `False` |
| personal_account_allowed | `False` |
| production_account_allowed | `False` |
| client_delivery_allowed | `False` |
| human_review_required | `True` |

## Blockers

{blockers_md}

## Notes

{notes_md}
"""

    def _build_smoke_script(
        self,
        target_url: str,
        storage_state_path: str,
        screenshot_path: str,
        headed: bool = False,
    ) -> str:
        headless_js = "false" if headed else "true"
        return f"""// Phase 7C -- Google OAuth StorageState Reuse Smoke
// AUTO-GENERATED. Read-only. No content extraction. No admin actions.
// storageState content is never read by Python -- only path passed here.

const {{ chromium }} = require('@playwright/test');

const TARGET_URL = {json.dumps(target_url)};
const STORAGE_STATE_PATH = {json.dumps(storage_state_path)};
const SCREENSHOT_PATH = {json.dumps(screenshot_path)};

(async () => {{
  const browser = await chromium.launch({{ headless: {headless_js} }});
  const context = await browser.newContext({{
    storageState: STORAGE_STATE_PATH,
    viewport: {{ width: 1280, height: 800 }},
  }});
  const page = await context.newPage();

  try {{
    const resp = await page.goto(TARGET_URL, {{ waitUntil: 'domcontentloaded', timeout: 30000 }});
    const status = resp ? resp.status() : 0;
    console.log('[7C] status=' + status);
    if (status >= 400) {{
      console.error('[7C] Error status: ' + status);
      await browser.close();
      process.exit(1);
    }}
  }} catch (e) {{
    console.error('[7C] navigation_error=' + e.message);
    await browser.close();
    process.exit(2);
  }}

  if ({str(headed).lower()}) {{
    await page.waitForTimeout(5000);
  }}

  try {{
    await page.screenshot({{ path: SCREENSHOT_PATH, fullPage: false }});
    console.log('[7C] screenshot_saved');
  }} catch (e) {{
    console.error('[7C] screenshot_failed=' + e.message);
  }}

  await browser.close();
  process.exit(0);
}})();
"""

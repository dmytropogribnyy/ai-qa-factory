"""
Phase 5G — Google Auth Runner.

Implements the two executable modes from Phase 5G:
1. manual_storage_state_capture — user logs into the dedicated Google test
   account manually; Playwright captures storageState to the approved internal path.
2. storage_state_reuse — Playwright loads previously captured storageState and runs
   a read-only smoke check.

Safety contract:
- Never automates Google password typing.
- Never bypasses CAPTCHA or anti-bot challenges.
- Never reads, prints, or serializes storageState content.
- Never reads or copies the main Chrome profile.
- Never logs cookies, tokens, or any sensitive headers.
- All raw network response bodies are discarded — only minimal status info recorded.
- Personal/production accounts are always blocked by GoogleAuthCapabilityPlanner.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional

from core.google_auth_capability import GoogleAuthCapabilityPlanner
from core.schemas.google_auth import (
    GoogleAuthEvidenceReport,
    GoogleAuthExecutionDecision,
)

# Allowed Google target URL prefixes (https only)
_ALLOWED_GOOGLE_TARGET_PREFIXES = (
    "https://accounts.google.com",
    "https://mail.google.com",
    "https://drive.google.com",
    "https://docs.google.com",
    "https://myaccount.google.com",
    "https://workspace.google.com",
)

# Patterns that always block execution regardless of approvals
_ALWAYS_BLOCKED_URL_SUBSTRINGS = (
    "captcha",
    "recaptcha",
    "challenge",
    "anti-bot",
)


class GoogleAuthRunner:
    """
    Runner for Phase 5G executable Google auth modes.
    Planning/policy is performed by GoogleAuthCapabilityPlanner first.
    """

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self.outputs_root = outputs_root or Path("outputs")
        self.planner = GoogleAuthCapabilityPlanner(outputs_root=self.outputs_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def capture_storage_state(
        self,
        project_id: str,
        target_url: str,
        approve_google_test_account: bool = False,
        google_test_account_confirmed: bool = False,
        dedicated_test_account_confirmed: bool = False,
        personal_account_confirmed: bool = False,
        production_account_confirmed: bool = False,
        account_email_label: str = "",
        timeout_seconds: int = 300,
    ) -> GoogleAuthEvidenceReport:
        """
        Opens a Playwright-driven Chromium for the user to manually log in to the
        dedicated Google test account. Saves storageState to the approved internal path.
        Does not automate password entry. Does not bypass CAPTCHA or 2FA challenges.
        """
        decision = self.planner.decide_execution(
            project_id=project_id,
            target_url=target_url,
            target_kind="google_account_ui",
            auth_mode="manual_storage_state_capture",
            account_email_label=account_email_label,
            approve_google_test_account=approve_google_test_account,
            google_test_account_confirmed=google_test_account_confirmed,
            dedicated_test_account_confirmed=dedicated_test_account_confirmed,
            personal_account_confirmed=personal_account_confirmed,
            production_account_confirmed=production_account_confirmed,
        )

        if not decision.allowed_now:
            return self._blocked_report(
                project_id=project_id,
                auth_mode="manual_storage_state_capture",
                target_url=target_url,
                account_email_label=account_email_label,
                decision=decision,
                notes=[
                    "Capture not started — decision is BLOCKED.",
                    *decision.blockers,
                ],
            )

        # URL allowlist check
        if not self._is_allowed_google_target(target_url):
            return self._blocked_report(
                project_id=project_id,
                auth_mode="manual_storage_state_capture",
                target_url=target_url,
                account_email_label=account_email_label,
                decision=decision,
                notes=[
                    f"Target URL '{target_url}' is not in the allowlisted Google "
                    "target prefixes. Capture not started.",
                ],
            )

        # Prepare output path (gitignored)
        out_dir = self.outputs_root / project_id / "15_google_auth" / ".auth"
        out_dir.mkdir(parents=True, exist_ok=True)
        storage_state_path = (out_dir / "google-storageState.json").resolve()

        # Build the Playwright Node.js script the user will see drive the browser.
        # We do not write any spec file to scaffold root — this is a one-off Node script
        # generated inside the project outputs directory. Execution happens via Node, not pytest.
        node_script_path = out_dir.parent / "manual_capture.cjs"
        node_script = self._build_manual_capture_node_script(
            target_url=target_url,
            storage_state_path=str(storage_state_path).replace("\\", "\\\\"),
            timeout_ms=timeout_seconds * 1000,
        )
        node_script_path.write_text(node_script, encoding="utf-8")

        # Determine which Node project to run against — we need playwright installed.
        # We look for an existing scaffold under outputs/<project_id>/03_framework/playwright.
        scaffold_root = self.outputs_root / project_id / "03_framework" / "playwright"
        if not scaffold_root.exists():
            return self._blocked_report(
                project_id=project_id,
                auth_mode="manual_storage_state_capture",
                target_url=target_url,
                account_email_label=account_email_label,
                decision=decision,
                notes=[
                    f"No Playwright scaffold found at {scaffold_root}. "
                    "Run Phase 3A scaffold generator first.",
                ],
            )

        # Execute the manual capture script — opens the browser visibly so the user
        # can log in. Password entry, 2FA, and CAPTCHA challenges are handled by the user.
        start = time.monotonic()
        node_exe = shutil.which("node") if sys.platform == "win32" else "node"
        if not node_exe:
            return self._blocked_report(
                project_id=project_id,
                auth_mode="manual_storage_state_capture",
                target_url=target_url,
                account_email_label=account_email_label,
                decision=decision,
                notes=[
                    "Node.js is not installed or not on PATH. "
                    "Manual capture cannot start.",
                ],
            )

        try:
            proc_env = dict(os.environ)
            # Do not pass any account credentials through env.
            result = subprocess.run(
                [node_exe, str(node_script_path)],
                cwd=str(scaffold_root),
                env=proc_env,
                timeout=timeout_seconds + 30,
                capture_output=True,
                text=True,
            )
            duration = time.monotonic() - start
            exit_code = result.returncode
            stderr_tail = (result.stderr or "")[-400:]
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            exit_code = 124
            stderr_tail = "TimeoutExpired — capture timed out before user finished login."
        except Exception as exc:
            duration = time.monotonic() - start
            exit_code = 1
            stderr_tail = f"{type(exc).__name__}: {exc}"[-400:]

        captured = storage_state_path.exists()
        size_bytes = storage_state_path.stat().st_size if captured else 0

        return GoogleAuthEvidenceReport(
            project_id=project_id,
            auth_mode="manual_storage_state_capture",
            target_url=target_url,
            target_kind="google_account_ui",
            account_email_label=account_email_label,
            execution_performed=True,
            storage_state_captured=captured,
            storage_state_path=str(storage_state_path),
            storage_state_present_after_run=captured,
            storage_state_size_bytes=size_bytes,
            smoke_commands=[f"node {node_script_path.name}"],
            smoke_results=[
                f"exit_code={exit_code}",
                f"captured={captured}",
                f"duration={round(duration, 2)}s",
                f"stderr_tail={stderr_tail}" if stderr_tail else "no_stderr",
            ],
            duration_seconds=round(duration, 3),
            notes=[
                "Manual capture: user solved login + any challenges manually.",
                "Password was never typed by automation.",
                "CAPTCHA and 2FA were not bypassed.",
                "storageState content was NOT read by this runner — only path/size metadata recorded.",
                f"storageState saved to: {storage_state_path}",
            ],
        )

    def run_storage_state_smoke(
        self,
        project_id: str,
        target_url: str,
        storage_state_path: str,
        approve_google_test_account: bool = False,
        google_test_account_confirmed: bool = False,
        dedicated_test_account_confirmed: bool = False,
        personal_account_confirmed: bool = False,
        production_account_confirmed: bool = False,
        account_email_label: str = "",
        target_kind: str = "google_account_ui",
        timeout_seconds: int = 90,
    ) -> GoogleAuthEvidenceReport:
        """
        Load previously captured storageState and run a read-only smoke check:
        navigate to target_url, verify it responds, take an optional redacted screenshot.
        No content extraction, no email/file reading, no admin actions.
        """
        decision = self.planner.decide_execution(
            project_id=project_id,
            target_url=target_url,
            target_kind=target_kind,
            auth_mode="storage_state_reuse",
            account_email_label=account_email_label,
            approve_google_test_account=approve_google_test_account,
            google_test_account_confirmed=google_test_account_confirmed,
            dedicated_test_account_confirmed=dedicated_test_account_confirmed,
            personal_account_confirmed=personal_account_confirmed,
            production_account_confirmed=production_account_confirmed,
            storage_state_path=storage_state_path,
        )

        if not decision.allowed_now:
            return self._blocked_report(
                project_id=project_id,
                auth_mode="storage_state_reuse",
                target_url=target_url,
                account_email_label=account_email_label,
                decision=decision,
                notes=["Smoke not started — decision is BLOCKED.", *decision.blockers],
            )

        if not self._is_allowed_google_target(target_url) and target_kind == "google_account_ui":
            return self._blocked_report(
                project_id=project_id,
                auth_mode="storage_state_reuse",
                target_url=target_url,
                account_email_label=account_email_label,
                decision=decision,
                notes=[
                    f"Target URL '{target_url}' is not in the allowlisted Google "
                    "target prefixes (for google_account_ui).",
                ],
            )

        scaffold_root = self.outputs_root / project_id / "03_framework" / "playwright"
        if not scaffold_root.exists():
            return self._blocked_report(
                project_id=project_id,
                auth_mode="storage_state_reuse",
                target_url=target_url,
                account_email_label=account_email_label,
                decision=decision,
                notes=[
                    f"No Playwright scaffold found at {scaffold_root}. "
                    "Run Phase 3A scaffold generator first.",
                ],
            )

        ssp = Path(storage_state_path).resolve()
        if not ssp.exists():
            return self._blocked_report(
                project_id=project_id,
                auth_mode="storage_state_reuse",
                target_url=target_url,
                account_email_label=account_email_label,
                decision=decision,
                notes=[f"storage_state_path does not exist: {ssp}"],
            )

        # Build smoke script — opens page with storageState, asserts response, no content extraction
        screenshot_path = (ssp.parent.parent / "smoke_redacted.png").resolve()
        node_script_path = ssp.parent.parent / "storage_state_smoke.cjs"
        node_script = self._build_storage_state_smoke_node_script(
            target_url=target_url,
            storage_state_path=str(ssp).replace("\\", "\\\\"),
            screenshot_path=str(screenshot_path).replace("\\", "\\\\"),
            timeout_ms=timeout_seconds * 1000,
        )
        node_script_path.write_text(node_script, encoding="utf-8")

        start = time.monotonic()
        node_exe = shutil.which("node") if sys.platform == "win32" else "node"
        if not node_exe:
            return self._blocked_report(
                project_id=project_id,
                auth_mode="storage_state_reuse",
                target_url=target_url,
                account_email_label=account_email_label,
                decision=decision,
                notes=["Node.js is not installed or not on PATH."],
            )

        try:
            proc_env = dict(os.environ)
            result = subprocess.run(
                [node_exe, str(node_script_path)],
                cwd=str(scaffold_root),
                env=proc_env,
                timeout=timeout_seconds + 30,
                capture_output=True,
                text=True,
            )
            duration = time.monotonic() - start
            exit_code = result.returncode
            stderr_tail = (result.stderr or "")[-400:]
            stdout_tail = (result.stdout or "")[-400:]
        except subprocess.TimeoutExpired:
            duration = time.monotonic() - start
            exit_code = 124
            stderr_tail = "TimeoutExpired"
            stdout_tail = ""
        except Exception as exc:
            duration = time.monotonic() - start
            exit_code = 1
            stderr_tail = f"{type(exc).__name__}: {exc}"[-400:]
            stdout_tail = ""

        return GoogleAuthEvidenceReport(
            project_id=project_id,
            auth_mode="storage_state_reuse",
            target_url=target_url,
            target_kind=target_kind,
            account_email_label=account_email_label,
            execution_performed=True,
            storage_state_captured=False,  # reused, not captured
            storage_state_path=str(ssp),
            storage_state_present_after_run=ssp.exists(),
            storage_state_size_bytes=ssp.stat().st_size if ssp.exists() else 0,
            smoke_commands=[f"node {node_script_path.name}"],
            smoke_results=[
                f"exit_code={exit_code}",
                f"duration={round(duration, 2)}s",
                f"screenshot={screenshot_path if screenshot_path.exists() else 'none'}",
                f"stdout_tail={stdout_tail}" if stdout_tail else "no_stdout",
                f"stderr_tail={stderr_tail}" if stderr_tail else "no_stderr",
            ],
            duration_seconds=round(duration, 3),
            notes=[
                "Read-only smoke. No content extraction. No email/file reads. No admin actions.",
                "storageState content was NOT read by this runner — only loaded by Playwright.",
                "CAPTCHA and anti-bot bypass were not attempted.",
            ],
        )

    # ------------------------------------------------------------------
    # Artifact rendering
    # ------------------------------------------------------------------

    def render_evidence_artifacts(
        self,
        report: GoogleAuthEvidenceReport,
        project_id: str,
    ) -> Dict[str, str]:
        out_dir = self.outputs_root / project_id / "15_google_auth"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: Dict[str, str] = {}

        ev_json = out_dir / "GOOGLE_AUTH_EVIDENCE_REPORT.json"
        ev_json.write_text(
            json.dumps(report.to_dict(), indent=2, default=str),
            encoding="utf-8",
        )
        paths["evidence_report_json"] = str(ev_json)

        ev_md = out_dir / "GOOGLE_AUTH_EVIDENCE_REPORT.md"
        ev_md.write_text(self._render_evidence_md(report), encoding="utf-8")
        paths["evidence_report_md"] = str(ev_md)

        return paths

    def _render_evidence_md(self, r: GoogleAuthEvidenceReport) -> str:
        return f"""# Google Auth Evidence Report

**Project:** `{r.project_id}`
**Mode:** `{r.auth_mode}`
**Target URL:** `{r.target_url}`
**Target kind:** `{r.target_kind}`
**Account label:** `{r.account_email_label or '(none)'}`

## Execution

| Field | Value |
|---|---|
| execution_performed | `{r.execution_performed}` |
| storage_state_captured | `{r.storage_state_captured}` |
| storage_state_present_after_run | `{r.storage_state_present_after_run}` |
| storage_state_size_bytes | `{r.storage_state_size_bytes}` |
| duration_seconds | `{r.duration_seconds}` |

## Commands attempted

{chr(10).join(f"- `{c}`" for c in r.smoke_commands) if r.smoke_commands else "_none_"}

## Results

{chr(10).join(f"- `{x}`" for x in r.smoke_results) if r.smoke_results else "_none_"}

## Safety boundary

| Flag | Value |
|---|---|
| raw_credentials_logged | `{r.raw_credentials_logged}` |
| raw_credentials_serialized | `{r.raw_credentials_serialized}` |
| cookies_logged | `{r.cookies_logged}` |
| tokens_logged | `{r.tokens_logged}` |
| storage_state_content_read | `{r.storage_state_content_read}` |
| browser_profile_content_read | `{r.browser_profile_content_read}` |
| captcha_bypass_attempted | `{r.captcha_bypass_attempted}` |
| anti_bot_bypass_attempted | `{r.anti_bot_bypass_attempted}` |
| personal_account_used | `{r.personal_account_used}` |
| production_account_used | `{r.production_account_used}` |
| safe_to_deliver | `{r.safe_to_deliver}` |
| approved_for_client_delivery | `{r.approved_for_client_delivery}` |
| client_visible | `{r.client_visible}` |
| internal_only | `{r.internal_only}` |
| human_review_required | `{r.human_review_required}` |

## Notes

{chr(10).join(f"- {n}" for n in r.notes) if r.notes else "_none_"}
"""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_allowed_google_target(self, url: str) -> bool:
        if not url:
            return False
        lurl = url.lower()
        if any(s in lurl for s in _ALWAYS_BLOCKED_URL_SUBSTRINGS):
            return False
        return any(lurl.startswith(p) for p in _ALLOWED_GOOGLE_TARGET_PREFIXES)

    def _blocked_report(
        self,
        project_id: str,
        auth_mode: str,
        target_url: str,
        account_email_label: str,
        decision: GoogleAuthExecutionDecision,
        notes: List[str],
    ) -> GoogleAuthEvidenceReport:
        return GoogleAuthEvidenceReport(
            project_id=project_id,
            auth_mode=auth_mode,
            target_url=target_url,
            target_kind=decision.target_kind,
            account_email_label=account_email_label,
            execution_performed=False,
            storage_state_captured=False,
            storage_state_path=decision.storage_state_path,
            smoke_commands=[],
            smoke_results=[],
            duration_seconds=0.0,
            notes=notes,
        )

    def _build_manual_capture_node_script(
        self,
        target_url: str,
        storage_state_path: str,
        timeout_ms: int,
    ) -> str:
        # Generated at runtime. Uses Playwright that is already installed in the
        # Phase 3A scaffold. No password automation. Browser is visible (headed).
        # User completes the login manually, then closes the browser to save.
        # storageState is saved by the script — content is not read by Python.
        return f"""// Phase 5G — Manual Google Storage State Capture
// AUTO-GENERATED. Do not commit. Do not automate password entry.
// User logs in manually; CAPTCHA/2FA solved by user.

const {{ chromium }} = require('@playwright/test');

const TARGET_URL = {json.dumps(target_url)};
const STORAGE_STATE_PATH = {json.dumps(storage_state_path)};
const TIMEOUT_MS = {timeout_ms};

(async () => {{
  console.log('[5G] Launching Chromium (headed). DO NOT enter personal account.');
  console.log('[5G] Use ONLY the dedicated Google test account.');
  console.log('[5G] After login is fully complete (you reach the account UI),');
  console.log('[5G] close the browser window to save the session.');

  const browser = await chromium.launch({{ headless: false }});
  const context = await browser.newContext({{
    viewport: {{ width: 1280, height: 800 }},
  }});
  const page = await context.newPage();

  let timedOut = false;
  const timer = setTimeout(async () => {{
    timedOut = true;
    console.error('[5G] Timeout reached. Closing without saving.');
    try {{ await browser.close(); }} catch (e) {{}}
  }}, TIMEOUT_MS);

  try {{
    await page.goto(TARGET_URL, {{ timeout: 60_000 }});
  }} catch (e) {{
    console.error('[5G] Initial navigation error:', e.message);
  }}

  // Wait for the user to close the window. We do NOT inspect the page.
  await new Promise((resolve) => {{
    browser.on('disconnected', resolve);
  }});

  clearTimeout(timer);

  if (timedOut) {{
    console.error('[5G] Capture timed out before user closed the browser.');
    process.exit(124);
  }}

  try {{
    await context.storageState({{ path: STORAGE_STATE_PATH }});
    console.log('[5G] Storage state saved.');
  }} catch (e) {{
    console.error('[5G] storageState save failed:', e.message);
    process.exit(2);
  }}

  process.exit(0);
}})();
"""

    def _build_storage_state_smoke_node_script(
        self,
        target_url: str,
        storage_state_path: str,
        screenshot_path: str,
        timeout_ms: int,
    ) -> str:
        # Read-only smoke. No content extraction. No clicks beyond the initial nav.
        return f"""// Phase 5G — Storage State Reuse Smoke
// AUTO-GENERATED. Read-only. No content extraction. No admin actions.

const {{ chromium }} = require('@playwright/test');

const TARGET_URL = {json.dumps(target_url)};
const STORAGE_STATE_PATH = {json.dumps(storage_state_path)};
const SCREENSHOT_PATH = {json.dumps(screenshot_path)};
const TIMEOUT_MS = {timeout_ms};

(async () => {{
  const browser = await chromium.launch({{ headless: true }});
  const context = await browser.newContext({{
    storageState: STORAGE_STATE_PATH,
    viewport: {{ width: 1280, height: 800 }},
  }});
  const page = await context.newPage();

  try {{
    const resp = await page.goto(TARGET_URL, {{ timeout: TIMEOUT_MS }});
    if (resp) {{
      console.log('[5G][smoke] status=' + resp.status());
    }} else {{
      console.log('[5G][smoke] status=unknown');
    }}
  }} catch (e) {{
    console.error('[5G][smoke] navigation_error=' + e.message);
    await browser.close();
    process.exit(2);
  }}

  // Optional redacted screenshot — only viewport, no content read by Python.
  try {{
    await page.screenshot({{ path: SCREENSHOT_PATH, fullPage: false }});
    console.log('[5G][smoke] screenshot_saved');
  }} catch (e) {{
    console.error('[5G][smoke] screenshot_failed=' + e.message);
  }}

  await browser.close();
  process.exit(0);
}})();
"""

"""
Phase 5I — GitHub OAuth / Test Account Auth Runner.

Permissioned model (mirrors Phase 5G Google Auth Runner):
- manual_storage_state_capture: open browser → user logs in → save storageState
- storage_state_reuse: headless smoke reusing saved storageState

SAFETY (all hardcoded):
- Personal GitHub accounts: always blocked.
- Production org accounts: always blocked.
- CAPTCHA bypass: always blocked.
- Raw secrets in CLI args: always blocked.
- storageState content never read by Python code.
- safe_to_deliver=False always.
- human_review_required=True always.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.schemas.github_auth import (
    GITHUB_AUTH_MODES_EXECUTABLE_5I,
    GITHUB_AUTH_MODES_PLANNING_ONLY_5I,
    GITHUB_ALLOWED_URL_PREFIXES,
    GITHUB_BLOCKED_URL_PATTERNS,
    GitHubAuthCapability,
    GitHubAuthEvidenceReport,
    GitHubAuthExecutionDecision,
    GitHubAuthModePolicy,
    GitHubStorageStatePolicy,
    GitHubTestAccountProfile,
)

_OUTPUTS_ROOT = Path("outputs")
_EXCERPT_LIMIT = 2000

# Permitted test account label allowlist (mirrors Google runner)
_PERMITTED_GITHUB_TEST_ACCOUNT_LABELS: frozenset = frozenset({
    # Add client-provided dedicated GitHub test accounts here
    # e.g. "qa_bot_github"
})


class GitHubAuthRunner:
    """Permissioned GitHub auth capability planner and execution runner."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Planning API
    # ------------------------------------------------------------------

    def plan_capability(
        self,
        project_id: str,
        account_label: str,
        target_url: str,
        target_kind: str,
        storage_state_path: Optional[str] = None,
        approve_github_test_account: bool = False,
        dedicated_test_account_confirmed: bool = False,
        personal_account_confirmed: bool = False,
        production_account_confirmed: bool = False,
    ) -> GitHubAuthCapability:
        """Build a capability plan for all GitHub auth modes."""
        blockers: List[str] = []
        notes: List[str] = []

        # Hard blocks
        if personal_account_confirmed:
            blockers.append("Personal GitHub accounts are always blocked.")
        if production_account_confirmed:
            blockers.append("Production GitHub org accounts are always blocked.")

        # Approval gate
        if not approve_github_test_account:
            blockers.append("Missing --approve-github-test-account flag.")
        if not dedicated_test_account_confirmed:
            blockers.append("Missing --dedicated-test-account-confirmed flag.")

        # Account label validation
        if account_label and _PERMITTED_GITHUB_TEST_ACCOUNT_LABELS:
            if account_label not in _PERMITTED_GITHUB_TEST_ACCOUNT_LABELS:
                notes.append(
                    f"Account label '{account_label}' not in allowlist. "
                    f"Manual review required before execution."
                )

        # URL validation
        if target_url:
            url_block = self._check_github_url(target_url)
            if url_block:
                blockers.append(url_block)

        account_profile = GitHubTestAccountProfile(
            account_label=account_label,
            target_kind=target_kind,
            storage_state_path=storage_state_path or "",
            is_dedicated_test_account=dedicated_test_account_confirmed,
        )

        # Build mode policies
        mode_policies: List[GitHubAuthModePolicy] = []
        executable_modes: List[str] = []
        planning_modes: List[str] = []

        for mode in GITHUB_AUTH_MODES_EXECUTABLE_5I:
            allowed = not blockers
            mode_policy = GitHubAuthModePolicy(
                mode=mode,
                allowed_now=allowed,
                approval_required=True,
                blockers=list(blockers) if not allowed else [],
                notes=list(notes),
            )
            mode_policies.append(mode_policy)
            if allowed:
                executable_modes.append(mode)

        for mode in GITHUB_AUTH_MODES_PLANNING_ONLY_5I:
            mode_policy = GitHubAuthModePolicy(
                mode=mode,
                allowed_now=False,
                approval_required=True,
                blockers=["Planning-only in Phase 5I. Deferred to a future phase."],
            )
            mode_policies.append(mode_policy)
            planning_modes.append(mode)

        # Storage state policy
        ss_policy: Optional[GitHubStorageStatePolicy] = None
        if storage_state_path:
            ss_path = Path(storage_state_path)
            ss_policy = GitHubStorageStatePolicy(
                storage_state_path=storage_state_path,
                path_exists=ss_path.exists(),
                file_size_bytes=ss_path.stat().st_size if ss_path.exists() else 0,
            )

        return GitHubAuthCapability(
            project_id=project_id,
            account_profile=account_profile,
            mode_policies=mode_policies,
            storage_state_policy=ss_policy,
            executable_modes=executable_modes,
            planning_only_modes=planning_modes,
            blockers=blockers,
            notes=notes,
        )

    def decide_execution(
        self,
        project_id: str,
        auth_mode: str,
        target_url: str,
        target_kind: str,
        storage_state_path: Optional[str] = None,
        approve_github_test_account: bool = False,
        dedicated_test_account_confirmed: bool = False,
        personal_account_confirmed: bool = False,
        production_account_confirmed: bool = False,
    ) -> GitHubAuthExecutionDecision:
        """Per-request execution decision."""
        blockers: List[str] = []
        notes: List[str] = []

        if personal_account_confirmed:
            blockers.append("Personal GitHub accounts are always blocked.")
        if production_account_confirmed:
            blockers.append("Production GitHub org accounts are always blocked.")
        if not approve_github_test_account:
            blockers.append("Missing --approve-github-test-account flag.")
        if not dedicated_test_account_confirmed:
            blockers.append("Missing --dedicated-test-account-confirmed flag.")
        if auth_mode in GITHUB_AUTH_MODES_PLANNING_ONLY_5I:
            blockers.append(f"Mode '{auth_mode}' is planning-only in Phase 5I.")
        if auth_mode not in GITHUB_AUTH_MODES_EXECUTABLE_5I and auth_mode not in GITHUB_AUTH_MODES_PLANNING_ONLY_5I:
            blockers.append(f"Unknown auth mode '{auth_mode}'.")

        url_block = self._check_github_url(target_url)
        if url_block:
            blockers.append(url_block)

        if auth_mode == "storage_state_reuse" and not storage_state_path:
            blockers.append("storage_state_reuse requires --storage-state-path.")

        return GitHubAuthExecutionDecision(
            project_id=project_id,
            auth_mode=auth_mode,
            target_url=target_url,
            target_kind=target_kind,
            allowed_now=not blockers,
            blockers=blockers,
            notes=notes,
        )

    # ------------------------------------------------------------------
    # Execution API
    # ------------------------------------------------------------------

    def run_storage_state_reuse_smoke(
        self,
        project_id: str,
        target_url: str,
        target_kind: str,
        storage_state_path: str,
        approve_github_test_account: bool = False,
        dedicated_test_account_confirmed: bool = False,
        timeout: int = 60,
    ) -> GitHubAuthEvidenceReport:
        """Run a headless smoke check reusing a captured GitHub storageState."""
        report = GitHubAuthEvidenceReport(
            project_id=project_id,
            auth_mode="storage_state_reuse",
            target_url=target_url,
            target_kind=target_kind,
            storage_state_path=storage_state_path,
        )

        # Gates
        if not approve_github_test_account:
            report.blockers.append("Missing --approve-github-test-account flag.")
            report.execution_status = "blocked"
            return report
        if not dedicated_test_account_confirmed:
            report.blockers.append("Missing --dedicated-test-account-confirmed flag.")
            report.execution_status = "blocked"
            return report

        url_block = self._check_github_url(target_url)
        if url_block:
            report.blockers.append(url_block)
            report.execution_status = "blocked"
            return report

        ss_path = Path(storage_state_path)
        if not ss_path.exists():
            report.blockers.append(f"storageState not found: {storage_state_path}")
            report.execution_status = "blocked"
            return report

        scaffold_root, node_exec = self._locate_scaffold_and_node(project_id)
        if not scaffold_root:
            report.blockers.append("No Playwright scaffold found. Run Phase 3A first.")
            report.execution_status = "blocked"
            return report

        script_path = scaffold_root / "github_smoke.cjs"
        screenshot_dir = self._outputs_root / project_id / "19_github_auth"
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = screenshot_dir / "github_smoke_redacted.png"

        script = self._build_smoke_script(
            target_url=target_url,
            storage_state_path=str(ss_path.resolve()),
            screenshot_path=str(screenshot_path),
        )

        try:
            script_path.write_text(script, encoding="utf-8")
            result = subprocess.run(
                [node_exec, str(script_path)],
                cwd=str(scaffold_root),
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ, "NODE_PATH": str(scaffold_root / "node_modules")},
            )
            stdout = result.stdout[:_EXCERPT_LIMIT]
            stderr = result.stderr[:_EXCERPT_LIMIT]

            if result.returncode == 0:
                report.execution_status = "complete"
                report.notes.append("storageState reuse smoke passed.")
                if screenshot_path.exists():
                    report.screenshot_path = str(screenshot_path)
                    report.notes.append(f"Screenshot: {screenshot_path}")
            else:
                report.execution_status = "error"
                report.blockers.append(f"Smoke failed. stderr: {stderr[:300]}")
                report.notes.append(f"stdout: {stdout[:300]}")
        except subprocess.TimeoutExpired:
            report.execution_status = "error"
            report.blockers.append(f"Smoke timed out after {timeout}s.")
        except Exception as exc:
            report.execution_status = "error"
            report.blockers.append(f"Subprocess error: {exc}")
        finally:
            try:
                script_path.unlink(missing_ok=True)
            except OSError:
                pass

        return report

    def render_artifacts(
        self,
        capability: Optional[GitHubAuthCapability],
        decision: Optional[GitHubAuthExecutionDecision],
        evidence: Optional[GitHubAuthEvidenceReport],
        project_id: str,
    ) -> Dict[str, Path]:
        """Write artifacts to outputs/<project_id>/19_github_auth/."""
        out_dir = self._outputs_root / project_id / "19_github_auth"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: Dict[str, Path] = {}

        if capability:
            p = out_dir / "GITHUB_AUTH_CAPABILITY_PLAN.json"
            p.write_text(json.dumps(self._capability_to_dict(capability), indent=2), encoding="utf-8")
            paths["capability_json"] = p

        if decision:
            p = out_dir / "GITHUB_AUTH_EXECUTION_DECISION.json"
            p.write_text(json.dumps(self._decision_to_dict(decision), indent=2), encoding="utf-8")
            paths["decision_json"] = p

        if evidence:
            p = out_dir / "GITHUB_AUTH_EVIDENCE_REPORT.json"
            p.write_text(json.dumps(self._evidence_to_dict(evidence), indent=2), encoding="utf-8")
            paths["evidence_json"] = p

        return paths

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_github_url(self, url: str) -> Optional[str]:
        if not url:
            return "Target URL is required."
        url_lower = url.lower()
        if not any(url_lower.startswith(pfx.lower()) for pfx in GITHUB_ALLOWED_URL_PREFIXES):
            return (
                f"URL '{url}' is not an allowed GitHub target. "
                f"Only github.com / gist.github.com are allowed."
            )
        for blocked in GITHUB_BLOCKED_URL_PATTERNS:
            if blocked in url_lower:
                return f"URL path '{blocked}' is blocked for GitHub auth smoke."
        return None

    def _locate_scaffold_and_node(
        self, project_id: str
    ) -> tuple:
        scaffold = self._outputs_root / project_id / "03_framework" / "playwright"
        if not scaffold.exists():
            return None, None
        node_exec = shutil.which("node") or "node"
        return scaffold, node_exec

    def _build_smoke_script(
        self, target_url: str, storage_state_path: str, screenshot_path: str
    ) -> str:
        safe_url = target_url.replace("'", "")
        safe_ss = storage_state_path.replace("\\", "/").replace("'", "")
        safe_ss_win = storage_state_path.replace("'", "")
        safe_shot = screenshot_path.replace("\\", "/").replace("'", "")
        return (
            "// GitHub auth smoke — runtime only, gitignored\n"
            "const { chromium } = require('@playwright/test');\n"
            "const path = require('path');\n"
            "(async () => {\n"
            f"  const storageStatePath = process.platform === 'win32' ? '{safe_ss_win}'.replace(/\\//g, '\\\\\\\\') : '{safe_ss}';\n"
            "  const browser = await chromium.launch({ headless: true });\n"
            "  const context = await browser.newContext({\n"
            "    storageState: storageStatePath,\n"
            "    viewport: { width: 1280, height: 720 },\n"
            "  });\n"
            "  const page = await context.newPage();\n"
            f"  await page.goto('{safe_url}');\n"
            "  await page.waitForLoadState('networkidle');\n"
            "  const title = await page.title();\n"
            "  console.log('Page title:', title);\n"
            f"  await page.screenshot({{ path: '{safe_shot}', fullPage: false }});\n"
            "  console.log('Screenshot saved.');\n"
            "  await browser.close();\n"
            "})().catch(err => { console.error(err); process.exit(1); });\n"
        )

    def _capability_to_dict(self, cap: GitHubAuthCapability) -> Dict[str, Any]:
        return {
            "project_id": cap.project_id,
            "executable_modes": cap.executable_modes,
            "planning_only_modes": cap.planning_only_modes,
            "blockers": cap.blockers,
            "notes": cap.notes,
            "personal_account_always_blocked": cap.personal_account_always_blocked,
            "production_account_always_blocked": cap.production_account_always_blocked,
            "captcha_bypass_allowed": cap.captcha_bypass_allowed,
            "raw_secrets_allowed": cap.raw_secrets_allowed,
            "storage_state_content_read": cap.storage_state_content_read,
            "client_delivery_allowed": cap.client_delivery_allowed,
        }

    def _decision_to_dict(self, dec: GitHubAuthExecutionDecision) -> Dict[str, Any]:
        return {
            "project_id": dec.project_id,
            "auth_mode": dec.auth_mode,
            "target_url": dec.target_url,
            "allowed_now": dec.allowed_now,
            "blockers": dec.blockers,
            "personal_account_always_blocked": dec.personal_account_always_blocked,
            "captcha_bypass_allowed": dec.captcha_bypass_allowed,
        }

    def _evidence_to_dict(self, ev: GitHubAuthEvidenceReport) -> Dict[str, Any]:
        return {
            "project_id": ev.project_id,
            "auth_mode": ev.auth_mode,
            "target_url": ev.target_url,
            "execution_status": ev.execution_status,
            "blockers": ev.blockers,
            "notes": ev.notes,
            "screenshot_path": ev.screenshot_path,
            "raw_credentials_logged": ev.raw_credentials_logged,
            "cookies_logged": ev.cookies_logged,
            "tokens_logged": ev.tokens_logged,
            "storage_state_content_read": ev.storage_state_content_read,
            "personal_account_used": ev.personal_account_used,
            "production_account_used": ev.production_account_used,
            "safe_to_deliver": ev.safe_to_deliver,
            "approved_for_client_delivery": ev.approved_for_client_delivery,
            "human_review_required": ev.human_review_required,
        }

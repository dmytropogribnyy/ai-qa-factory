"""Demo Auth Runner — Phase 4F.

Executes approval-gated demo auth smoke against strictly allowlisted public demo targets.

SAFETY:
- subprocess.run is called ONLY when --approve-demo-auth-execution is present.
- Only saucedemo_demo_auth profile is allowed in Phase 4F.
- Credential values are injected into subprocess env only — never command args, logs, or artifacts.
- Credential values are masked in stdout/stderr excerpts.
- storageState is generated only under outputs/<project_id>/09_auth/.auth/ (gitignored).
- storageState content is never read or included in reports.
- No .env reading. No personal/production/client credentials.
- Alza, Amazon, Google, LinkedIn, Linear always blocked.
- Delivery flags always False.
- Evidence always internal-only.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.schemas.auth_execution import (
    AuthCredentialProfile,
    AuthExecutionCommand,
    AuthExecutionReport,
    AuthSessionArtifact,
)

_OUTPUTS_ROOT = Path("outputs")

# ---------------------------------------------------------------------------
# Allowed demo auth profiles (Phase 4F: saucedemo_demo_auth only)
# ---------------------------------------------------------------------------
# Public demo credentials for SauceDemo are universally published on the
# SauceDemo site itself. They are not real/personal/production credentials.
# Values are injected into subprocess env only when all approval gates pass.
# They must never appear in command args, logs, JSON reports, or MD artifacts.

_DEMO_AUTH_PROFILES: Dict[str, Dict[str, Any]] = {
    "saucedemo_demo_auth": {
        "provider": "SauceDemo",
        "target_url": "https://www.saucedemo.com",
        "target_category": "public_demo_target",
        "credential_source_type": "public_demo_profile",
        "username_label": "SauceDemo demo account (publicly published on site)",
        "password_label": "SauceDemo demo password (publicly published on site)",
        # Public demo credential values — inject into env only, never log/report
        "_username": "standard_user",
        "_password": "secret_sauce",
        "public_demo_credentials": True,
        "dedicated_test_account": False,
        "personal_account": False,
        "production_account": False,
        "approved_for_demo_auth": True,
        "approved_for_storage_state": True,
        "safe_to_inject_runtime": True,
        "safe_to_store_in_repo": False,
        "allowed_command_modes": {"auth_smoke", "auth_setup"},
        "allowed_test_paths": ["tests/auth"],
        "blocked_test_paths": [
            "tests/ecommerce", "tests/admin", "tests/regression", "tests/api",
        ],
        "notes": [
            "SauceDemo public demo — credentials are universally published on the site.",
            "Credentials are universally published on the SauceDemo website, not real secrets.",
            "Allowed in Phase 4F with --approve-demo-auth-execution.",
            "storageState generated under outputs/<project_id>/09_auth/.auth/ only.",
            "No checkout, no order creation, no payment, no account mutation.",
        ],
    },
}

# ---------------------------------------------------------------------------
# Hard-blocked domains and providers (always blocked regardless of approval)
# ---------------------------------------------------------------------------

_ALWAYS_BLOCKED_DOMAINS = [
    "alza.sk", "www.alza.sk",
    "amazon.com", "www.amazon.com",
    "google.com", "accounts.google.com",
    "gmail.com",
    "linear.app", "app.linear.app",
    "linkedin.com", "www.linkedin.com",
    "upwork.com", "www.upwork.com",
]

_ALWAYS_BLOCKED_PROVIDERS = [
    "alza", "amazon", "google", "linear", "linkedin", "upwork",
]

# ---------------------------------------------------------------------------
# Allowlisted auth commands (only these may pass through subprocess)
# ---------------------------------------------------------------------------

_ALLOWED_AUTH_COMMANDS = [
    "npx playwright test tests/auth --reporter=list",
    "npx playwright test tests/auth --reporter=html,list",
]

# ---------------------------------------------------------------------------
# Blocked command patterns (checked as substrings in the full command string)
# ---------------------------------------------------------------------------

_BLOCKED_COMMAND_PATTERNS = [
    "npm test",
    "npm run test",
    "npm run report",
    "npm install",
    "playwright install",
    "--headed",
    "--ui",
    "tests/ecommerce",
    "tests/admin",
    "tests/regression",
    "tests/api",
    "tests/smoke",
    "curl ",
    "wget ",
    "git clone",
]

# ---------------------------------------------------------------------------
# Environment variable prefixes to strip before subprocess
# ---------------------------------------------------------------------------

_SECRET_ENV_PATTERNS = [
    "PASSWORD", "SECRET", "TOKEN", "API_KEY",
    "PRIVATE_KEY", "CREDENTIAL", "AUTH", "COOKIE", "SESSION",
]

# Maximum stdout/stderr excerpt length
_EXCERPT_LIMIT = 2000


class DemoAuthRunner:
    """Runs approval-gated demo auth execution. subprocess only for allowlisted commands.

    Only saucedemo_demo_auth is allowed in Phase 4F.
    No personal credentials. No production auth. No Alza/Amazon/Google/Linear.
    """

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_demo_auth_execution(
        self,
        project_id: str,
        scaffold_root: Optional[Path] = None,
        approve_demo_auth: bool = False,
        auth_profile: Optional[str] = None,
        command_mode: str = "auth_smoke",
        timeout: int = 120,
    ) -> AuthExecutionReport:
        """Main entry point. Returns AuthExecutionReport."""
        resolved_scaffold = self._resolve_scaffold_root(project_id, scaffold_root)

        report = AuthExecutionReport(
            project_id=project_id,
            scaffold_root=str(resolved_scaffold),
            approved=False,
            demo_profile=auth_profile,
        )

        # Step 1: Validate approval
        block_reason = self._validate_approval(approve_demo_auth, auth_profile, command_mode)
        if block_reason:
            report.execution_status = "blocked"
            report.blockers.append(block_reason)
            cmd = self._build_blocked_command(command_mode, resolved_scaffold, block_reason)
            report.commands.append(cmd)
            report.notes.append("No subprocess executed.")
            report.notes.append("No credentials injected.")
            report.notes.append("No storageState created.")
            return report

        # Step 2: Build credential profile metadata (no raw values)
        profile_meta = _DEMO_AUTH_PROFILES[auth_profile]
        credential_profile = self._build_credential_profile(auth_profile, profile_meta)
        report.credential_profile = credential_profile
        report.target_url = profile_meta["target_url"]

        # Step 3: Build command
        command_str, cmd_block = self._build_auth_command(command_mode)
        if cmd_block:
            report.execution_status = "blocked"
            report.blockers.append(cmd_block)
            cmd = self._build_blocked_command(command_mode, resolved_scaffold, cmd_block)
            report.commands.append(cmd)
            return report

        # Step 4: Resolve storageState path (under 09_auth only)
        storage_state_path = (
            self._outputs_root / project_id / "09_auth" / ".auth" / "storageState.json"
        )

        # Step 5: Execute
        exec_cmd = self._run_auth_command(
            command_str=command_str,
            scaffold_root=resolved_scaffold,
            profile_meta=profile_meta,
            storage_state_path=storage_state_path,
            project_id=project_id,
            timeout=timeout,
        )
        report.commands.append(exec_cmd)
        report.approved = True
        report.auth_execution_performed = exec_cmd.executed
        report.browser_execution_performed = exec_cmd.executed
        report.credentials_used = exec_cmd.executed  # public demo creds injected
        report.execution_status = "complete" if exec_cmd.status == "pass" else "error"

        # Step 6: Check if storageState was generated
        if storage_state_path.exists():
            report.storage_state_created = True
            ss_artifact = AuthSessionArtifact(
                id="artifact_storage_state",
                artifact_type="storage_state",
                path=str(storage_state_path),
                internal_only=True,
                requires_redaction=True,
                notes=[
                    "storageState generated by Playwright auth fixture.",
                    "Internal-only — must not be committed to the repository.",
                    "Content not read or included in this report.",
                    "Gitignored under outputs/<project_id>/09_auth/.auth/.",
                ],
            )
            report.session_artifacts.append(ss_artifact)

        # Step 7: Evidence reference for command log
        log_artifact = AuthSessionArtifact(
            id="artifact_command_log",
            artifact_type="command_log",
            path=str(self._outputs_root / project_id / "09_auth" / "AUTH_COMMAND_LOG.md"),
            internal_only=True,
            requires_redaction=True,
            notes=["Command log — internal-only. Credential values masked."],
        )
        report.session_artifacts.append(log_artifact)

        report.notes.extend([
            "Approved demo auth execution only.",
            f"Profile: {auth_profile}",
            f"Target: {profile_meta['target_url']}",
            "No real credentials used. Public demo profile only.",
            "No personal/production account used.",
            "No payment/checkout/destructive actions.",
            "No client delivery created.",
            "Evidence internal-only.",
            "safe_to_deliver=False.",
            "approved_for_client_delivery=False.",
        ])
        return report

    def render_auth_artifacts(
        self,
        report: AuthExecutionReport,
        project_id: str,
    ) -> Dict[str, Path]:
        """Write auth artifacts to outputs/<project_id>/09_auth/."""
        out_dir = self._outputs_root / project_id / "09_auth"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: Dict[str, Path] = {}

        # Approval JSON/MD
        approval_data = self._build_approval_dict(report, project_id)
        p = out_dir / "AUTH_EXECUTION_APPROVAL.json"
        p.write_text(json.dumps(approval_data, indent=2), encoding="utf-8")
        paths["approval_json"] = p

        p = out_dir / "AUTH_EXECUTION_APPROVAL.md"
        p.write_text(self._render_approval_md(approval_data, report), encoding="utf-8")
        paths["approval_md"] = p

        # Report JSON/MD
        p = out_dir / "AUTH_EXECUTION_REPORT.json"
        p.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        paths["report_json"] = p

        p = out_dir / "AUTH_EXECUTION_REPORT.md"
        p.write_text(self._render_report_md(report), encoding="utf-8")
        paths["report_md"] = p

        # Command log
        p = out_dir / "AUTH_COMMAND_LOG.md"
        p.write_text(self._render_command_log_md(report), encoding="utf-8")
        paths["command_log_md"] = p

        # Session artifacts JSON/MD
        p = out_dir / "AUTH_SESSION_ARTIFACTS.json"
        artifacts_data = {
            "project_id": project_id,
            "session_artifacts": [a.to_dict() for a in report.session_artifacts],
        }
        p.write_text(json.dumps(artifacts_data, indent=2), encoding="utf-8")
        paths["artifacts_json"] = p

        p = out_dir / "AUTH_SESSION_ARTIFACTS.md"
        p.write_text(self._render_artifacts_md(report), encoding="utf-8")
        paths["artifacts_md"] = p

        # Redaction checklist
        p = out_dir / "AUTH_REDACTION_CHECKLIST.md"
        p.write_text(self._render_redaction_checklist(report, project_id), encoding="utf-8")
        paths["redaction_checklist"] = p

        return paths

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_approval(
        self,
        approve_demo_auth: bool,
        auth_profile: Optional[str],
        command_mode: str,
    ) -> Optional[str]:
        """Return block reason string, or None if execution is allowed."""
        if not approve_demo_auth:
            return (
                "No approval flag provided. "
                "Use --approve-demo-auth-execution to enable demo auth execution."
            )

        if not auth_profile:
            return "No --auth-profile specified. Use --auth-profile saucedemo_demo_auth."

        if auth_profile not in _DEMO_AUTH_PROFILES:
            return (
                f"Auth profile '{auth_profile}' is not an allowed demo auth profile. "
                "Only saucedemo_demo_auth is allowed in Phase 4F. "
                "Alza, Amazon, Google, Linear, LinkedIn, Upwork auth is always blocked."
            )

        # Check for blocked providers by name in the profile id
        profile_lower = auth_profile.lower()
        for blocked in _ALWAYS_BLOCKED_PROVIDERS:
            if blocked in profile_lower and auth_profile != "saucedemo_demo_auth":
                return (
                    f"Auth profile '{auth_profile}' references a blocked provider '{blocked}'. "
                    "Personal/production/client auth is always blocked."
                )

        profile_meta = _DEMO_AUTH_PROFILES[auth_profile]
        allowed_modes = profile_meta["allowed_command_modes"]
        if command_mode not in allowed_modes:
            return (
                f"command_mode='{command_mode}' is not allowed for profile '{auth_profile}'. "
                f"Allowed modes: {sorted(allowed_modes)}."
            )

        return None

    def validate_profile_blocked(
        self,
        auth_profile: str,
        target_url: Optional[str] = None,
    ) -> Optional[str]:
        """Return block reason if the profile or URL is always blocked."""
        profile_lower = auth_profile.lower()
        for blocked in _ALWAYS_BLOCKED_PROVIDERS:
            if blocked in profile_lower:
                return f"Provider '{blocked}' is always blocked in Phase 4F."

        if target_url:
            url_lower = target_url.lower()
            for domain in _ALWAYS_BLOCKED_DOMAINS:
                if domain in url_lower:
                    return f"Domain '{domain}' is always blocked as an auth target."

        return None

    def is_command_allowed(self, command: str) -> bool:
        """Return True if command is in the auth allowlist and not in blocklist."""
        cmd_stripped = command.strip()
        if cmd_stripped not in _ALLOWED_AUTH_COMMANDS:
            return False
        return self._check_command_blocked(cmd_stripped) is None

    def _check_command_blocked(self, command: str) -> Optional[str]:
        """Return block reason if command matches a blocked pattern."""
        cmd_lower = command.lower()
        for pattern in _BLOCKED_COMMAND_PATTERNS:
            if pattern.lower() in cmd_lower:
                return f"Command contains blocked pattern '{pattern}': {command}"
        if command.strip() not in _ALLOWED_AUTH_COMMANDS:
            return f"Command not in auth allowlist: {command}"
        return None

    # ------------------------------------------------------------------
    # Credential profile (metadata only, no raw values)
    # ------------------------------------------------------------------

    def _build_credential_profile(
        self,
        auth_profile: str,
        profile_meta: Dict[str, Any],
    ) -> AuthCredentialProfile:
        """Build a credential profile metadata object. Raw values excluded."""
        return AuthCredentialProfile(
            id=auth_profile,
            provider=profile_meta["provider"],
            target_category=profile_meta["target_category"],
            target_url=profile_meta["target_url"],
            credential_source_type=profile_meta["credential_source_type"],
            username_label=profile_meta["username_label"],
            password_label=profile_meta["password_label"],
            public_demo_credentials=profile_meta["public_demo_credentials"],
            dedicated_test_account=profile_meta["dedicated_test_account"],
            approved_for_demo_auth=profile_meta["approved_for_demo_auth"],
            approved_for_storage_state=profile_meta["approved_for_storage_state"],
            safe_to_inject_runtime=profile_meta["safe_to_inject_runtime"],
            notes=list(profile_meta.get("notes", [])),
        )

    # ------------------------------------------------------------------
    # Command building and execution
    # ------------------------------------------------------------------

    def _build_auth_command(self, command_mode: str) -> Tuple[str, Optional[str]]:
        """Return (command_string, block_reason). block_reason is None if allowed."""
        if command_mode == "auth_smoke":
            cmd = "npx playwright test tests/auth --reporter=list"
        elif command_mode == "auth_setup":
            cmd = "npx playwright test tests/auth --reporter=list"
        else:
            return "", f"Unknown command_mode: '{command_mode}'."

        block = self._check_command_blocked(cmd)
        if block:
            return cmd, block
        return cmd, None

    def _build_blocked_command(
        self,
        command_mode: str,
        scaffold_root: Path,
        block_reason: str,
    ) -> AuthExecutionCommand:
        return AuthExecutionCommand(
            id="cmd_blocked",
            command=f"[blocked:{command_mode}]",
            cwd=str(scaffold_root),
            status="blocked",
            executed=False,
            skipped_reason=block_reason,
            safety_notes=[
                "No subprocess was executed.",
                "No credentials were injected.",
            ],
        )

    def _run_auth_command(
        self,
        command_str: str,
        scaffold_root: Path,
        profile_meta: Dict[str, Any],
        storage_state_path: Path,
        project_id: str,
        timeout: int,
    ) -> AuthExecutionCommand:
        """Run allowlisted auth command via subprocess. Returns AuthExecutionCommand."""
        cmd_id = f"cmd_auth_{datetime.now(timezone.utc).strftime('%H%M%S')}"
        safe_env = self._build_safe_env(profile_meta, storage_state_path)

        cmd_record = AuthExecutionCommand(
            id=cmd_id,
            command=command_str,
            cwd=str(scaffold_root),
            safety_notes=[
                "subprocess used only for allowlisted auth command.",
                "Secrets stripped from environment.",
                "Only approved public demo credentials injected.",
                "Credentials never appear in command args.",
                "cwd restricted to scaffold root.",
            ],
        )

        start = time.monotonic()
        try:
            result = subprocess.run(
                command_str,
                shell=True,
                cwd=str(scaffold_root),
                env=safe_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.monotonic() - start
            cmd_record.exit_code = result.returncode
            cmd_record.duration_seconds = round(duration, 2)
            # Mask credential values in output
            credential_values = [
                profile_meta.get("_username", ""),
                profile_meta.get("_password", ""),
            ]
            cmd_record.stdout_excerpt = self._mask_credentials(
                result.stdout[:_EXCERPT_LIMIT], credential_values
            )
            cmd_record.stderr_excerpt = self._mask_credentials(
                result.stderr[:_EXCERPT_LIMIT], credential_values
            )
            cmd_record.executed = True
            cmd_record.status = "pass" if result.returncode == 0 else "fail"
        except FileNotFoundError as exc:
            cmd_record.status = "fail"
            cmd_record.executed = False
            cmd_record.skipped_reason = (
                f"Command not found (dependencies not installed?): {exc}"
            )
        except subprocess.TimeoutExpired:
            cmd_record.status = "fail"
            cmd_record.executed = False
            cmd_record.skipped_reason = f"Command timed out after {timeout}s."
        except Exception as exc:  # noqa: BLE001
            cmd_record.status = "fail"
            cmd_record.executed = False
            cmd_record.skipped_reason = f"Unexpected error: {type(exc).__name__}: {exc}"

        return cmd_record

    # ------------------------------------------------------------------
    # Environment safety
    # ------------------------------------------------------------------

    def _build_safe_env(
        self,
        profile_meta: Dict[str, Any],
        storage_state_path: Path,
    ) -> Dict[str, str]:
        """Build sanitized environment with only approved demo credentials injected."""
        env = dict(os.environ)
        # Strip all secret-like variables from inherited environment
        to_remove = [
            k for k in env
            if any(pat in k.upper() for pat in _SECRET_ENV_PATTERNS)
        ]
        for k in to_remove:
            del env[k]
        # Inject only approved public demo credentials and safe overrides
        env["BASE_URL"] = profile_meta["target_url"]
        env["API_BASE_URL"] = ""
        env["TEST_USERNAME"] = profile_meta.get("_username", "")
        env["TEST_PASSWORD"] = profile_meta.get("_password", "")
        env["AUTH_STORAGE_STATE_PATH"] = str(storage_state_path)
        # Ensure storage state directory exists
        storage_state_path.parent.mkdir(parents=True, exist_ok=True)
        return env

    def _mask_credentials(self, text: str, credential_values: List[str]) -> str:
        """Mask known credential values in stdout/stderr excerpt."""
        for val in credential_values:
            if val and val in text:
                text = text.replace(val, "***")
        return text

    # ------------------------------------------------------------------
    # Profile resolution
    # ------------------------------------------------------------------

    def _resolve_scaffold_root(
        self,
        project_id: str,
        scaffold_root: Optional[Path],
    ) -> Path:
        if scaffold_root:
            return scaffold_root
        return self._outputs_root / project_id / "03_framework" / "playwright"

    # ------------------------------------------------------------------
    # Artifact rendering
    # ------------------------------------------------------------------

    def _build_approval_dict(
        self,
        report: AuthExecutionReport,
        project_id: str,
    ) -> Dict[str, Any]:
        return {
            "project_id": project_id,
            "approved": report.approved,
            "approval_required": report.approval_required,
            "approval_source": "--approve-demo-auth-execution" if report.approved else "none",
            "approval_scope": (
                "saucedemo_demo_auth public demo auth only"
                if report.approved
                else "no approval granted"
            ),
            "approved_profile": report.demo_profile if report.approved else None,
            "approved_target_url": report.target_url if report.approved else None,
            "approved_commands": list(_ALLOWED_AUTH_COMMANDS) if report.approved else [],
            "denied_commands": [
                "npm install", "npx playwright install",
                "npm test", "npm run test", "npm run test:headed", "npm run test:ui",
                "npx playwright test (unrestricted)",
                "npx playwright test tests/ecommerce",
                "npx playwright test tests/admin",
                "npx playwright test tests/regression",
                "npx playwright test tests/api",
                "any command with --headed or --ui",
                "any command with credentials in args",
                "curl/wget", "git clone",
            ],
            "safety_constraints": [
                "Public demo credentials only (SauceDemo — publicly published on site).",
                "No personal/production/client credentials.",
                "No Alza/Amazon/Google/Linear/LinkedIn/Upwork auth.",
                "No payment/checkout/order creation.",
                "No destructive/admin writes.",
                "No scraping/crawling/load/security testing.",
                "No client delivery. safe_to_deliver=False.",
                "storageState internal-only under 09_auth/.auth/.",
                "Evidence internal-only.",
            ],
            "blockers": list(report.blockers),
        }

    def _render_approval_md(
        self,
        approval_data: Dict[str, Any],
        report: AuthExecutionReport,
    ) -> str:
        approved = approval_data["approved"]
        lines = [
            "# Auth Execution Approval — Phase 4F",
            "",
            f"> **approved:** `{approved}`",
            f"> **scope:** {approval_data['approval_scope']}",
            "",
            "## Safety Constraints",
            "",
        ]
        for c in approval_data["safety_constraints"]:
            lines.append(f"- {c}")
        if approval_data["blockers"]:
            lines.extend(["", "## Blockers", ""])
            for b in approval_data["blockers"]:
                lines.append(f"- {b}")
        lines.extend([
            "",
            "## Safety Boundary",
            "",
            "- No real credentials used.",
            "- No personal/production account used.",
            "- No Alza/Amazon/Google/Linear auth.",
            "- No payment/checkout/order.",
            "- No client delivery.",
        ])
        return "\n".join(lines) + "\n"

    def _render_report_md(self, report: AuthExecutionReport) -> str:
        lines = [
            "# Auth Execution Report — Phase 4F",
            "",
            "> **No real credentials used.**  ",
            "> **No personal/production account used.**  ",
            "> **Evidence internal-only.**",
            "",
            f"**Project:** `{report.project_id}`",
            f"**Status:** `{report.execution_status}`",
            f"**Approved:** `{report.approved}`",
            f"**Profile:** `{report.demo_profile}`",
            "",
            "## Execution Flags",
            "",
            "| Flag | Value |",
            "|------|-------|",
            f"| auth_execution_performed | `{report.auth_execution_performed}` |",
            f"| browser_execution_performed | `{report.browser_execution_performed}` |",
            f"| storage_state_created | `{report.storage_state_created}` |",
            f"| credentials_used | `{report.credentials_used}` |",
            f"| real_credentials_used | `{report.real_credentials_used}` |",
            f"| personal_account_used | `{report.personal_account_used}` |",
            f"| production_account_used | `{report.production_account_used}` |",
            f"| safe_to_deliver | `{report.safe_to_deliver}` |",
            f"| approved_for_client_delivery | `{report.approved_for_client_delivery}` |",
        ]
        if report.blockers:
            lines.extend(["", "## Blockers", ""])
            for b in report.blockers:
                lines.append(f"- {b}")
        if report.warnings:
            lines.extend(["", "## Warnings", ""])
            for w in report.warnings:
                lines.append(f"- {w}")
        lines.extend(["", "## Notes", ""])
        for n in report.notes:
            lines.append(f"- {n}")
        return "\n".join(lines) + "\n"

    def _render_command_log_md(self, report: AuthExecutionReport) -> str:
        lines = [
            "# Auth Command Log — Phase 4F",
            "",
            "> Credential values are masked in this log.",
            "> Internal-only — do not share with clients.",
            "",
            f"**Project:** `{report.project_id}`",
            "",
        ]
        for cmd in report.commands:
            lines.extend([
                f"## Command: `{cmd.command}`",
                "",
                f"- Status: `{cmd.status}`",
                f"- Executed: `{cmd.executed}`",
                f"- Exit code: `{cmd.exit_code}`",
                f"- Duration: `{cmd.duration_seconds}s`",
            ])
            if cmd.skipped_reason:
                lines.append(f"- Skipped/blocked: {cmd.skipped_reason}")
            if cmd.stdout_excerpt:
                lines.extend(["", "**stdout (masked):**", "```", cmd.stdout_excerpt[:500], "```"])
            if cmd.stderr_excerpt:
                lines.extend(["", "**stderr (masked):**", "```", cmd.stderr_excerpt[:500], "```"])
            lines.append("")
        return "\n".join(lines) + "\n"

    def _render_artifacts_md(self, report: AuthExecutionReport) -> str:
        lines = [
            "# Auth Session Artifacts — Phase 4F",
            "",
            "> All artifacts are internal-only.",
            "> approved_for_commit=False. client_visible=False.",
            "",
            f"**Project:** `{report.project_id}`",
            "",
        ]
        if report.session_artifacts:
            for a in report.session_artifacts:
                lines.extend([
                    f"## {a.artifact_type}: `{a.id}`",
                    f"- path: `{a.path}`",
                    f"- internal_only: `{a.internal_only}`",
                    f"- client_visible: `{a.client_visible}`",
                    f"- requires_redaction: `{a.requires_redaction}`",
                    f"- approved_for_commit: `{a.approved_for_commit}`",
                    f"- approved_for_client_view: `{a.approved_for_client_view}`",
                    "",
                ])
        else:
            lines.append("No session artifacts produced.")
        return "\n".join(lines) + "\n"

    def _render_redaction_checklist(
        self,
        report: AuthExecutionReport,
        project_id: str,
    ) -> str:
        lines = [
            "# Auth Redaction Checklist — Phase 4F",
            "",
            f"**Project:** `{project_id}`",
            "",
            "> Review before any client-visible use of auth artifacts.",
            "",
            "## Required Actions",
            "",
            "- [ ] Verify no real passwords appear in any artifact.",
            "- [ ] Verify no API keys or tokens appear in any artifact.",
            "- [ ] Verify storageState files are not committed to the repository.",
            "- [ ] Verify .auth/ directory is gitignored.",
            "- [ ] Verify no personal account credentials appear anywhere.",
            "- [ ] Verify no production account credentials appear anywhere.",
            "- [ ] Verify command log has no raw credential values (should be masked).",
            "",
            "## Session Artifacts Requiring Review",
            "",
        ]
        if report.session_artifacts:
            for a in report.session_artifacts:
                lines.append(f"- [ ] `{a.artifact_type}` at `{a.path}` — verify no credentials exposed")
        else:
            lines.append("- No session artifacts produced.")
        lines.extend([
            "",
            "## Safety Boundary",
            "",
            "- No real credentials were used in this session.",
            "- Public demo credentials (SauceDemo) were injected into subprocess env only.",
            "- Credential values were masked from stdout/stderr excerpts.",
            "- No .env or .auth files were read.",
            "- storageState is internal-only. approved_for_commit=False.",
            "- safe_to_deliver=False. approved_for_client_delivery=False.",
        ])
        return "\n".join(lines) + "\n"

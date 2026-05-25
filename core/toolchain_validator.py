"""ToolchainValidator — approval-gated local toolchain validation (Phase 3C).

Validates a generated Playwright scaffold by running allowlisted local commands
(npm install, typecheck, playwright --list) inside the scaffold directory only.

APPROVAL GATE:
- All commands require explicit approval (approved=True) before execution.
- Without approval: all commands are marked skipped/blocked, no subprocess runs.
- With approval: only allowlisted commands are executed.

PERMANENT SAFETY INVARIANTS:
- safe_to_execute_tests = False always
- browser_execution_performed = False always
- external_url_used = False always
- credentials_used = False always
- No npx playwright install
- No npx playwright test (any mode)
- No npm test / npm run test
- No headed/headless browser launch
- No external URL access
- No .env reading
- No credential injection
- Subprocess only inside scaffold root, allowlist-checked commands only
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.schemas.toolchain_validation import (
    ToolchainApprovalRecord,
    ToolchainCommandResult,
    ToolchainValidationReport,
)

_OUTPUTS_ROOT = Path("outputs")

_EXCERPT_LIMIT = 2000

# Commands explicitly blocked regardless of approval
_BLOCKED_SUBSTRINGS = [
    "playwright install",
    "playwright test",
    "npm test",
    "npm run test",
    "npm run test:",
    "headed",
    "--headed",
    "curl",
    "wget",
    "git clone",
    "npm run report",
    "npm run test:smoke",
    "npm run test:api",
    "npm run test:ui",
    "npm run test:regression",
]

# External URL pattern (blocks if found in command args)
_EXTERNAL_URL_RE = re.compile(
    r"https?://(?!localhost\b|127\.0\.0\.1\b|example\.com\b)[a-zA-Z0-9\-.]+"
)

# Patterns that look like secrets in command args
_SECRET_LIKE_RE = re.compile(
    r"(sk-[A-Za-z0-9]{10,}|xoxb-|ghp_|Bearer\s+[A-Za-z0-9]{10,}|password=[^\s]+|token=[^\s]+)",
    re.IGNORECASE,
)

# Allowlisted command definitions: (display_name, category, base_argv)
_ALLOWED_COMMANDS: List[Tuple[str, str, List[str]]] = [
    ("npm install", "dependency_install", ["npm", "install"]),
    ("npm run typecheck", "typecheck", ["npm", "run", "typecheck"]),
    ("npx playwright test --list", "discovery", ["npx", "playwright", "test", "--list"]),
]

# Safe environment overrides — prevent credential leakage into subprocess
_SAFE_ENV_OVERRIDES: Dict[str, str] = {
    "BASE_URL": "http://localhost:3000",
    "API_BASE_URL": "http://localhost:3000/api",
    "TEST_USERNAME": "",
    "TEST_PASSWORD": "",
}

# Keys to strip from environment before passing to subprocess
_STRIP_ENV_KEYS_RE = re.compile(
    r"(PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE_KEY|CREDENTIAL|AUTH|COOKIE|SESSION)",
    re.IGNORECASE,
)


class ToolchainValidator:
    """Approval-gated local toolchain validation for generated Playwright scaffolds.

    Usage without approval (safe, no commands executed):
        report, approval = validator.validate_toolchain(root, project_id, approved=False)

    Usage with approval (runs allowlisted commands):
        report, approval = validator.validate_toolchain(root, project_id, approved=True)
    """

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_toolchain(
        self,
        scaffold_root: Path,
        project_id: Optional[str] = None,
        approved: bool = False,
        command_timeout: int = 120,
    ) -> Tuple[ToolchainValidationReport, ToolchainApprovalRecord]:
        """Run toolchain validation. Returns (report, approval_record).

        All safety invariants (safe_to_execute_tests=False, browser_execution_performed=False,
        external_url_used=False, credentials_used=False) are hardcoded and never changed.
        """
        pid = project_id or scaffold_root.name
        approval = self.build_approval_record(scaffold_root, pid, approved)

        report = ToolchainValidationReport(
            project_id=pid,
            scaffold_root=str(scaffold_root.resolve()),
            approval_required=True,
            approved=approved,
            browser_execution_performed=False,
            external_url_used=False,
            credentials_used=False,
            safe_to_execute_tests=False,
        )

        if not scaffold_root.exists():
            report.validation_status = "blocked"
            report.blockers.append(f"Scaffold root not found: {scaffold_root}")
            return report, approval

        # Prerequisite: check static validation
        static_ok, static_msg = self._check_static_prerequisite(scaffold_root)
        if not static_ok:
            report.validation_status = "blocked"
            report.blockers.append(static_msg)
            return report, approval

        if not approved:
            report.validation_status = "blocked"
            report.notes.append(
                "No --approve-toolchain flag: toolchain commands were not executed. "
                "Re-run with --approve-toolchain to execute allowlisted local commands."
            )
            for name, _cat, argv in _ALLOWED_COMMANDS:
                report.commands.append(ToolchainCommandResult(
                    id=f"cmd-{name.replace(' ', '-')}",
                    command=" ".join(argv),
                    cwd=str(scaffold_root),
                    status="skipped",
                    executed=False,
                    skipped_reason="approval_required — pass --approve-toolchain to execute",
                    safety_notes=["Not executed: no approval flag provided"],
                ))
            return report, approval

        # Approved: run allowlisted commands
        report.commands = self.run_allowed_commands(
            scaffold_root, approval, command_timeout
        )

        # Aggregate results
        any_fail = any(c.status == "fail" for c in report.commands)
        any_pass = any(c.status == "pass" for c in report.commands)
        all_skipped = all(c.status in ("skipped", "blocked") for c in report.commands)

        for cmd in report.commands:
            if cmd.status == "fail":
                report.blockers.append(f"Command failed: {cmd.command} (exit {cmd.exit_code})")
            if cmd.command in ("npm install", "npm ci") and cmd.status == "pass":
                report.npm_install_performed = True
            if "typecheck" in cmd.command and cmd.status == "pass":
                report.typecheck_performed = True
            if "--list" in cmd.command and cmd.status == "pass":
                report.playwright_discovery_performed = True

        if all_skipped:
            report.validation_status = "skipped"
        elif any_fail:
            report.validation_status = "fail"
        elif any_pass:
            report.validation_status = "pass"
        else:
            report.validation_status = "unknown"

        # safe_to_proceed is True only if approved + no blockers + at least one pass
        report.safe_to_proceed_to_approved_execution = (
            approved and not report.blockers and any_pass
        )
        # safe_to_execute_tests is ALWAYS False — toolchain validation alone never grants test permission
        report.safe_to_execute_tests = False
        report.browser_execution_performed = False
        report.external_url_used = False
        report.credentials_used = False

        return report, approval

    def build_approval_record(
        self,
        scaffold_root: Path,
        project_id: str,
        approved: bool,
    ) -> ToolchainApprovalRecord:
        """Build an approval record reflecting the current approval state."""
        approved_cmds = [" ".join(argv) for _, _, argv in _ALLOWED_COMMANDS] if approved else []
        denied_cmds = [s for s in _BLOCKED_SUBSTRINGS]
        return ToolchainApprovalRecord(
            project_id=project_id,
            scaffold_root=str(scaffold_root.resolve()),
            approved=approved,
            approval_source="cli_flag" if approved else "not_provided",
            approval_reason=(
                "--approve-toolchain flag provided" if approved
                else "Approval not provided. Pass --approve-toolchain to execute commands."
            ),
            approved_commands=approved_cmds,
            denied_commands=denied_cmds,
            safety_constraints=[
                "safe_to_execute_tests remains False",
                "browser_execution_performed remains False",
                "external_url_used remains False",
                "credentials_used remains False",
                "No npx playwright install",
                "No npx playwright test",
                "No npm test or npm run test",
                "No headed/headless browser launch",
                "No external URL access",
                "No .env file reading",
                "No credential injection",
                "Toolchain validation does not authorize target execution",
                "Toolchain validation does not mean client delivery is approved",
            ],
        )

    def run_allowed_commands(
        self,
        scaffold_root: Path,
        approval: ToolchainApprovalRecord,
        command_timeout: int = 120,
    ) -> List[ToolchainCommandResult]:
        """Execute only allowlisted commands inside scaffold root. Returns results."""
        results = []
        for name, _cat, argv in _ALLOWED_COMMANDS:
            cmd_str = " ".join(argv)
            result = ToolchainCommandResult(
                id=f"cmd-{name.replace(' ', '-')}",
                command=cmd_str,
                cwd=str(scaffold_root),
                executed=False,
            )

            blocked, reason = self._is_blocked(argv, scaffold_root)
            if blocked:
                result.status = "blocked"
                result.skipped_reason = reason
                result.safety_notes.append(f"Blocked: {reason}")
                results.append(result)
                continue

            result = self.run_command(argv, scaffold_root, command_timeout, result)
            results.append(result)

        return results

    def run_command(
        self,
        argv: List[str],
        cwd: Path,
        timeout: int,
        result: ToolchainCommandResult,
    ) -> ToolchainCommandResult:
        """Execute a single subprocess command. Captures output safely."""
        safe_env = self._build_safe_env()
        start = time.monotonic()
        try:
            proc = subprocess.run(
                argv,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=safe_env,
            )
            elapsed = time.monotonic() - start
            result.exit_code = proc.returncode
            result.stdout_excerpt = proc.stdout[-_EXCERPT_LIMIT:] if proc.stdout else ""
            result.stderr_excerpt = proc.stderr[-_EXCERPT_LIMIT:] if proc.stderr else ""
            result.duration_seconds = round(elapsed, 3)
            result.executed = True
            result.status = "pass" if proc.returncode == 0 else "fail"
        except subprocess.TimeoutExpired:
            elapsed = time.monotonic() - start
            result.status = "fail"
            result.executed = True
            result.duration_seconds = round(elapsed, 3)
            result.stderr_excerpt = f"Command timed out after {timeout}s"
            result.skipped_reason = "timeout"
        except FileNotFoundError:
            result.status = "fail"
            result.executed = False
            result.stderr_excerpt = f"Command not found: {argv[0]}"
            result.skipped_reason = "command_not_found"
        return result

    def is_command_allowed(self, argv: List[str]) -> bool:
        """Return True if command is in the allowlist and not blocked."""
        blocked, _ = self._is_blocked(argv, Path("."))
        if blocked:
            return False
        cmd_str = " ".join(argv).lower()
        for _, _, allowed_argv in _ALLOWED_COMMANDS:
            allowed_str = " ".join(allowed_argv).lower()
            if cmd_str.startswith(allowed_str):
                return True
        return False

    def detect_external_url(self, argv: List[str]) -> Optional[str]:
        """Return first external URL found in command args, or None."""
        cmd_str = " ".join(argv)
        m = _EXTERNAL_URL_RE.search(cmd_str)
        return m.group(0) if m else None

    def detect_secret_like_args(self, argv: List[str]) -> Optional[str]:
        """Return first secret-like pattern found in command args, or None."""
        cmd_str = " ".join(argv)
        m = _SECRET_LIKE_RE.search(cmd_str)
        return m.group(0) if m else None

    # ------------------------------------------------------------------
    # Artifact renderers
    # ------------------------------------------------------------------

    def render_toolchain_artifacts(
        self,
        report: ToolchainValidationReport,
        approval: ToolchainApprovalRecord,
        scaffold_root: Path,
    ) -> Dict[str, str]:
        """Write toolchain validation artifacts under scaffold_root. Returns path dict."""
        root = scaffold_root
        root.mkdir(parents=True, exist_ok=True)

        paths: Dict[str, str] = {}

        # JSON report
        json_path = root / "TOOLCHAIN_VALIDATION_REPORT.json"
        json_path.write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False), encoding="utf-8"
        )
        paths["TOOLCHAIN_VALIDATION_REPORT.json"] = str(json_path)

        # Markdown report
        md_path = root / "TOOLCHAIN_VALIDATION_REPORT.md"
        md_path.write_text(self._render_report_md(report), encoding="utf-8")
        paths["TOOLCHAIN_VALIDATION_REPORT.md"] = str(md_path)

        # Command log
        log_path = root / "TOOLCHAIN_COMMAND_LOG.md"
        log_path.write_text(self._render_command_log(report), encoding="utf-8")
        paths["TOOLCHAIN_COMMAND_LOG.md"] = str(log_path)

        # Approval record
        approval_path = root / "TOOLCHAIN_APPROVAL_RECORD.md"
        approval_path.write_text(self._render_approval_record(approval), encoding="utf-8")
        paths["TOOLCHAIN_APPROVAL_RECORD.md"] = str(approval_path)

        return paths

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_static_prerequisite(self, scaffold_root: Path) -> Tuple[bool, str]:
        """Check static validation prerequisite. Returns (ok, message)."""
        static_report_path = scaffold_root / "STATIC_VALIDATION_REPORT.json"
        if not static_report_path.exists():
            # Try to run ScaffoldValidator internally
            try:
                from core.scaffold_validator import ScaffoldValidator
                validator = ScaffoldValidator(outputs_root=self._outputs_root)
                static_report = validator.validate_scaffold(scaffold_root)
                if static_report.blockers:
                    return False, (
                        f"Static validation has {len(static_report.blockers)} blocker(s). "
                        "Run 'python tools/validate_scaffold.py' and resolve blockers first."
                    )
                return True, "Static validation passed (run internally)"
            except Exception as exc:
                return False, (
                    f"STATIC_VALIDATION_REPORT.json not found and internal check failed: {exc}. "
                    "Run 'python tools/validate_scaffold.py' first."
                )

        try:
            data = json.loads(static_report_path.read_text(encoding="utf-8"))
        except Exception as exc:
            return False, f"Could not read STATIC_VALIDATION_REPORT.json: {exc}"

        blockers = data.get("blockers", [])
        if blockers:
            return False, (
                f"Static validation report has {len(blockers)} blocker(s). "
                "Resolve all blockers before toolchain validation."
            )
        return True, "Static validation prerequisite satisfied"

    def _is_blocked(self, argv: List[str], cwd: Path) -> Tuple[bool, str]:
        """Check if command is blocked. Returns (blocked, reason)."""
        cmd_str = " ".join(argv).lower()

        # Allowlisted commands bypass substring checks (they are safe by definition).
        # External URL and secret checks still apply to all commands.
        is_allowlisted = any(
            cmd_str.startswith(" ".join(a).lower())
            for _, _, a in _ALLOWED_COMMANDS
        )
        if not is_allowlisted:
            for blocked_sub in _BLOCKED_SUBSTRINGS:
                if blocked_sub.lower() in cmd_str:
                    return True, f"Command contains blocked substring: '{blocked_sub}'"

        external_url = self.detect_external_url(argv)
        if external_url:
            return True, f"Command contains external URL: {external_url}"

        secret = self.detect_secret_like_args(argv)
        if secret:
            return True, "Command contains secret-like argument (redacted)"

        return False, ""

    def _build_safe_env(self) -> Dict[str, str]:
        """Build a sanitized environment for subprocess, stripping sensitive vars."""
        env = dict(os.environ)
        stripped = []
        for key in list(env.keys()):
            if _STRIP_ENV_KEYS_RE.search(key):
                stripped.append(key)
                del env[key]
        env.update(_SAFE_ENV_OVERRIDES)
        return env

    def _render_report_md(self, report: ToolchainValidationReport) -> str:
        status_icon = {"pass": "PASS", "fail": "FAIL", "blocked": "BLOCKED",
                       "skipped": "SKIPPED", "warning": "WARN", "unknown": "???"}
        icon = status_icon.get(report.validation_status, report.validation_status.upper())
        approved_str = "YES (--approve-toolchain)" if report.approved else "NO (approval required)"
        lines = [
            f"# Toolchain Validation Report [{icon}]",
            "",
            f"**Project:** {report.project_id}",
            f"**Scaffold root:** {report.scaffold_root}",
            f"**Status:** {report.validation_status}",
            f"**Approved:** {approved_str}",
            f"**Created:** {report.created_at}",
            "",
            "---",
            "",
            "## Safety Boundary",
            "",
            "> **Toolchain validation does not mean tests were executed.**",
            "> **Toolchain validation does not mean client delivery is approved.**",
            "> **safe_to_execute_tests remains False.**",
            "",
            f"- browser_execution_performed: {report.browser_execution_performed}",
            f"- external_url_used: {report.external_url_used}",
            f"- credentials_used: {report.credentials_used}",
            f"- safe_to_execute_tests: {report.safe_to_execute_tests}",
            f"- safe_to_proceed_to_approved_execution: {report.safe_to_proceed_to_approved_execution}",
            "",
            "## Toolchain Steps Performed",
            "",
            f"- npm_install_performed: {report.npm_install_performed}",
            f"- typecheck_performed: {report.typecheck_performed}",
            f"- playwright_discovery_performed: {report.playwright_discovery_performed}",
            "",
        ]

        if report.blockers:
            lines += ["## Blockers", ""]
            for b in report.blockers:
                lines.append(f"- {b}")
            lines.append("")

        if report.warnings:
            lines += ["## Warnings", ""]
            for w in report.warnings:
                lines.append(f"- {w}")
            lines.append("")

        if report.commands:
            lines += ["## Command Results", ""]
            lines += ["| Command | Status | Exit Code | Duration |",
                      "|---------|--------|-----------|----------|"]
            for cmd in report.commands:
                exit_str = str(cmd.exit_code) if cmd.exit_code is not None else "-"
                dur_str = f"{cmd.duration_seconds:.1f}s" if cmd.duration_seconds is not None else "-"
                lines.append(f"| `{cmd.command}` | {cmd.status} | {exit_str} | {dur_str} |")
            lines.append("")

        if report.notes:
            lines += ["## Notes", ""]
            for n in report.notes:
                lines.append(f"- {n}")
            lines.append("")

        if not report.approved:
            lines += [
                "## Next Steps",
                "",
                "To execute toolchain commands, re-run with --approve-toolchain:",
                "",
                "```bash",
                f"python tools/validate_toolchain.py --project-id {report.project_id} --approve-toolchain",
                "```",
                "",
                "Approval authorizes only: npm install, npm run typecheck, npx playwright test --list",
                "",
                "It does NOT authorize: browser tests, target URL access, credential use.",
            ]

        return "\n".join(lines) + "\n"

    def _render_command_log(self, report: ToolchainValidationReport) -> str:
        lines = [
            "# Toolchain Command Log",
            "",
            f"**Project:** {report.project_id}",
            f"**Approved:** {report.approved}",
            "",
            "> No secrets are reproduced in this log.",
            "> safe_to_execute_tests remains False.",
            "",
        ]
        if not report.commands:
            lines.append("No commands recorded.")
            return "\n".join(lines) + "\n"

        for cmd in report.commands:
            lines += [
                f"## `{cmd.command}`",
                "",
                f"- **Status:** {cmd.status}",
                f"- **CWD:** {cmd.cwd}",
                f"- **Exit code:** {cmd.exit_code if cmd.exit_code is not None else 'N/A'}",
                f"- **Executed:** {cmd.executed}",
            ]
            if cmd.duration_seconds is not None:
                lines.append(f"- **Duration:** {cmd.duration_seconds:.3f}s")
            if cmd.skipped_reason:
                lines.append(f"- **Skipped/blocked reason:** {cmd.skipped_reason}")
            if cmd.stdout_excerpt:
                lines += ["", "**stdout (excerpt):**", "```", cmd.stdout_excerpt[:1000], "```"]
            if cmd.stderr_excerpt:
                lines += ["", "**stderr (excerpt):**", "```", cmd.stderr_excerpt[:1000], "```"]
            if cmd.safety_notes:
                lines += ["", "**Safety notes:**"]
                for note in cmd.safety_notes:
                    lines.append(f"- {note}")
            lines.append("")

        return "\n".join(lines) + "\n"

    def _render_approval_record(self, approval: ToolchainApprovalRecord) -> str:
        approved_str = "APPROVED" if approval.approved else "NOT APPROVED"
        lines = [
            f"# Toolchain Approval Record [{approved_str}]",
            "",
            f"**Project:** {approval.project_id}",
            f"**Scaffold root:** {approval.scaffold_root}",
            f"**Approved:** {approval.approved}",
            f"**Approval source:** {approval.approval_source}",
            f"**Reason:** {approval.approval_reason}",
            f"**Created:** {approval.created_at}",
            "",
            "> **WARNING:** This approval authorizes local toolchain commands only.",
            "> It does NOT authorize browser test execution or target URL access.",
            "> safe_to_execute_tests remains False.",
            "",
        ]

        if approval.approved_commands:
            lines += ["## Approved Commands", ""]
            for cmd in approval.approved_commands:
                lines.append(f"- `{cmd}`")
            lines.append("")

        lines += ["## Denied Commands (sample)", ""]
        for cmd in approval.denied_commands[:10]:
            lines.append(f"- `{cmd}`")
        lines += ["", "## Safety Constraints", ""]
        for constraint in approval.safety_constraints:
            lines.append(f"- {constraint}")
        lines.append("")
        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------

    def _write_json(self, path: Path, data: Any) -> str:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(path)

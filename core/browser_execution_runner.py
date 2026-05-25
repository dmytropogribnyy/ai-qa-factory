"""Controlled Browser Execution Runner — Phase 4D.

Executes approved Playwright commands against narrowly allowlisted targets:
  - local / localhost
  - explicit public demo profiles (saucedemo_public_demo, the_internet_public_demo)
  - one public read-only profile: playwright_docs_readonly

SAFETY:
- subprocess.run is called ONLY for allowlisted commands.
- No .env reading. No credential injection.
- No production/high-risk/task-source targets.
- Alza.sk, Amazon.com, Linear.app always blocked.
- Playwright.dev only via --approve-public-readonly-execution + readonly_profile.
- Delivery flags always False (enforced by schema __post_init__).
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.schemas.browser_execution import (
    BrowserExecutionApproval,
    BrowserExecutionCommand,
    BrowserExecutionEvidence,
    BrowserExecutionReport,
)

_OUTPUTS_ROOT = Path("outputs")

# ---------------------------------------------------------------------------
# Demo and read-only profile registry
# ---------------------------------------------------------------------------

_DEMO_PROFILES: Dict[str, Dict[str, Any]] = {
    "saucedemo_public_demo": {
        "base_url": "https://www.saucedemo.com",
        "target_category": "public_demo_target",
        "approval_flag": "demo",
        "allowed_modes": {"list", "smoke"},
        "allowed_test_paths": ["tests/smoke"],
        "blocked_test_paths": ["tests/auth", "tests/regression", "tests/ecommerce", "tests/admin", "tests/api"],
        "description": "SauceDemo public practice e-commerce site",
    },
    "the_internet_public_demo": {
        "base_url": "https://the-internet.herokuapp.com",
        "target_category": "public_demo_target",
        "approval_flag": "demo",
        "allowed_modes": {"list", "smoke"},
        "allowed_test_paths": ["tests/smoke"],
        "blocked_test_paths": ["tests/auth", "tests/regression", "tests/ecommerce", "tests/admin", "tests/api"],
        "description": "The Internet (Herokuapp) public practice UI site",
    },
    "local": {
        "base_url": "http://localhost:3000",
        "target_category": "local",
        "approval_flag": "demo",
        "allowed_modes": {"list", "smoke"},
        "allowed_test_paths": ["tests/smoke"],
        "blocked_test_paths": [],
        "description": "Local development server (user must start separately)",
    },
}

_READONLY_PROFILES: Dict[str, Dict[str, Any]] = {
    "playwright_docs_readonly": {
        "base_url": "https://playwright.dev",
        "target_category": "real_public_readonly",
        "approval_flag": "public_readonly",
        "allowed_modes": {"list", "readonly_smoke"},
        "allowed_test_paths": ["tests/smoke"],
        "max_pages": 2,
        "description": "Playwright.dev public documentation — read-only smoke only",
    },
}

# ---------------------------------------------------------------------------
# Hard-blocked domains (always blocked regardless of approval)
# ---------------------------------------------------------------------------

_ALWAYS_BLOCKED_DOMAINS = [
    "alza.sk", "www.alza.sk",
    "amazon.com", "www.amazon.com",
    "linear.app", "app.linear.app",
]

# Playwright.dev is blocked unless readonly_profile=playwright_docs_readonly + public_readonly approval
_PLAYWRIGHT_DEV_DOMAIN = "playwright.dev"

# ---------------------------------------------------------------------------
# Allowlisted commands (only these may pass through subprocess)
# ---------------------------------------------------------------------------

_ALLOWED_COMMANDS = [
    "npx playwright test --list",
    "npx playwright test tests/smoke --reporter=list",
    "npx playwright test tests/smoke --reporter=html,list",
]

# Blocked command patterns (checked as substrings/prefixes in the full command)
_BLOCKED_COMMAND_PATTERNS = [
    "npm test",
    "npm run test",
    "npm run report",
    "--headed",
    "--ui",
    "tests/regression",
    "tests/auth",
    "tests/ecommerce",
    "tests/admin",
    "tests/api",
    "curl ",
    "wget ",
    "git clone",
]

# Environment variable prefixes to strip before subprocess
_SECRET_ENV_PATTERNS = [
    "PASSWORD", "SECRET", "TOKEN", "API_KEY",
    "PRIVATE_KEY", "CREDENTIAL", "AUTH", "COOKIE", "SESSION",
]

# Maximum stdout/stderr excerpt length
_EXCERPT_LIMIT = 2000


class BrowserExecutionRunner:
    """Runs approved controlled browser execution. subprocess only for allowlisted commands."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_browser_execution(
        self,
        project_id: str,
        scaffold_root: Optional[Path] = None,
        approve_demo: bool = False,
        approve_public_readonly: bool = False,
        target_category: Optional[str] = None,
        base_url: Optional[str] = None,
        demo_profile: Optional[str] = None,
        readonly_profile: Optional[str] = None,
        command_mode: str = "list",
        timeout: int = 120,
    ) -> BrowserExecutionReport:
        """Main entry point. Returns BrowserExecutionReport."""
        resolved_scaffold = self._resolve_scaffold_root(project_id, scaffold_root)

        # Resolve profile → target_category and base_url
        resolved_category, resolved_base_url, profile_meta = self._resolve_profile(
            target_category, base_url, demo_profile, readonly_profile,
            approve_demo, approve_public_readonly,
        )

        approval = self.build_approval(
            project_id=project_id,
            approve_demo=approve_demo,
            approve_public_readonly=approve_public_readonly,
            target_category=resolved_category,
            base_url=resolved_base_url,
            demo_profile=demo_profile,
            readonly_profile=readonly_profile,
            command_mode=command_mode,
        )

        report = BrowserExecutionReport(
            project_id=project_id,
            scaffold_root=str(resolved_scaffold),
            target_category=resolved_category,
            target_url=resolved_base_url,
            demo_profile=demo_profile,
            readonly_profile=readonly_profile,
            command_mode=command_mode,
            approved=approval.approved,
        )

        # Validate: block or proceed
        block_reason = self.validate_execution_allowed(
            approve_demo=approve_demo,
            approve_public_readonly=approve_public_readonly,
            target_category=resolved_category,
            base_url=resolved_base_url,
            demo_profile=demo_profile,
            readonly_profile=readonly_profile,
            command_mode=command_mode,
        )

        if block_reason:
            report.execution_status = "blocked"
            report.blockers.append(block_reason)
            cmd = self._build_blocked_command(command_mode, resolved_scaffold, block_reason)
            report.commands.append(cmd)
            report.notes.append("No subprocess executed.")
            report.notes.append("No browser launched.")
            report.notes.append("No credentials used.")
            return report

        # Approved: build and run command
        command_str, cmd_block_reason = self._build_command(
            command_mode=command_mode,
            readonly_profile=readonly_profile,
        )

        if cmd_block_reason:
            report.execution_status = "blocked"
            report.blockers.append(cmd_block_reason)
            cmd = self._build_blocked_command(command_mode, resolved_scaffold, cmd_block_reason)
            report.commands.append(cmd)
            return report

        exec_cmd, cmd_result = self._run_command(
            command_str=command_str,
            scaffold_root=resolved_scaffold,
            base_url=resolved_base_url,
            timeout=timeout,
        )
        report.commands.append(exec_cmd)

        # Set execution flags based on result
        if exec_cmd.executed:
            # list mode does not open browser; smoke/readonly_smoke may
            if command_mode in ("smoke", "readonly_smoke"):
                report.browser_execution_performed = True
                report.playwright_test_execution_performed = True
            else:
                # list command: playwright ran but not a browser test session
                report.playwright_test_execution_performed = True

            if readonly_profile == "playwright_docs_readonly":
                report.public_readonly_target_used = True

        report.execution_status = "complete" if exec_cmd.status == "pass" else "error"
        report.approved = True

        # Collect evidence references
        report.evidence = self.collect_evidence_references(
            project_id=project_id,
            scaffold_root=resolved_scaffold,
            command_mode=command_mode,
        )

        report.notes.extend([
            "Approved demo/local/public-readonly execution only.",
            f"Target category: {resolved_category}",
            f"Command mode: {command_mode}",
            "No credentials used.",
            "No general production target used.",
            "No client delivery created.",
            "Evidence internal-only.",
        ])

        return report

    def render_execution_artifacts(
        self,
        approval: BrowserExecutionApproval,
        report: BrowserExecutionReport,
        project_id: str,
    ) -> Dict[str, Path]:
        """Write execution artifacts to outputs/<project_id>/07_execution/."""
        out_dir = self._outputs_root / project_id / "07_execution"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: Dict[str, Path] = {}

        # Approval JSON/MD
        p = out_dir / "BROWSER_EXECUTION_APPROVAL.json"
        p.write_text(json.dumps(approval.to_dict(), indent=2), encoding="utf-8")
        paths["approval_json"] = p

        p = out_dir / "BROWSER_EXECUTION_APPROVAL.md"
        p.write_text(self._render_approval_md(approval), encoding="utf-8")
        paths["approval_md"] = p

        # Report JSON/MD
        p = out_dir / "BROWSER_EXECUTION_REPORT.json"
        p.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        paths["report_json"] = p

        p = out_dir / "BROWSER_EXECUTION_REPORT.md"
        p.write_text(self._render_report_md(report), encoding="utf-8")
        paths["report_md"] = p

        # Command log
        p = out_dir / "BROWSER_COMMAND_LOG.md"
        p.write_text(self._render_command_log_md(report), encoding="utf-8")
        paths["command_log_md"] = p

        # Evidence manifest JSON/MD
        p = out_dir / "BROWSER_EVIDENCE_MANIFEST.json"
        ev_data = {"project_id": project_id, "evidence": [e.to_dict() for e in report.evidence]}
        p.write_text(json.dumps(ev_data, indent=2), encoding="utf-8")
        paths["evidence_json"] = p

        p = out_dir / "BROWSER_EVIDENCE_MANIFEST.md"
        p.write_text(self._render_evidence_manifest_md(report), encoding="utf-8")
        paths["evidence_md"] = p

        return paths

    # ------------------------------------------------------------------
    # Approval construction
    # ------------------------------------------------------------------

    def build_approval(
        self,
        project_id: str,
        approve_demo: bool,
        approve_public_readonly: bool,
        target_category: str,
        base_url: Optional[str],
        demo_profile: Optional[str],
        readonly_profile: Optional[str],
        command_mode: str,
    ) -> BrowserExecutionApproval:
        """Construct the BrowserExecutionApproval record."""
        if not approve_demo and not approve_public_readonly:
            return BrowserExecutionApproval(
                project_id=project_id,
                approved=False,
                approval_source="none",
                approval_scope="no approval flag provided",
                approved_target_category="",
                notes=["No --approve-demo-execution or --approve-public-readonly-execution flag provided."],
            )

        block = self.validate_execution_allowed(
            approve_demo=approve_demo,
            approve_public_readonly=approve_public_readonly,
            target_category=target_category,
            base_url=base_url,
            demo_profile=demo_profile,
            readonly_profile=readonly_profile,
            command_mode=command_mode,
        )
        if block:
            return BrowserExecutionApproval(
                project_id=project_id,
                approved=False,
                approval_source="cli_flag",
                approval_scope="blocked",
                approved_target_category=target_category,
                notes=[block],
            )

        if approve_public_readonly and readonly_profile == "playwright_docs_readonly":
            scope = "playwright.dev public read-only smoke only"
            constraints = [
                "Read-only navigation to playwright.dev only.",
                "No form submissions, no login, no account creation.",
                "No crawling, scraping, load testing, or security testing.",
                "No credentials.",
                "No external API calls outside approved browser navigation.",
                "No client delivery. safe_to_deliver=False.",
                "Evidence internal-only.",
            ]
            approved_commands = [
                "npx playwright test --list",
                "npx playwright test tests/smoke --reporter=list",
                "npx playwright test tests/smoke --reporter=html,list",
            ]
        else:
            scope = "demo/local execution only"
            constraints = [
                "Demo/local targets only — no production/read-only/high-risk targets.",
                "No credentials used.",
                "No payment/checkout/order creation.",
                "No destructive/admin writes.",
                "No scraping/crawling/load/security testing.",
                "No client delivery. safe_to_deliver=False.",
                "Evidence internal-only.",
            ]
            approved_commands = [
                "npx playwright test --list",
                "npx playwright test tests/smoke --reporter=list",
                "npx playwright test tests/smoke --reporter=html,list",
            ]

        return BrowserExecutionApproval(
            project_id=project_id,
            approved=True,
            approval_source="cli_flag",
            approval_scope=scope,
            approved_target_category=target_category,
            approved_target_url=base_url,
            demo_profile=demo_profile,
            readonly_profile=readonly_profile,
            approved_commands=approved_commands,
            denied_commands=[
                "npm test", "npm run test", "npm run test:headed",
                "npm run test:ui", "npm run report",
                "npx playwright test (unrestricted)",
                "npx playwright test tests/regression",
                "npx playwright test tests/auth",
                "npx playwright test tests/ecommerce",
                "npx playwright test tests/admin",
                "any command with --headed",
                "any command with external URL in arguments",
                "curl/wget", "git clone",
            ],
            safety_constraints=constraints,
            notes=[
                "This does not authorize general production/client execution.",
                "This does not authorize credentials/auth/payment/destructive actions.",
                "This does not authorize scraping/crawling/load/security testing.",
                "This does not authorize client delivery.",
            ],
        )

    # ------------------------------------------------------------------
    # Target classification and validation
    # ------------------------------------------------------------------

    def classify_target_category(
        self,
        target_category: Optional[str],
        base_url: Optional[str],
        demo_profile: Optional[str],
        readonly_profile: Optional[str],
    ) -> str:
        """Determine effective target category from available inputs."""
        if readonly_profile and readonly_profile in _READONLY_PROFILES:
            return _READONLY_PROFILES[readonly_profile]["target_category"]
        if demo_profile and demo_profile in _DEMO_PROFILES:
            return _DEMO_PROFILES[demo_profile]["target_category"]
        if target_category:
            return target_category
        if base_url:
            url_lower = base_url.lower()
            if "localhost" in url_lower or "127.0.0.1" in url_lower:
                return "local"
            for domain in _ALWAYS_BLOCKED_DOMAINS:
                if domain in url_lower:
                    return "unknown"
            if _PLAYWRIGHT_DEV_DOMAIN in url_lower:
                return "real_public_readonly"
        return "unknown"

    def validate_execution_allowed(
        self,
        approve_demo: bool,
        approve_public_readonly: bool,
        target_category: str,
        base_url: Optional[str],
        demo_profile: Optional[str],
        readonly_profile: Optional[str],
        command_mode: str,
    ) -> Optional[str]:
        """Return a block reason string, or None if execution is allowed."""
        # No approval at all
        if not approve_demo and not approve_public_readonly:
            return "No approval flag provided. Use --approve-demo-execution or --approve-public-readonly-execution."

        # Check hard-blocked URLs
        if base_url:
            block = self._check_hard_blocked_url(
                base_url=base_url,
                approve_public_readonly=approve_public_readonly,
                readonly_profile=readonly_profile,
            )
            if block:
                return block

        # Category-level blocks
        if target_category in ("production",):
            return f"Target category '{target_category}' is blocked in Phase 4D. No general production execution."

        if target_category == "high_risk_marketplace_readonly":
            return "high_risk_marketplace_readonly targets are always blocked (includes Amazon.com)."

        if target_category == "task_source":
            return "task_source targets (Linear/Jira/ClickUp task URLs) are always blocked as execution targets."

        # real_public_readonly: only playwright_docs_readonly + public_readonly approval
        if target_category == "real_public_readonly":
            if not approve_public_readonly:
                return "real_public_readonly requires --approve-public-readonly-execution."
            if readonly_profile != "playwright_docs_readonly":
                return (
                    "real_public_readonly execution requires readonly_profile=playwright_docs_readonly. "
                    "All other read-only targets are blocked."
                )

        # playwright_docs_readonly must NOT run with only --approve-demo-execution
        if readonly_profile == "playwright_docs_readonly" and not approve_public_readonly:
            return "playwright_docs_readonly requires --approve-public-readonly-execution, not --approve-demo-execution."

        # public_readonly-only approval: only real_public_readonly + playwright_docs_readonly allowed.
        # Demo/local/public_demo_target require --approve-demo-execution.
        if approve_public_readonly and not approve_demo:
            if target_category != "real_public_readonly":
                return (
                    f"--approve-public-readonly-execution alone does not allow "
                    f"'{target_category}' targets. Use --approve-demo-execution for demo/local."
                )

        # Demo/local approval checks
        if approve_demo and not approve_public_readonly:
            if target_category not in ("local", "localhost", "public_demo_target"):
                return (
                    f"--approve-demo-execution only allows local/localhost/public_demo_target. "
                    f"Got: '{target_category}'."
                )
            if readonly_profile == "playwright_docs_readonly":
                return "playwright_docs_readonly requires --approve-public-readonly-execution."

        # unknown category: only allowed if no real URL or localhost
        if target_category == "unknown":
            if base_url and "localhost" not in base_url.lower() and "127.0.0.1" not in base_url.lower():
                return f"Unknown target category with non-localhost URL '{base_url}' is blocked."

        # Command mode validation
        if demo_profile and demo_profile in _DEMO_PROFILES:
            allowed_modes = _DEMO_PROFILES[demo_profile]["allowed_modes"]
            if command_mode not in allowed_modes:
                return f"command_mode='{command_mode}' not allowed for demo profile '{demo_profile}'."

        if readonly_profile and readonly_profile in _READONLY_PROFILES:
            allowed_modes = _READONLY_PROFILES[readonly_profile]["allowed_modes"]
            if command_mode not in allowed_modes:
                return f"command_mode='{command_mode}' not allowed for readonly profile '{readonly_profile}'."

        return None  # allowed

    def _check_hard_blocked_url(
        self,
        base_url: str,
        approve_public_readonly: bool,
        readonly_profile: Optional[str],
    ) -> Optional[str]:
        """Return block reason if URL is hard-blocked."""
        url_lower = base_url.lower()
        for domain in _ALWAYS_BLOCKED_DOMAINS:
            if domain in url_lower:
                if "alza" in url_lower:
                    return f"Alza.sk is always blocked as an execution target. URL: {base_url}"
                if "amazon" in url_lower:
                    return f"Amazon.com is always blocked as an execution target. URL: {base_url}"
                if "linear.app" in url_lower:
                    return f"Linear.app is always blocked as an execution target (task source only). URL: {base_url}"
                return f"Domain is blocked as an execution target. URL: {base_url}"

        # Playwright.dev: only with correct approval + readonly profile
        if _PLAYWRIGHT_DEV_DOMAIN in url_lower:
            if not approve_public_readonly or readonly_profile != "playwright_docs_readonly":
                return (
                    f"playwright.dev requires --approve-public-readonly-execution "
                    f"and --readonly-profile playwright_docs_readonly. URL: {base_url}"
                )

        return None

    # ------------------------------------------------------------------
    # Profile resolution
    # ------------------------------------------------------------------

    def _resolve_profile(
        self,
        target_category: Optional[str],
        base_url: Optional[str],
        demo_profile: Optional[str],
        readonly_profile: Optional[str],
        approve_demo: bool,
        approve_public_readonly: bool,
    ) -> Tuple[str, Optional[str], Dict[str, Any]]:
        """Resolve effective (category, base_url, profile_meta) from inputs."""
        if readonly_profile and readonly_profile in _READONLY_PROFILES:
            meta = _READONLY_PROFILES[readonly_profile]
            return meta["target_category"], base_url or meta["base_url"], meta

        if demo_profile and demo_profile in _DEMO_PROFILES:
            meta = _DEMO_PROFILES[demo_profile]
            return meta["target_category"], base_url or meta["base_url"], meta

        resolved_cat = self.classify_target_category(
            target_category, base_url, demo_profile, readonly_profile
        )
        return resolved_cat, base_url, {}

    def _resolve_scaffold_root(
        self,
        project_id: str,
        scaffold_root: Optional[Path],
    ) -> Path:
        if scaffold_root:
            return scaffold_root
        return self._outputs_root / project_id / "03_framework" / "playwright"

    # ------------------------------------------------------------------
    # Command building and execution
    # ------------------------------------------------------------------

    def _build_command(
        self,
        command_mode: str,
        readonly_profile: Optional[str],
    ) -> Tuple[str, Optional[str]]:
        """Return (command_string, block_reason). block_reason is None if allowed."""
        if command_mode == "list":
            cmd = "npx playwright test --list"
        elif command_mode in ("smoke", "readonly_smoke"):
            cmd = "npx playwright test tests/smoke --reporter=list"
        else:
            return "", f"Unknown command_mode: '{command_mode}'."

        block = self._check_command_blocked(cmd)
        if block:
            return cmd, block

        return cmd, None

    def is_command_allowed(self, command: str) -> bool:
        """Return True if command is in the allowlist and not in blocklist."""
        cmd_stripped = command.strip()
        if cmd_stripped not in _ALLOWED_COMMANDS:
            return False
        return not self._check_command_blocked(cmd_stripped)

    def _check_command_blocked(self, command: str) -> Optional[str]:
        """Return block reason if command matches a blocked pattern."""
        cmd_lower = command.lower()
        for pattern in _BLOCKED_COMMAND_PATTERNS:
            if pattern.lower() in cmd_lower:
                return f"Command contains blocked pattern '{pattern}': {command}"
        if command.strip() not in _ALLOWED_COMMANDS:
            return f"Command not in allowlist: {command}"
        return None

    def build_safe_env(self, base_url: Optional[str]) -> Dict[str, str]:
        """Build a sanitized environment dict stripping secrets."""
        env = dict(os.environ)
        # Strip secret-like variables
        to_remove = [
            k for k in env
            if any(pat in k.upper() for pat in _SECRET_ENV_PATTERNS)
        ]
        for k in to_remove:
            del env[k]
        # Set safe overrides
        env["BASE_URL"] = base_url or "http://localhost:3000"
        env["API_BASE_URL"] = "http://localhost:3000"
        env["TEST_USERNAME"] = ""
        env["TEST_PASSWORD"] = ""
        return env

    def _run_command(
        self,
        command_str: str,
        scaffold_root: Path,
        base_url: Optional[str],
        timeout: int,
    ) -> Tuple[BrowserExecutionCommand, Optional[Exception]]:
        """Run allowlisted command via subprocess. Returns (command_record, error_or_None)."""
        cmd_id = f"cmd_{datetime.now(timezone.utc).strftime('%H%M%S')}"
        safe_env = self.build_safe_env(base_url)

        cmd_record = BrowserExecutionCommand(
            id=cmd_id,
            command=command_str,
            cwd=str(scaffold_root),
            safety_notes=[
                "Subprocess used only for allowlisted commands.",
                "Secrets stripped from environment.",
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
            cmd_record.stdout_excerpt = result.stdout[:_EXCERPT_LIMIT]
            cmd_record.stderr_excerpt = result.stderr[:_EXCERPT_LIMIT]
            cmd_record.executed = True
            cmd_record.status = "pass" if result.returncode == 0 else "fail"
        except FileNotFoundError as exc:
            cmd_record.status = "fail"
            cmd_record.executed = False
            cmd_record.skipped_reason = f"Command not found (dependencies not installed?): {exc}"
        except subprocess.TimeoutExpired:
            cmd_record.status = "fail"
            cmd_record.executed = True
            cmd_record.skipped_reason = f"Command timed out after {timeout}s."
        except Exception as exc:  # noqa: BLE001
            cmd_record.status = "fail"
            cmd_record.executed = False
            cmd_record.skipped_reason = f"Unexpected error: {exc}"
            return cmd_record, exc

        return cmd_record, None

    def _build_blocked_command(
        self,
        command_mode: str,
        scaffold_root: Path,
        block_reason: str,
    ) -> BrowserExecutionCommand:
        return BrowserExecutionCommand(
            id="cmd_blocked",
            command=f"[BLOCKED: {command_mode}]",
            cwd=str(scaffold_root),
            status="blocked",
            executed=False,
            skipped_reason=block_reason,
            safety_notes=["No subprocess called. Execution blocked by approval gate."],
        )

    # ------------------------------------------------------------------
    # Evidence collection
    # ------------------------------------------------------------------

    def collect_evidence_references(
        self,
        project_id: str,
        scaffold_root: Path,
        command_mode: str,
    ) -> List[BrowserExecutionEvidence]:
        """Collect path-based references to evidence without copying files."""
        evidence: List[BrowserExecutionEvidence] = []
        ev_id = 0

        # Command log (always)
        ev_id += 1
        evidence.append(BrowserExecutionEvidence(
            id=f"be_{ev_id:03d}",
            evidence_type="command_log",
            path=str(self._outputs_root / project_id / "07_execution" / "BROWSER_COMMAND_LOG.md"),
            title="Browser Command Log",
            description="Command execution log for Phase 4D browser execution.",
        ))

        # Playwright report (may exist after smoke run)
        ev_id += 1
        evidence.append(BrowserExecutionEvidence(
            id=f"be_{ev_id:03d}",
            evidence_type="playwright_report",
            path=str(scaffold_root / "playwright-report"),
            title="Playwright HTML Report",
            description="Playwright HTML report directory (if generated by smoke run).",
            notes=["Path reference only. May not exist if list-only or dependencies absent."],
        ))

        # Test results
        ev_id += 1
        evidence.append(BrowserExecutionEvidence(
            id=f"be_{ev_id:03d}",
            evidence_type="test_results",
            path=str(scaffold_root / "test-results"),
            title="Playwright Test Results",
            description="Test results directory with traces/screenshots/videos.",
            notes=["Path reference only. Only populated after actual smoke run."],
        ))

        # Execution summary
        ev_id += 1
        evidence.append(BrowserExecutionEvidence(
            id=f"be_{ev_id:03d}",
            evidence_type="execution_summary",
            path=str(self._outputs_root / project_id / "07_execution" / "BROWSER_EXECUTION_REPORT.md"),
            title="Browser Execution Summary",
            description="Human-readable execution report for Phase 4D.",
        ))

        return evidence

    # ------------------------------------------------------------------
    # Markdown rendering
    # ------------------------------------------------------------------

    def _render_approval_md(self, approval: BrowserExecutionApproval) -> str:
        lines = [
            "# Browser Execution Approval",
            "",
            f"**Project:** `{approval.project_id}`",
            f"**Approved:** `{approval.approved}`",
            f"**Approval Source:** `{approval.approval_source}`",
            f"**Approval Scope:** {approval.approval_scope}",
            f"**Target Category:** `{approval.approved_target_category}`",
        ]
        if approval.demo_profile:
            lines.append(f"**Demo Profile:** `{approval.demo_profile}`")
        if approval.readonly_profile:
            lines.append(f"**Read-Only Profile:** `{approval.readonly_profile}`")
        if approval.approved_target_url:
            lines.append(f"**Approved Target URL:** `{approval.approved_target_url}`")
        lines.extend(["", "## Safety Constraints", ""])
        for c in approval.safety_constraints:
            lines.append(f"- {c}")
        lines.extend(["", "## Approved Commands", ""])
        for c in approval.approved_commands:
            lines.append(f"- `{c}`")
        lines.extend(["", "## Denied Commands", ""])
        for c in approval.denied_commands:
            lines.append(f"- {c}")
        lines.extend(["", "## Notes", ""])
        for n in approval.notes:
            lines.append(f"- {n}")
        return "\n".join(lines) + "\n"

    def _render_report_md(self, report: BrowserExecutionReport) -> str:
        lines = [
            "# Browser Execution Report",
            "",
            "> **Approved demo/local/public-readonly execution only.**  ",
            "> No general production execution. No client delivery.",
            "",
            f"**Project:** `{report.project_id}`",
            f"**Execution Status:** `{report.execution_status}`",
            f"**Approved:** `{report.approved}`",
            f"**Target Category:** `{report.target_category}`",
            f"**Command Mode:** `{report.command_mode}`",
        ]
        if report.demo_profile:
            lines.append(f"**Demo Profile:** `{report.demo_profile}`")
        if report.readonly_profile:
            lines.append(f"**Read-Only Profile:** `{report.readonly_profile}`")
        if report.target_url:
            lines.append(f"**Target URL:** `{report.target_url}`")
        lines.extend([
            "",
            "## Execution Flags",
            "",
            "| Flag | Value |",
            "|------|-------|",
            f"| browser_execution_performed | `{report.browser_execution_performed}` |",
            f"| playwright_test_execution_performed | `{report.playwright_test_execution_performed}` |",
            f"| production_target_used | `{report.production_target_used}` |",
            f"| public_readonly_target_used | `{report.public_readonly_target_used}` |",
            f"| credentials_used | `{report.credentials_used}` |",
            f"| external_calls_performed | `{report.external_calls_performed}` |",
            f"| destructive_actions_performed | `{report.destructive_actions_performed}` |",
            f"| client_delivery_created | `{report.client_delivery_created}` |",
            f"| safe_to_deliver | `{report.safe_to_deliver}` |",
            f"| approved_for_client_delivery | `{report.approved_for_client_delivery}` |",
        ])
        if report.blockers:
            lines.extend(["", "## Blockers", ""])
            for b in report.blockers:
                lines.append(f"- {b}")
        if report.warnings:
            lines.extend(["", "## Warnings", ""])
            for w in report.warnings:
                lines.append(f"- {w}")
        lines.extend(["", "## Commands", ""])
        for cmd in report.commands:
            lines.append(f"- `{cmd.command}` — status={cmd.status}, executed={cmd.executed}")
            if cmd.skipped_reason:
                lines.append(f"  - Reason: {cmd.skipped_reason}")
        lines.extend(["", "## Evidence", ""])
        for ev in report.evidence:
            lines.append(f"- [{ev.title}]({ev.path}) — internal_only={ev.internal_only}, client_visible={ev.client_visible}")
        lines.extend(["", "## Notes", ""])
        for n in report.notes:
            lines.append(f"- {n}")
        return "\n".join(lines) + "\n"

    def _render_command_log_md(self, report: BrowserExecutionReport) -> str:
        lines = [
            "# Browser Command Log",
            "",
            f"**Project:** `{report.project_id}`",
            f"**Execution Status:** `{report.execution_status}`",
            "",
            "## Commands",
            "",
        ]
        for cmd in report.commands:
            lines.extend([
                f"### `{cmd.command}`",
                f"- Status: `{cmd.status}`",
                f"- Executed: `{cmd.executed}`",
                f"- CWD: `{cmd.cwd}`",
            ])
            if cmd.exit_code is not None:
                lines.append(f"- Exit code: `{cmd.exit_code}`")
            if cmd.duration_seconds is not None:
                lines.append(f"- Duration: `{cmd.duration_seconds}s`")
            if cmd.skipped_reason:
                lines.append(f"- Reason: {cmd.skipped_reason}")
            if cmd.stdout_excerpt:
                lines.extend(["", "**stdout:**", "```", cmd.stdout_excerpt[:500], "```"])
            if cmd.stderr_excerpt:
                lines.extend(["", "**stderr:**", "```", cmd.stderr_excerpt[:500], "```"])
            lines.append("")
        return "\n".join(lines)

    def _render_evidence_manifest_md(self, report: BrowserExecutionReport) -> str:
        lines = [
            "# Browser Evidence Manifest",
            "",
            f"**Project:** `{report.project_id}`",
            "**All evidence internal-only by default.**",
            "",
            "| ID | Type | Title | internal_only | client_visible |",
            "|----|------|-------|---------------|----------------|",
        ]
        for ev in report.evidence:
            lines.append(f"| {ev.id} | {ev.evidence_type} | {ev.title} | {ev.internal_only} | {ev.client_visible} |")
        lines.extend(["", "## Notes", ""])
        lines.append("- client_visible=False for all evidence records.")
        lines.append("- requires_redaction=True for all evidence records.")
        lines.append("- No evidence approved for client view.")
        return "\n".join(lines) + "\n"

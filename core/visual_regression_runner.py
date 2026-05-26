"""
Phase 5I — Visual Regression Runner.

Playwright toHaveScreenshot()-based visual regression testing.
Generates a temporary visual regression config + spec file, runs Playwright,
then parses results and baseline metadata.

Modes:
- capture: first run, creates baseline screenshots
- compare: diff against baselines, reports failures
- update:  update baselines after approved intentional change

SAFETY:
- No credentials, no auth.
- Baselines stored in outputs/<project_id>/18_visual_regression/baselines/ (gitignored).
- safe_to_deliver=False always.
- Human review required before any client-facing use.
"""
from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from core.schemas.visual_regression import (
    VISUAL_REGRESSION_MODES,
    VisualBaselineRecord,
    VisualRegressionReport,
)

_OUTPUTS_ROOT = Path("outputs")
_EXCERPT_LIMIT = 2000

# Allowed target URL prefixes for visual regression
_ALLOWED_URL_PREFIXES = (
    "http://localhost",
    "http://127.0.0.1",
    "https://www.saucedemo.com",
    "https://the-internet.herokuapp.com",
    "https://practicesoftwaretesting.com",
    "https://demoqa.com",
    "https://opensource-demo.orangehrmlive.com",
    "https://restful-booker.herokuapp.com",
    "https://playwright.dev",
    "https://www.amazon.com",
    "https://www.alza.sk",
)

# Blocked URL patterns (auth/payment/admin) — applied for public targets
_BLOCKED_URL_PATTERNS = (
    "/signin", "/login", "/cart", "/checkout", "/account",
    "/order", "/payment", "/admin", "/settings",
)


class VisualRegressionRunner:
    """Runs Playwright visual regression (baseline capture / screenshot comparison)."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        project_id: str,
        target_url: str,
        mode: str = "compare",
        device_name: str = "",
        scaffold_root: Optional[Path] = None,
        approve_visual_regression: bool = False,
        threshold_ratio: float = 0.01,
        timeout: int = 120,
    ) -> VisualRegressionReport:
        """Main entry point. Returns VisualRegressionReport."""
        report = VisualRegressionReport(
            project_id=project_id,
            mode=mode,
            device_name=device_name,
            target_url=target_url,
        )

        # Gate 1: approval
        if not approve_visual_regression:
            return self._blocked(report, "Missing --approve-visual-regression flag.")

        # Gate 2: mode
        if mode not in VISUAL_REGRESSION_MODES:
            return self._blocked(
                report,
                f"Unknown mode '{mode}'. Supported: {', '.join(VISUAL_REGRESSION_MODES)}",
            )

        # Gate 3: target URL allowlist
        url_lower = target_url.lower()
        if not any(url_lower.startswith(pfx.lower()) for pfx in _ALLOWED_URL_PREFIXES):
            return self._blocked(
                report,
                f"Target URL not in allowlist: {target_url}. "
                f"Add to _ALLOWED_URL_PREFIXES for approval.",
            )

        # Gate 4: blocked path check for public targets
        for blocked in _BLOCKED_URL_PATTERNS:
            if blocked in url_lower:
                return self._blocked(
                    report,
                    f"Target URL contains blocked path '{blocked}': {target_url}",
                )

        resolved_scaffold = scaffold_root or (
            self._outputs_root / project_id / "03_framework" / "playwright"
        )

        # Baseline directory
        baseline_dir = self._outputs_root / project_id / "18_visual_regression" / "baselines"
        baseline_dir.mkdir(parents=True, exist_ok=True)

        # Build and write visual regression spec
        spec_path = resolved_scaffold / "tests" / "smoke" / "visual_regression.spec.ts"
        try:
            spec_path.parent.mkdir(parents=True, exist_ok=True)
            spec_path.write_text(
                self._build_spec(target_url=target_url, threshold_ratio=threshold_ratio),
                encoding="utf-8",
            )
        except OSError as exc:
            return self._blocked(report, f"Could not write visual regression spec: {exc}")

        # Choose command
        if mode == "capture":
            cmd_str = "npx playwright test tests/smoke/visual_regression.spec.ts --reporter=list --update-snapshots"
        elif mode == "update":
            cmd_str = "npx playwright test tests/smoke/visual_regression.spec.ts --reporter=list --update-snapshots"
        else:  # compare
            cmd_str = "npx playwright test tests/smoke/visual_regression.spec.ts --reporter=list"

        exec_result = self._run_command(
            cmd_str=cmd_str,
            scaffold_root=resolved_scaffold,
            base_url=target_url,
            timeout=timeout,
        )

        # Parse output for pass/fail counts
        passed, failed = self._parse_counts(exec_result.get("stdout", ""))
        report.total_tests = passed + failed
        report.passed = passed
        report.failed = failed
        report.execution_status = "complete" if exec_result.get("returncode", 1) == 0 else "error"
        report.approved = True
        report.notes.extend([
            f"Mode: {mode}",
            f"Device: {device_name or 'desktop'}",
            f"Threshold: {threshold_ratio:.1%}",
            "safe_to_deliver=False always.",
            "human_review_required=True always.",
        ])

        # Record baseline metadata for capture/update modes
        if mode in ("capture", "update"):
            snapshots_dir = resolved_scaffold / "tests" / "smoke" / "visual_regression.spec.ts-snapshots"
            if snapshots_dir.exists():
                for f in snapshots_dir.glob("*.png"):
                    report.baselines.append(VisualBaselineRecord(
                        test_name=f.stem,
                        screenshot_filename=f.name,
                        device_name=device_name or "desktop",
                        viewport=f"device:{device_name}" if device_name else "default",
                        target_url=target_url,
                        captured_at=datetime.now(timezone.utc).isoformat(),
                        file_size_bytes=f.stat().st_size,
                    ))
            report.new_baselines = len(report.baselines)

        # Cleanup generated spec (keep baselines)
        try:
            spec_path.unlink(missing_ok=True)
        except OSError:
            pass

        return report

    def render_artifacts(
        self,
        report: VisualRegressionReport,
        project_id: str,
    ) -> Dict[str, Path]:
        """Write artifacts to outputs/<project_id>/18_visual_regression/."""
        out_dir = self._outputs_root / project_id / "18_visual_regression"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: Dict[str, Path] = {}

        p = out_dir / "VISUAL_REGRESSION_REPORT.json"
        p.write_text(json.dumps(self._report_to_dict(report), indent=2), encoding="utf-8")
        paths["report_json"] = p

        p = out_dir / "VISUAL_REGRESSION_REPORT.md"
        p.write_text(self._render_md(report), encoding="utf-8")
        paths["report_md"] = p

        return paths

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _blocked(self, report: VisualRegressionReport, reason: str) -> VisualRegressionReport:
        report.execution_status = "blocked"
        report.blockers.append(reason)
        return report

    def _build_spec(self, target_url: str, threshold_ratio: float) -> str:
        safe_url = target_url.replace("'", "")
        return (
            "// Visual regression spec — generated by visual_regression_runner.py\n"
            "// Runtime only — not committed\n"
            "import { test, expect } from '@playwright/test';\n"
            "\n"
            f"const TARGET_URL = '{safe_url}';\n"
            f"const THRESHOLD = {threshold_ratio};\n"
            "\n"
            "test('visual regression — page load', async ({ page }) => {{\n"
            "  await page.goto(TARGET_URL);\n"
            "  await page.waitForLoadState('networkidle');\n"
            f"  await expect(page).toHaveScreenshot('page-load.png', {{ maxDiffRatio: THRESHOLD }});\n"
            "}});\n"
        )

    def _run_command(
        self,
        cmd_str: str,
        scaffold_root: Path,
        base_url: str,
        timeout: int,
    ) -> Dict[str, Any]:
        cmd_parts = cmd_str.split()
        if os.name == "nt" and cmd_parts[0] == "npx":
            cmd_parts[0] = "npx.cmd"

        env = dict(os.environ)
        for k in list(env.keys()):
            if any(p in k.upper() for p in ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "CREDENTIAL")):
                del env[k]
        env["BASE_URL"] = base_url

        try:
            result = subprocess.run(
                cmd_parts,
                cwd=str(scaffold_root),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            return {
                "returncode": result.returncode,
                "stdout": result.stdout[:_EXCERPT_LIMIT],
                "stderr": result.stderr[:_EXCERPT_LIMIT],
            }
        except Exception as exc:
            return {"returncode": 1, "stdout": "", "stderr": str(exc)}

    def _parse_counts(self, stdout: str) -> tuple:
        """Parse 'X passed', 'Y failed' from Playwright output."""
        passed = 0
        failed = 0
        for line in stdout.splitlines():
            line_lower = line.lower()
            if "passed" in line_lower:
                for part in line_lower.split():
                    if part.isdigit():
                        passed = int(part)
                        break
            if "failed" in line_lower:
                for part in line_lower.split():
                    if part.isdigit():
                        failed = int(part)
                        break
        return passed, failed

    def _report_to_dict(self, report: VisualRegressionReport) -> Dict[str, Any]:
        return {
            "project_id": report.project_id,
            "mode": report.mode,
            "device_name": report.device_name,
            "target_url": report.target_url,
            "total_tests": report.total_tests,
            "passed": report.passed,
            "failed": report.failed,
            "new_baselines": report.new_baselines,
            "errors": report.errors,
            "execution_status": report.execution_status,
            "blockers": report.blockers,
            "notes": report.notes,
            "credentials_used": report.credentials_used,
            "auth_performed": report.auth_performed,
            "safe_to_deliver": report.safe_to_deliver,
            "approved_for_client_delivery": report.approved_for_client_delivery,
            "human_review_required": report.human_review_required,
            "baselines_committed": report.baselines_committed,
            "baselines": [b.to_dict() for b in report.baselines],
            "results": [r.to_dict() for r in report.results],
        }

    def _render_md(self, report: VisualRegressionReport) -> str:
        status_icon = "PASS" if report.execution_status == "complete" and not report.failed else "FAIL"
        lines = [
            f"# Visual Regression Report — [{status_icon}]",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Mode:** `{report.mode}`  ",
            f"**Device:** `{report.device_name or 'desktop'}`  ",
            f"**Target:** `{report.target_url}`  ",
            f"**Status:** `{report.execution_status}`  ",
            f"**Tests:** {report.total_tests} total / {report.passed} passed / {report.failed} failed  ",
            "",
            "## Safety",
            "",
            "| Property | Value |",
            "|---|---|",
            "| credentials_used | `False` |",
            "| auth_performed | `False` |",
            "| safe_to_deliver | `False` |",
            "| approved_for_client_delivery | `False` |",
            "| human_review_required | `True` |",
            "| baselines_committed | `False` |",
            "",
        ]
        if report.blockers:
            lines += ["## Blockers", ""]
            for b in report.blockers:
                lines.append(f"- {b}")
            lines.append("")
        if report.baselines:
            lines += [f"## Baselines Captured ({len(report.baselines)})", ""]
            for b in report.baselines:
                lines.append(f"- `{b.screenshot_filename}` — {b.file_size_bytes} bytes")
            lines.append("")
        return "\n".join(lines)

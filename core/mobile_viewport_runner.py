"""
Phase 5I — Mobile Viewport Emulation Runner.

Runs approved Playwright tests with device viewport emulation.
Works by generating a temporary mobile.config.cjs with Playwright device
settings, then running npx playwright test via subprocess.

Extends the ecommerce readonly model:
- amazon_mobile_readonly: Amazon mobile web (same path-gates as desktop)
- alza_mobile_readonly: Alza mobile web (same path-gates as desktop)

SAFETY:
- No credentials. No auth. No personal or production accounts.
- Same ecommerce path-gate and selector-scan as Phase 5H browser runner.
- Generated config files are runtime-only (gitignored).
- safe_to_deliver=False always.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.schemas.mobile_viewport import (
    MOBILE_VIEWPORT_DEVICES,
    MOBILE_VIEWPORT_MODES,
    MobileViewportExecutionCommand,
    MobileViewportExecutionReport,
    MobileViewportProfile,
)

_OUTPUTS_ROOT = Path("outputs")
_EXCERPT_LIMIT = 2000

# ---------------------------------------------------------------------------
# Device registry — maps device name to Playwright config
# ---------------------------------------------------------------------------

_PLAYWRIGHT_DEVICES: Dict[str, Dict[str, Any]] = {
    "iPhone 14": {
        "playwright_name": "iPhone 14",
        "viewport": {"width": 390, "height": 844},
        "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
        "deviceScaleFactor": 3,
        "isMobile": True,
        "hasTouch": True,
    },
    "iPhone 14 Pro": {
        "playwright_name": "iPhone 14 Pro",
        "viewport": {"width": 393, "height": 852},
        "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
        "deviceScaleFactor": 3,
        "isMobile": True,
        "hasTouch": True,
    },
    "iPhone 13": {
        "playwright_name": "iPhone 13",
        "viewport": {"width": 390, "height": 844},
        "userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15",
        "deviceScaleFactor": 3,
        "isMobile": True,
        "hasTouch": True,
    },
    "Pixel 7": {
        "playwright_name": "Pixel 7",
        "viewport": {"width": 412, "height": 915},
        "userAgent": "Mozilla/5.0 (Linux; Android 13; Pixel 7) AppleWebKit/537.36",
        "deviceScaleFactor": 2.625,
        "isMobile": True,
        "hasTouch": True,
    },
    "Pixel 5": {
        "playwright_name": "Pixel 5",
        "viewport": {"width": 393, "height": 851},
        "userAgent": "Mozilla/5.0 (Linux; Android 11; Pixel 5) AppleWebKit/537.36",
        "deviceScaleFactor": 2.75,
        "isMobile": True,
        "hasTouch": True,
    },
    "Galaxy S22": {
        "playwright_name": "Galaxy S22",
        "viewport": {"width": 360, "height": 780},
        "userAgent": "Mozilla/5.0 (Linux; Android 12; SM-S901B) AppleWebKit/537.36",
        "deviceScaleFactor": 3,
        "isMobile": True,
        "hasTouch": True,
    },
    "iPad Pro": {
        "playwright_name": "iPad Pro 11",
        "viewport": {"width": 834, "height": 1194},
        "userAgent": "Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
        "deviceScaleFactor": 2,
        "isMobile": True,
        "hasTouch": True,
    },
    "iPad Mini": {
        "playwright_name": "iPad Mini",
        "viewport": {"width": 768, "height": 1024},
        "userAgent": "Mozilla/5.0 (iPad; CPU OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
        "deviceScaleFactor": 2,
        "isMobile": True,
        "hasTouch": True,
    },
}

# Mobile ecommerce readonly profiles (same path-gates as Phase 5H desktop)
_MOBILE_ECOMMERCE_PROFILES: Dict[str, Dict[str, Any]] = {
    "amazon_mobile_readonly": {
        "base_url": "https://www.amazon.com",
        "target_category": "ecommerce_public_readonly",
        "blocked_url_paths": [
            "/signin", "/ap/signin", "/ap/cvf", "/gp/cart", "/cart",
            "/checkout", "/account", "/order", "/orders", "/payment",
            "/wishlist", "/address-book", "/subscribe", "/memberships",
            "/ap/forgotpassword", "/your-account", "/hz/mycd",
        ],
        "description": "Amazon mobile web — public product/search pages via device emulation",
    },
    "alza_mobile_readonly": {
        "base_url": "https://www.alza.sk",
        "target_category": "ecommerce_public_readonly",
        "blocked_url_paths": [
            "/prihlasit", "/registracia", "/odhlasit", "/kosik", "/platba",
            "/objednavka", "/moj-ucet", "/login", "/signin", "/cart",
            "/checkout", "/order", "/account", "/logout",
        ],
        "description": "Alza mobile web — public product/category pages via device emulation",
    },
}

# Blocked command patterns
_BLOCKED_PATTERNS = [
    "tests/auth", "tests/regression", "tests/ecommerce",
    "tests/admin", "tests/api", "--headed", "--ui",
    "curl ", "wget ", "git clone",
]

# Ecommerce dangerous selector patterns (same as Phase 5H)
_ECOMMERCE_DANGEROUS_PATTERNS = [
    "add-to-cart", "add_to_cart", "addtocart", "addToCart",
    "buy-now", "buy_now", "buynow", "buyNow",
    "proceed-to-checkout", "place-order", "submit-order",
    "checkout-button", "/cart", "/checkout", "/order", "/payment",
    "sign-in", "signin", "login-button", "password", "/signin",
    "page.fill", "page.type", "page.selectOption",
    "wishlist", "add-to-list",
]


class MobileViewportRunner:
    """Runs Playwright tests with mobile device viewport emulation."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        project_id: str,
        device_name: str,
        command_mode: str = "viewport_smoke",
        target_url: Optional[str] = None,
        readonly_profile: Optional[str] = None,
        scaffold_root: Optional[Path] = None,
        approve_mobile_execution: bool = False,
        timeout: int = 120,
    ) -> MobileViewportExecutionReport:
        """Main entry point. Returns MobileViewportExecutionReport."""
        report = MobileViewportExecutionReport(
            project_id=project_id,
            device_name=device_name,
            command_mode=command_mode,
            readonly_profile=readonly_profile or "",
            target_url=target_url or "",
        )

        # Gate 1: approval flag
        if not approve_mobile_execution:
            return self._blocked(report, "Missing --approve-mobile-execution flag.")

        # Gate 2: device must be known
        if device_name not in _PLAYWRIGHT_DEVICES:
            return self._blocked(
                report,
                f"Unknown device '{device_name}'. Supported: {', '.join(MOBILE_VIEWPORT_DEVICES)}",
            )

        # Gate 3: command mode
        if command_mode not in MOBILE_VIEWPORT_MODES:
            return self._blocked(
                report,
                f"Unknown command_mode '{command_mode}'. Supported: {', '.join(MOBILE_VIEWPORT_MODES)}",
            )

        # Gate 4: readonly_profile URL path-gate (for ecommerce)
        if readonly_profile in _MOBILE_ECOMMERCE_PROFILES:
            block = self._check_ecommerce_url(target_url or "", readonly_profile)
            if block:
                return self._blocked(report, block)

        # Resolve scaffold
        resolved_scaffold = scaffold_root or (
            self._outputs_root / project_id / "03_framework" / "playwright"
        )

        # Gate 5: ecommerce selector scan
        if readonly_profile in _MOBILE_ECOMMERCE_PROFILES:
            scan_block = self._scan_ecommerce_test_files(resolved_scaffold)
            if scan_block:
                return self._blocked(report, scan_block)

        if command_mode == "list":
            cmd_str = "npx playwright test --list"
        else:
            cmd_str = "npx playwright test tests/smoke --reporter=list"

        # Build + write mobile config
        device_meta = _PLAYWRIGHT_DEVICES[device_name]
        config_path = resolved_scaffold / "mobile.config.cjs"
        config_content = self._build_mobile_config(device_meta, target_url or "")
        try:
            config_path.parent.mkdir(parents=True, exist_ok=True)
            config_path.write_text(config_content, encoding="utf-8")
            report.config_path = str(config_path)
        except OSError as exc:
            return self._blocked(report, f"Could not write mobile config: {exc}")

        cmd_str_with_config = f"{cmd_str} --config=mobile.config.cjs"

        # Run
        exec_cmd = self._run_command(
            command_str=cmd_str_with_config,
            scaffold_root=resolved_scaffold,
            base_url=target_url,
            device_name=device_name,
            timeout=timeout,
        )
        report.commands.append(exec_cmd)

        # Cleanup config
        try:
            config_path.unlink(missing_ok=True)
        except OSError:
            pass

        report.execution_status = "complete" if exec_cmd.status == "pass" else "error"
        report.approved = True
        report.notes.extend([
            f"Device: {device_name}",
            f"Viewport: {device_meta['viewport']['width']}x{device_meta['viewport']['height']}",
            "No credentials used. Mobile viewport only.",
            "safe_to_deliver=False always.",
        ])
        return report

    def render_artifacts(
        self,
        report: MobileViewportExecutionReport,
        project_id: str,
    ) -> Dict[str, Path]:
        """Write execution artifacts to outputs/<project_id>/17_mobile_viewport/."""
        out_dir = self._outputs_root / project_id / "17_mobile_viewport"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: Dict[str, Path] = {}

        p = out_dir / "MOBILE_VIEWPORT_REPORT.json"
        p.write_text(json.dumps(self._report_to_dict(report), indent=2), encoding="utf-8")
        paths["report_json"] = p

        p = out_dir / "MOBILE_VIEWPORT_REPORT.md"
        p.write_text(self._render_md(report), encoding="utf-8")
        paths["report_md"] = p

        return paths

    def get_device_profile(self, device_name: str) -> Optional[MobileViewportProfile]:
        if device_name not in _PLAYWRIGHT_DEVICES:
            return None
        meta = _PLAYWRIGHT_DEVICES[device_name]
        return MobileViewportProfile(
            device_name=device_name,
            viewport_width=meta["viewport"]["width"],
            viewport_height=meta["viewport"]["height"],
            user_agent=meta.get("userAgent", ""),
            is_mobile=meta.get("isMobile", True),
            has_touch=meta.get("hasTouch", True),
            pixel_ratio=float(meta.get("deviceScaleFactor", 2.0)),
            playwright_device_name=meta.get("playwright_name", device_name),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _blocked(
        self, report: MobileViewportExecutionReport, reason: str
    ) -> MobileViewportExecutionReport:
        report.execution_status = "blocked"
        report.blockers.append(reason)
        cmd = MobileViewportExecutionCommand(
            id="blocked",
            command="[blocked]",
            device_name=report.device_name,
            status="blocked",
            executed=False,
            safety_notes=[reason],
        )
        report.commands.append(cmd)
        return report

    def _check_ecommerce_url(self, url: str, profile: str) -> Optional[str]:
        if profile not in _MOBILE_ECOMMERCE_PROFILES:
            return None
        blocked_paths = _MOBILE_ECOMMERCE_PROFILES[profile]["blocked_url_paths"]
        url_lower = url.lower()
        for path in blocked_paths:
            if path in url_lower:
                return (
                    f"Mobile ecommerce readonly profile '{profile}': "
                    f"path '{path}' is always blocked (auth/cart/checkout). URL: {url}"
                )
        return None

    def _scan_ecommerce_test_files(self, scaffold_root: Path) -> Optional[str]:
        tests_dir = scaffold_root / "tests"
        if not tests_dir.exists():
            return None
        extensions = (".spec.ts", ".spec.js", ".test.ts", ".test.js")
        scanned: List[Path] = []
        for ext in extensions:
            scanned.extend(tests_dir.rglob(f"*{ext}"))
        for test_file in scanned:
            try:
                content = Path(test_file).read_text(encoding="utf-8", errors="replace").lower()
            except OSError:
                continue
            for pattern in _ECOMMERCE_DANGEROUS_PATTERNS:
                if pattern.lower() in content:
                    rel = Path(test_file).relative_to(scaffold_root)
                    return (
                        f"Mobile ecommerce readonly safety scan: "
                        f"dangerous pattern '{pattern}' found in '{rel}'. "
                        f"Remove cart/checkout/auth selectors from tests."
                    )
        return None

    def _build_mobile_config(self, device_meta: Dict[str, Any], base_url: str) -> str:
        vp = device_meta["viewport"]
        ua = device_meta.get("userAgent", "")
        scale = device_meta.get("deviceScaleFactor", 2)
        is_mobile = str(device_meta.get("isMobile", True)).lower()
        has_touch = str(device_meta.get("hasTouch", True)).lower()
        safe_base_url = base_url.replace("'", "") if base_url else "http://localhost:3000"
        return (
            "// Mobile viewport config — runtime only, gitignored\n"
            "// @ts-check\n"
            "const { defineConfig, devices } = require('@playwright/test');\n"
            "module.exports = defineConfig({\n"
            f"  use: {{\n"
            f"    baseURL: '{safe_base_url}',\n"
            f"    viewport: {{ width: {vp['width']}, height: {vp['height']} }},\n"
            f"    userAgent: '{ua}',\n"
            f"    deviceScaleFactor: {scale},\n"
            f"    isMobile: {is_mobile},\n"
            f"    hasTouch: {has_touch},\n"
            f"  }},\n"
            "  reporter: [['list']],\n"
            "  testDir: './tests',\n"
            "});\n"
        )

    def _run_command(
        self,
        command_str: str,
        scaffold_root: Path,
        base_url: Optional[str],
        device_name: str,
        timeout: int,
    ) -> MobileViewportExecutionCommand:
        cmd_id = f"mobile_{datetime.now(timezone.utc).strftime('%H%M%S')}"
        env = dict(os.environ)
        # Strip secrets
        for k in list(env.keys()):
            if any(p in k.upper() for p in ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "CREDENTIAL", "AUTH", "COOKIE")):
                del env[k]
        env["BASE_URL"] = base_url or "http://localhost:3000"
        env["TEST_USERNAME"] = ""
        env["TEST_PASSWORD"] = ""

        cmd_parts = command_str.split()
        # On Windows, npx needs .cmd suffix
        if os.name == "nt" and cmd_parts[0] == "npx":
            cmd_parts[0] = "npx.cmd"

        start = time.time()
        try:
            result = subprocess.run(
                cmd_parts,
                cwd=str(scaffold_root),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
            duration = time.time() - start
            status = "pass" if result.returncode == 0 else "fail"
            return MobileViewportExecutionCommand(
                id=cmd_id,
                command=command_str,
                device_name=device_name,
                cwd=str(scaffold_root),
                status=status,
                executed=True,
                stdout_excerpt=result.stdout[:_EXCERPT_LIMIT],
                stderr_excerpt=result.stderr[:_EXCERPT_LIMIT],
                duration_seconds=round(duration, 2),
                safety_notes=["Subprocess with allowlisted command only.", "Secrets stripped."],
            )
        except subprocess.TimeoutExpired:
            return MobileViewportExecutionCommand(
                id=cmd_id, command=command_str, device_name=device_name,
                cwd=str(scaffold_root), status="fail", executed=True,
                stderr_excerpt=f"Timeout after {timeout}s",
                duration_seconds=float(timeout),
            )
        except Exception as exc:
            return MobileViewportExecutionCommand(
                id=cmd_id, command=command_str, device_name=device_name,
                cwd=str(scaffold_root), status="fail", executed=False,
                stderr_excerpt=str(exc),
            )

    def _report_to_dict(self, report: MobileViewportExecutionReport) -> Dict[str, Any]:
        return {
            "project_id": report.project_id,
            "device_name": report.device_name,
            "command_mode": report.command_mode,
            "readonly_profile": report.readonly_profile,
            "target_url": report.target_url,
            "execution_status": report.execution_status,
            "approved": report.approved,
            "blockers": report.blockers,
            "notes": report.notes,
            "credentials_used": report.credentials_used,
            "auth_performed": report.auth_performed,
            "safe_to_deliver": report.safe_to_deliver,
            "approved_for_client_delivery": report.approved_for_client_delivery,
            "human_review_required": report.human_review_required,
            "commands": [c.to_dict() for c in report.commands],
        }

    def _render_md(self, report: MobileViewportExecutionReport) -> str:
        lines = [
            f"# Mobile Viewport Report — {report.device_name}",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Device:** `{report.device_name}`  ",
            f"**Mode:** `{report.command_mode}`  ",
            f"**Status:** `{report.execution_status}`  ",
            f"**Target URL:** `{report.target_url}`  ",
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
            "",
        ]
        if report.blockers:
            lines += ["## Blockers", ""]
            for b in report.blockers:
                lines.append(f"- {b}")
            lines.append("")
        if report.notes:
            lines += ["## Notes", ""]
            for n in report.notes:
                lines.append(f"- {n}")
        return "\n".join(lines)

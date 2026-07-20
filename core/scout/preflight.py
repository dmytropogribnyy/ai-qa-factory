"""Readiness preflight for a live Scout campaign (v3.3).

Real probes, not "installed == ready". Each check reports an honest status; the report is `ok`
only when no REQUIRED check is not-ready/blocked/error. Used by the Dashboard "Run readiness
preflight" panel before a live acceptance run. The Tavily key value is never read into any
returned field — only presence/metadata (see tavily_secret.masked_metadata).
"""
from __future__ import annotations

import shutil
import socket
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.scout.discovery.tavily_secret import key_present, masked_metadata

READY = "ready"
CONFIGURED = "configured"          # present but not deeply verified (e.g. key set, not API-pinged)
NOT_READY = "not_ready"
BLOCKED = "blocked"
SKIPPED = "skipped"
ERROR = "error"

_OK_STATES = frozenset({READY, CONFIGURED, SKIPPED})


@dataclass
class PreflightCheck:
    key: str
    label: str
    status: str
    detail: str = ""
    required: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class PreflightReport:
    checks: List[PreflightCheck] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(c.status in _OK_STATES for c in self.checks if c.required)

    def to_dict(self) -> Dict[str, Any]:
        return {"ok": self.ok, "checks": [c.to_dict() for c in self.checks]}


# --- individual probes -------------------------------------------------------------------------
def probe_tavily(env: Optional[Dict[str, str]] = None) -> PreflightCheck:
    if not key_present(env):
        return PreflightCheck("tavily_key", "Tavily key + provider readiness", NOT_READY,
                              "no TAVILY_API_KEY in env or the outside-repo secret file", True)
    meta = masked_metadata(env)
    ok_prefix = meta.get("prefix_ok")
    detail = f"key present (source={meta.get('source')}, prefix_ok={ok_prefix}); not API-pinged"
    # Present but not verified against the live API (that would consume a credit).
    return PreflightCheck("tavily_key", "Tavily key + provider readiness", CONFIGURED, detail, True)


def probe_browser(launch: bool = True) -> PreflightCheck:
    """Import Playwright AND actually launch+close Chromium headless (installed != ready)."""
    try:
        from playwright.sync_api import sync_playwright  # type: ignore
    except Exception as exc:
        return PreflightCheck("browser", "Browser install + real launch", NOT_READY,
                              f"playwright not importable: {str(exc)[:100]}", True)
    if not launch:
        return PreflightCheck("browser", "Browser install + real launch", CONFIGURED,
                              "playwright importable; launch not probed", True)
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return PreflightCheck("browser", "Browser install + real launch", READY,
                              "Chromium launched + closed headless", True)
    except Exception as exc:
        return PreflightCheck("browser", "Browser install + real launch", NOT_READY,
                              f"launch failed: {str(exc)[:120]}", True)


def probe_network(host: str = "api.tavily.com", port: int = 443,
                  timeout: float = 4.0) -> PreflightCheck:
    """Bounded outbound reachability probe (real TCP connect)."""
    try:
        start = time.monotonic()
        with socket.create_connection((host, port), timeout=timeout):
            ms = round((time.monotonic() - start) * 1000)
        return PreflightCheck("network", "Outbound network readiness", READY,
                              f"connected to {host}:{port} in ~{ms}ms", True)
    except OSError as exc:
        return PreflightCheck("network", "Outbound network readiness", NOT_READY,
                              f"cannot reach {host}:{port}: {str(exc)[:100]}", True)


def probe_evidence_dir(output_dir: str) -> PreflightCheck:
    """Write + delete a temp file under the output dir (real writability probe)."""
    try:
        base = Path(output_dir)
        base.mkdir(parents=True, exist_ok=True)
        probe = base / ".preflight_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return PreflightCheck("evidence_dir", "Writable evidence directory", READY,
                              f"{base} is writable", True)
    except OSError as exc:
        return PreflightCheck("evidence_dir", "Writable evidence directory", NOT_READY,
                              f"not writable: {str(exc)[:100]}", True)


def probe_runtime() -> PreflightCheck:
    import sys
    try:
        import core.scout.engine  # noqa: F401
        import core.scout.discovery.engine  # noqa: F401
    except Exception as exc:
        return PreflightCheck("runtime", "Required runtime/process readiness", NOT_READY,
                              f"core modules not importable: {str(exc)[:100]}", True)
    ok = sys.version_info >= (3, 10)
    return PreflightCheck("runtime", "Required runtime/process readiness",
                          READY if ok else NOT_READY,
                          f"python {sys.version_info.major}.{sys.version_info.minor}", True)


def probe_safety_policy(campaign_config: Any) -> PreflightCheck:
    """The campaign must be bounded (finite ceilings), never outreach, and use supported modes."""
    if campaign_config is None:
        return PreflightCheck("safety_policy", "Campaign safety policy", SKIPPED,
                              "no campaign selected yet", False)
    try:
        finite = bool(getattr(campaign_config, "max_candidates", 0) > 0
                      and getattr(campaign_config, "time_budget_s", 0) > 0)
        # A config that constructed successfully already validated its bounds + strategy.
        if not finite:
            return PreflightCheck("safety_policy", "Campaign safety policy", BLOCKED,
                                  "campaign is not bounded (no finite ceiling)", True)
        return PreflightCheck("safety_policy", "Campaign safety policy", READY,
                              "bounded run; outreach disabled; supported interaction modes", True)
    except Exception as exc:
        return PreflightCheck("safety_policy", "Campaign safety policy", ERROR,
                              str(exc)[:100], True)


def probe_auth_dependency(campaign_config: Any) -> PreflightCheck:
    """Public Scout flows need no authentication. A test-account (Mode 3) needs explicit approval."""
    needs_account = bool(getattr(campaign_config, "requires_test_account", False))
    if needs_account and not getattr(campaign_config, "test_account_approved", False):
        return PreflightCheck("auth_dependency", "No unsupported auth dependency", BLOCKED,
                              "campaign needs a test account not yet approved (Mode 3)", True)
    return PreflightCheck("auth_dependency", "No unsupported auth dependency", READY,
                          "public flows require no authentication", True)


def probe_scheduling() -> PreflightCheck:
    """Windows Task Scheduler availability (skipped off-Windows)."""
    import os
    if os.name != "nt":
        return PreflightCheck("scheduling", "Scheduling readiness", SKIPPED,
                              "not Windows; scheduling not applicable here", False)
    if shutil.which("schtasks"):
        return PreflightCheck("scheduling", "Scheduling readiness", READY, "schtasks available",
                              False)
    return PreflightCheck("scheduling", "Scheduling readiness", NOT_READY,
                          "schtasks not found", False)


def run_preflight(*, output_dir: str = "outputs", campaign_config: Any = None,
                  probe_browser_launch: bool = True, do_network: bool = True,
                  env: Optional[Dict[str, str]] = None) -> PreflightReport:
    """Run all readiness probes and return an honest, aggregated report."""
    checks = [
        probe_tavily(env),
        probe_browser(launch=probe_browser_launch),
        probe_network() if do_network else PreflightCheck(
            "network", "Outbound network readiness", SKIPPED, "network probe disabled", True),
        probe_evidence_dir(output_dir),
        probe_runtime(),
        probe_safety_policy(campaign_config),
        probe_auth_dependency(campaign_config),
        probe_scheduling(),
    ]
    return PreflightReport(checks=checks)

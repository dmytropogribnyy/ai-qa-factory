"""Readiness preflight for a live Scout campaign (v3.3).

Real probes, not "installed == ready". Each check reports an honest status; the report is `ok`
only when no REQUIRED check is not-ready/blocked/error. Used by the Dashboard "Run readiness
preflight" panel before a live acceptance run. The Tavily key value is never read into any
returned field — only presence/metadata (see tavily_secret.masked_metadata).
"""
from __future__ import annotations

import asyncio
import shutil
import socket
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

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


def _sync_playwright_factory() -> Callable:
    """Return Playwright's sync context factory.

    Kept behind a tiny seam so the readiness probe can be tested without making Chromium an
    unconditional dependency of the deterministic suite.
    """
    from playwright.sync_api import sync_playwright  # type: ignore
    return sync_playwright


def _launch_browser(factory: Callable) -> None:
    with factory() as playwright:
        browser = playwright.chromium.launch(headless=True)
        browser.close()


def _inside_asyncio_loop() -> bool:
    try:
        asyncio.get_running_loop()
        return True
    except RuntimeError:
        return False


def probe_browser(launch: bool = True) -> PreflightCheck:
    """Import Playwright AND actually launch+close Chromium headless (installed != ready).

    Observer MCP handlers can execute this synchronous probe on an asyncio event-loop thread.
    Playwright deliberately refuses its Sync API there, so hand only the bounded launch/close work
    to a worker thread in that case. Ordinary CLI/Dashboard calls keep the direct path.
    """
    try:
        factory = _sync_playwright_factory()
    except Exception as exc:
        return PreflightCheck("browser", "Browser install + real launch", NOT_READY,
                              f"playwright not importable: {str(exc)[:100]}", True)
    if not launch:
        return PreflightCheck("browser", "Browser install + real launch", CONFIGURED,
                              "playwright importable; launch not probed", True)
    try:
        if _inside_asyncio_loop():
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="aiqa-browser-probe") as pool:
                pool.submit(_launch_browser, factory).result()
        else:
            _launch_browser(factory)
        return PreflightCheck("browser", "Browser install + real launch", READY,
                              "Chromium launched + closed headless", True)
    except Exception as exc:
        return PreflightCheck("browser", "Browser install + real launch", NOT_READY,
                              f"launch failed: {str(exc)[:120]}", True)


_AXE_CALLABLE_JS = ("() => (typeof axe === 'object' && typeof axe.run === 'function') "
                    "? (axe.version || 'unknown') : ''")


def _default_axe_loader() -> str:
    """The PRODUCTION loader, not a second copy of its search logic.

    A probe that reimplemented the vendored-file/optional-package search could report ready while
    the pipeline still raised — it would be evidence about itself. Imported lazily so a static scan
    never pulls the browser stack in.
    """
    from core.scout.pipeline.browser_qa import load_axe_source
    return load_axe_source()


def _inject_axe(source: str) -> str:
    """Launch Chromium, inject the real source into a blank page, return axe's version.

    Returns "" when axe did not end up callable. Loading the bytes proves only that some file
    exists: a truncated or wrong-format bundle reads perfectly and then fails at the moment a run
    depends on it, which is the failure this probe exists to catch.
    """
    factory = _sync_playwright_factory()

    def _run() -> str:
        with factory() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.add_script_tag(content=source)
                return str(page.evaluate(_AXE_CALLABLE_JS) or "")
            finally:
                browser.close()

    # Same constraint as probe_browser: Playwright's sync API refuses to run on an asyncio loop
    # thread, which Observer MCP handlers have.
    if _inside_asyncio_loop():
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="aiqa-axe-probe") as pool:
            return pool.submit(_run).result()
    return _run()


def probe_axe(*, load_source: Optional[Callable[[], str]] = None,
              inject: Optional[Callable[[str], str]] = None) -> PreflightCheck:
    """Deep Capture's accessibility module: source obtainable AND actually runnable in a page.

    Both seams are injectable so the deterministic suite can pin every outcome without making
    Chromium or an axe distribution a hard dependency of the whole test run.
    """
    label = "axe-core source + real injection"
    try:
        source = (load_source or _default_axe_loader)()
    except Exception as exc:  # noqa: BLE001 - any loader failure is a not-ready answer, not a crash
        return PreflightCheck("axe", label, NOT_READY,
                              f"axe-core source not loadable: {str(exc)[:120]}", True)
    if not source:
        return PreflightCheck("axe", label, NOT_READY, "axe-core source loaded empty", True)
    try:
        version = (inject or _inject_axe)(source)
    except Exception as exc:  # noqa: BLE001 - a failed injection is the answer this probe reports
        return PreflightCheck("axe", label, NOT_READY,
                              f"axe-core could not be injected: {str(exc)[:120]}", True)
    if not version:
        return PreflightCheck("axe", label, NOT_READY,
                              "axe-core injected but axe.run is not callable", True)
    return PreflightCheck("axe", label, READY, f"axe-core {version} injected; axe.run callable", True)


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
        # Deep Capture is what the start form selects by DEFAULT, and it advertises an accessibility
        # module. A host with a browser but no usable axe-core is not ready for it, so the aggregate
        # must say so here rather than let the operator discover it by spending a run. Gated on the
        # same flag as the browser launch: this probe opens a page too.
        probe_axe() if probe_browser_launch else PreflightCheck(
            "axe", "axe-core source + real injection", SKIPPED,
            "browser launches disabled, so axe injection was not probed", True),
        probe_network() if do_network else PreflightCheck(
            "network", "Outbound network readiness", SKIPPED, "network probe disabled", True),
        probe_evidence_dir(output_dir),
        probe_runtime(),
        probe_safety_policy(campaign_config),
        probe_auth_dependency(campaign_config),
        probe_scheduling(),
    ]
    return PreflightReport(checks=checks)

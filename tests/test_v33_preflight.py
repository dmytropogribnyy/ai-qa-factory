"""v3.3 — readiness preflight. Deterministic probes only (browser/network probed structurally).

The key value is never surfaced; probes are honest (present != verified, installed != launched);
the report is ok only when every REQUIRED check is in an acceptable state.
"""
from __future__ import annotations

import asyncio
import threading
from contextlib import contextmanager

import core.scout.preflight as preflight
from core.scout.presets import build_config
from core.scout.preflight import (
    BLOCKED,
    CONFIGURED,
    NOT_READY,
    READY,
    PreflightCheck,
    PreflightReport,
    probe_auth_dependency,
    probe_browser,
    probe_evidence_dir,
    probe_runtime,
    probe_safety_policy,
    probe_tavily,
    run_preflight,
)


def test_tavily_probe_never_leaks_the_key():
    present = probe_tavily(env={"TAVILY_API_KEY": "tvly-secret-value"})
    assert present.status == CONFIGURED
    assert "tvly-secret-value" not in present.detail        # never surfaces the value


def test_tavily_probe_not_ready_when_absent(tmp_path, monkeypatch):
    # Point the outside-repo secret dir at an empty location AND clear the env var so neither
    # source has a key (the real machine has a key file, which is correctly CONFIGURED).
    monkeypatch.setenv("AIQA_SECRETS_DIR", str(tmp_path / "empty-secrets"))
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    assert probe_tavily(env={}).status == NOT_READY


def test_evidence_dir_probe_is_a_real_write(tmp_path):
    c = probe_evidence_dir(str(tmp_path / "out"))
    assert c.status == READY
    assert not (tmp_path / "out" / ".preflight_write_probe").exists()   # cleaned up


def test_runtime_probe_ready():
    assert probe_runtime().status == READY


def test_browser_probe_uses_worker_thread_inside_asyncio_loop(monkeypatch):
    caller_thread = threading.get_ident()
    launch_threads = []
    closed = []

    class Browser:
        def close(self):
            closed.append(True)

    class Chromium:
        def launch(self, *, headless):
            assert headless is True
            launch_threads.append(threading.get_ident())
            return Browser()

    class Playwright:
        chromium = Chromium()

    @contextmanager
    def fake_factory():
        yield Playwright()

    monkeypatch.setattr(preflight, "_sync_playwright_factory", lambda: fake_factory)

    async def call_from_running_loop():
        return probe_browser(launch=True)

    check = asyncio.run(call_from_running_loop())
    assert check.status == READY
    assert closed == [True]
    assert launch_threads and launch_threads[0] != caller_thread


def test_safety_policy_probe_ready_for_bounded_config_and_skipped_when_none():
    cfg = build_config("safe-live-acceptance", "quick", provider_allowlist=["tavily"])
    assert probe_safety_policy(cfg).status == READY
    assert probe_safety_policy(None).status == "skipped"


def test_auth_dependency_ready_for_public_flows():
    cfg = build_config("safe-live-acceptance", "quick", provider_allowlist=["tavily"])
    assert probe_auth_dependency(cfg).status == READY


def test_report_ok_requires_all_required_checks_acceptable():
    good = PreflightReport(checks=[
        PreflightCheck("a", "A", READY, required=True),
        PreflightCheck("b", "B", CONFIGURED, required=True),
        PreflightCheck("c", "C", NOT_READY, required=False),      # optional not-ready is fine
    ])
    bad = PreflightReport(checks=[
        PreflightCheck("a", "A", READY, required=True),
        PreflightCheck("b", "B", BLOCKED, required=True),         # required blocked => not ok
    ])
    assert good.ok is True
    assert bad.ok is False


def test_run_preflight_structure_without_browser_or_network(tmp_path):
    cfg = build_config("safe-live-acceptance", "quick", provider_allowlist=["tavily"])
    report = run_preflight(output_dir=str(tmp_path), campaign_config=cfg,
                           probe_browser_launch=False, do_network=False,
                           env={"TAVILY_API_KEY": "tvly-x"})
    keys = {c.key for c in report.checks}
    assert keys == {"tavily_key", "browser", "network", "evidence_dir", "runtime",
                    "safety_policy", "auth_dependency", "scheduling"}
    # evidence/runtime/safety/tavily are deterministically acceptable here
    by = {c.key: c for c in report.checks}
    assert by["evidence_dir"].status == READY
    assert by["safety_policy"].status == READY
    assert by["network"].status == "skipped"

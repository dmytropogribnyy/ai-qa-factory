"""v3.0.0 Milestone 3 — capability & tool broker (deterministic; no live MCP/network call)."""
from __future__ import annotations

from core.orchestration.tool_broker import (
    DOMAIN_EXTERNAL_SETUP,
    DOMAIN_INTERNAL,
    DOMAIN_LOCAL_FACTORY,
    DOMAIN_SESSION,
    ToolBroker,
)

# Deterministic environment: some local binaries present, some not; Gmail not configured.
_PRESENT = {"git", "python", "ruff"}


def _which(name):
    return f"/usr/bin/{name}" if name in _PRESENT else None


def _gmail_unconfigured():
    return {"client_config_present": False, "token_present": False}


def _broker(gmail=None):
    return ToolBroker(which=_which, gmail_status_fn=gmail or _gmail_unconfigured, clock=lambda: "T0")


def _by_id(statuses):
    return {s.id: s for s in statuses}


def test_availability_domains_are_distinguished():
    s = _by_id(_broker().discover())
    assert s["playwright_internal"].domain == DOMAIN_INTERNAL
    assert s["gh"].domain == DOMAIN_LOCAL_FACTORY
    assert s["github_mcp"].domain == DOMAIN_SESSION
    assert s["sentry_mcp"].domain == DOMAIN_EXTERNAL_SETUP


def test_local_binary_health_check_is_honest():
    s = _by_id(_broker().discover())
    assert s["git"].readiness == "health-checked"          # present on PATH
    assert s["gh"].readiness == "unavailable" and s["gh"].setup_instruction  # not present -> setup shown
    assert s["node"].readiness == "unavailable"


def test_internal_runner_is_fixture_tested_and_no_tool_is_live_accepted():
    snap = _broker().snapshot()
    assert snap["any_live_accepted"] is False
    s = _by_id(snap["tools"] and _broker().discover())
    assert s["playwright_internal"].readiness == "fixture-tested"
    assert s["api_runner_internal"].readiness == "fixture-tested"


def test_mcp_tools_are_only_declared_not_live():
    s = _by_id(_broker().discover())
    for mcp_id in ("github_mcp", "context7", "sentry_mcp", "browserstack_mcp", "atlassian_mcp",
                   "postman_mcp", "chrome_devtools_mcp"):
        assert s[mcp_id].readiness == "declared", mcp_id   # never 'configured'/'authenticated'/'live'


def test_gmail_readiness_reflects_status():
    s = _by_id(_broker().discover())
    assert s["gmail_personal"].readiness == "blocked-by-auth"   # not configured
    ready = _by_id(_broker(gmail=lambda: {"client_config_present": True, "token_present": True}).discover())
    assert ready["gmail_personal"].readiness == "authenticated"


def test_selection_is_task_driven_and_ranks_ready_first():
    browser = _broker().select(capabilities=["browser_automation"])
    ids = [t.id for t in browser]
    assert "playwright_internal" in ids and "chrome_devtools_mcp" in ids
    assert ids[0] == "playwright_internal"                       # internal ready first
    # A task that needs none of a tool's capabilities never selects it.
    assert "sentry_mcp" not in ids

    github = _broker().select(capabilities=["github"])
    gids = [t.id for t in github]
    assert "gh" in gids and "github_mcp" in gids

    api = [t.id for t in _broker().select(capabilities=["api_testing"])]
    assert api[0] == "api_runner_internal"                      # internal runner preferred over Postman MCP


def test_fallbacks_are_declared():
    s = _by_id(_broker().discover())
    assert s["browserstack_mcp"].fallback == "Internal Playwright runtime"
    assert s["sentry_mcp"].fallback == "provided_logs"
    assert s["github_mcp"].fallback == "GitHub CLI"

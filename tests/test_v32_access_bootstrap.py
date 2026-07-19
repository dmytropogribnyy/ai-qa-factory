"""v3.2 Section 8 - Access & Identity Bootstrap: honest readiness, never a secret."""
from __future__ import annotations

from core.orchestration.access_bootstrap import (
    AUTHENTICATED,
    NEEDS_CLIENT,
    RUNTIME_VERIFIED,
    UNAVAILABLE,
    AccessBootstrap,
)


def _boot(present=(), modules=(), env=None, gh_auth=False, claude=None):
    present = set(present)
    modules = set(modules)

    def _which(name):
        return f"/usr/bin/{name}" if name in present else None

    def _run(cmd, timeout=8):
        exe = cmd[0]
        if exe == "gh" and cmd[1:3] == ["auth", "status"]:
            return "Logged in to github.com" if gh_auth else "not logged in"
        if exe == "claude":
            return claude
        return f"{exe} 1.0.0" if exe in present else None

    return AccessBootstrap(which=_which, run=_run,
                           module_available=lambda n: n in modules, env=(env or {}))


def _by_id(items):
    return {i.id: i for i in items}


def test_python_is_runtime_verified_and_no_secret_shown():
    boot = _boot()
    snap = boot.snapshot()
    assert snap["any_secret_shown"] is False
    for i in snap["integrations"]:
        # No env-var VALUE is ever present; only the NAME may appear in secret_ref.
        assert "ghp_" not in str(i) and "token=" not in str(i).lower()
    assert _by_id(boot.inspect())["python"].readiness == RUNTIME_VERIFIED


def test_missing_tools_are_unavailable_and_have_setup_actions():
    items = _by_id(_boot(present=(), modules=()).inspect())
    assert items["node"].readiness == UNAVAILABLE and items["node"].setup_action
    assert items["docker"].readiness == UNAVAILABLE
    assert items["playwright_python"].setup_action


def test_github_authenticated_only_when_logged_in():
    logged = _by_id(_boot(present=("gh", "git"), gh_auth=True).inspect())
    assert logged["github"].readiness == AUTHENTICATED
    assert logged["github"].secret_ref == "GH_TOKEN"      # name only, never a value
    not_logged = _by_id(_boot(present=("gh",), gh_auth=False).inspect())
    assert not_logged["github"].readiness != AUTHENTICATED


def test_client_owned_integrations_are_needs_client():
    items = _by_id(_boot().inspect())
    for cid in ("client_test_account", "client_database", "client_oauth_tenant"):
        assert items[cid].readiness == NEEDS_CLIENT and items[cid].owner == "client"


def test_claude_and_mcp_states():
    items = _by_id(_boot(present=("claude",), claude="2.1.198 (Claude Code)").inspect())
    assert items["claude_code"].readiness == "Installed" and "2.1.198" in items["claude_code"].check_result
    assert items["github_mcp"].readiness == "Declared"    # a connector is never auto-authenticated

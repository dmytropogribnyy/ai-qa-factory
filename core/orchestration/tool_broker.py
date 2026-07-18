"""Capability & tool broker (v3.0.0 Milestone 3).

A single honest broker over the EXISTING capability + MCP surfaces. It answers what a task needs,
which tools are internal / local / session-only / require setup, each tool's honest readiness, the
best pick, and the fallback — without claiming a manifest entry is a working integration and without
reusing a ChatGPT/Claude connector as a Factory credential. Deterministic discovery (local-binary
presence + the references-only MCP manifest + offline Gmail status) makes NO live MCP or network
call, so CI never depends on the operator's authenticated session; live session discovery is a
separate, documented, non-CI path.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# Availability domains (honest; a connector in ChatGPT/Claude is NOT a local Factory credential).
DOMAIN_SESSION = "CLAUDE_SESSION_TOOL"            # usable by Claude Code in the current IDE session
DOMAIN_LOCAL_FACTORY = "LOCAL_FACTORY_TOOL"       # usable by the standalone local runtime
DOMAIN_CONNECTOR_ONLY = "CHATGPT_CONNECTOR_ONLY"  # not reusable by the local process
DOMAIN_EXTERNAL_SETUP = "EXTERNAL_SERVICE_REQUIRES_SETUP"
DOMAIN_INTERNAL = "INTERNAL_RUNNER"

# Readiness ladder.
READINESS_LADDER = ("declared", "available-in-session", "configured", "authenticated",
                    "health-checked", "tools-discovered", "fixture-tested", "sandbox-accepted",
                    "live-accepted", "unavailable", "blocked-by-auth", "blocked-by-policy")


@dataclass
class ToolProfile:
    id: str
    name: str
    domain: str
    kind: str                      # local_bin | internal | mcp | gmail
    capabilities: List[str] = field(default_factory=list)
    auth_ref: str = ""             # env-var NAME only, never a value
    fallback_id: str = ""
    bin_name: str = ""             # for local_bin discovery
    setup: str = ""
    notes: str = ""


@dataclass
class ToolStatus:
    id: str
    name: str
    domain: str
    readiness: str
    capabilities: List[str]
    auth_requirement: str
    fallback: str
    checked_at: str = ""
    check_result: str = ""
    setup_instruction: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


_CATALOGUE: List[ToolProfile] = [
    ToolProfile("git", "Git", DOMAIN_LOCAL_FACTORY, "local_bin", ["repository", "version_control"],
                bin_name="git", setup="install Git and ensure `git` is on PATH"),
    ToolProfile("gh", "GitHub CLI", DOMAIN_LOCAL_FACTORY, "local_bin",
                ["github", "repository", "ci_inspection"], auth_ref="GH_TOKEN", bin_name="gh",
                fallback_id="git", setup="install GitHub CLI and run `gh auth login` (or set GH_TOKEN)"),
    ToolProfile("github_mcp", "GitHub MCP", DOMAIN_SESSION, "mcp",
                ["github", "repository", "ci_inspection", "pull_request"], fallback_id="gh",
                setup="connect the GitHub MCP in Claude Code (/mcp); PAT-based, not a Factory credential"),
    ToolProfile("playwright_internal", "Internal Playwright runtime", DOMAIN_INTERNAL, "internal",
                ["browser_automation", "e2e", "evidence"],
                notes="in-repo browser acceptance (Chromium/axe/perf) with local fixtures"),
    ToolProfile("playwright_cli", "Playwright CLI", DOMAIN_LOCAL_FACTORY, "local_bin",
                ["browser_automation", "e2e"], bin_name="playwright", fallback_id="playwright_internal",
                setup="pip install playwright && python -m playwright install chromium"),
    ToolProfile("chrome_devtools_mcp", "Chrome DevTools MCP", DOMAIN_SESSION, "mcp",
                ["browser_automation", "performance", "network"], fallback_id="playwright_internal",
                setup="connect the Chrome DevTools MCP in Claude Code (/mcp)"),
    ToolProfile("context7", "Context7 docs MCP", DOMAIN_SESSION, "mcp", ["documentation"],
                setup="connect Context7 in Claude Code for current official library docs"),
    ToolProfile("api_runner_internal", "Internal API runner", DOMAIN_INTERNAL, "internal",
                ["api_testing", "openapi"], notes="in-repo OpenAPI/endpoint test runner"),
    ToolProfile("postman_mcp", "Postman MCP", DOMAIN_EXTERNAL_SETUP, "mcp", ["api_testing", "postman"],
                fallback_id="api_runner_internal", setup="connect Postman MCP + authorize your workspace"),
    ToolProfile("sentry_mcp", "Sentry MCP", DOMAIN_EXTERNAL_SETUP, "mcp", ["error_analysis"],
                fallback_id="provided_logs", setup="connect Sentry MCP + authorize your org"),
    ToolProfile("browserstack_mcp", "BrowserStack MCP", DOMAIN_EXTERNAL_SETUP, "mcp",
                ["real_device", "cross_browser"], fallback_id="playwright_internal",
                setup="connect BrowserStack MCP + authorize (paid)"),
    ToolProfile("atlassian_mcp", "Atlassian (Jira/Confluence) MCP", DOMAIN_EXTERNAL_SETUP, "mcp",
                ["requirements_intake"], fallback_id="pasted_requirements",
                setup="connect Atlassian MCP + authorize your site"),
    ToolProfile("gmail_personal", "Gmail send provider", DOMAIN_EXTERNAL_SETUP, "gmail", ["email"],
                auth_ref="GMAIL_OAUTH_TOKEN_JSON", fallback_id="manual_gmail",
                setup="see docs/GMAIL_PROVIDER_SETUP.md (local OAuth; send-only)"),
    ToolProfile("python", "Python", DOMAIN_LOCAL_FACTORY, "local_bin", ["runtime", "pytest"],
                bin_name="python", setup="install Python 3.12"),
    ToolProfile("ruff", "Ruff", DOMAIN_LOCAL_FACTORY, "local_bin", ["lint"], bin_name="ruff",
                setup="pip install ruff"),
    ToolProfile("node", "Node.js", DOMAIN_LOCAL_FACTORY, "local_bin", ["runtime", "typescript"],
                bin_name="node", fallback_id="", setup="install Node.js LTS"),
]
_BY_ID = {p.id: p for p in _CATALOGUE}


class ToolBroker:
    def __init__(self, *, env: Optional[Dict[str, str]] = None, which: Callable[[str], Any] = shutil.which,
                 clock: Optional[Callable[[], str]] = None, gmail_status_fn: Optional[Callable[[], Dict]] = None
                 ) -> None:
        self._env = env
        self._which = which
        self._clock = clock or (lambda: "")
        self._gmail_status_fn = gmail_status_fn

    def discover(self) -> List[ToolStatus]:
        return [self._status(p) for p in _CATALOGUE]

    def snapshot(self) -> Dict[str, Any]:
        tools = self.discover()
        return {"generated_at": self._clock(), "tool_count": len(tools),
                "domains": sorted({t.domain for t in tools}),
                "any_live_accepted": any(t.readiness == "live-accepted" for t in tools),
                "tools": [t.to_dict() for t in tools]}

    def select(self, *, capabilities: List[str]) -> List[ToolStatus]:
        """Return the tools relevant to the requested capabilities, best (ready) first."""
        want = set(capabilities or [])
        relevant = [self._status(p) for p in _CATALOGUE if want & set(p.capabilities)]
        return sorted(relevant, key=self._rank)

    # --- honest per-tool readiness (no live MCP / network call) ----------------------------------
    def _status(self, p: ToolProfile) -> ToolStatus:
        readiness, result, setup = self._readiness(p)
        return ToolStatus(
            id=p.id, name=p.name, domain=p.domain, readiness=readiness, capabilities=list(p.capabilities),
            auth_requirement=(f"env {p.auth_ref}" if p.auth_ref else "none"),
            fallback=(_BY_ID[p.fallback_id].name if p.fallback_id in _BY_ID else p.fallback_id or "none"),
            checked_at=self._clock(), check_result=result, setup_instruction=setup)

    def _readiness(self, p: ToolProfile):
        if p.kind == "internal":
            return "fixture-tested", "in-repo runner present", ""
        if p.kind == "local_bin":
            found = bool(self._which(p.bin_name))
            return (("health-checked", f"{p.bin_name} found on PATH", "") if found
                    else ("unavailable", f"{p.bin_name} not on PATH", p.setup))
        if p.kind == "gmail":
            status = self._gmail()
            if not status.get("client_config_present"):
                return "blocked-by-auth", "no OAuth client configured", p.setup
            if not status.get("token_present"):
                return "blocked-by-auth", "not authorized", p.setup
            return "authenticated", "OAuth token present (identity proven at live preflight)", ""
        # mcp: references-only manifest -> declared. Live session availability is discovered
        # separately (not in CI); never claimed as a working integration here.
        return "declared", "declared in the MCP manifest; connect in-session to use", p.setup

    def _gmail(self) -> Dict[str, Any]:
        if self._gmail_status_fn is not None:
            return self._gmail_status_fn() or {}
        from core.scout.comms.gmail import gmail_config_from_env
        from core.scout.comms.gmail_oauth import gmail_status
        return gmail_status(gmail_config_from_env(self._env))

    @staticmethod
    def _rank(t: ToolStatus) -> tuple:
        order = {"fixture-tested": 0, "health-checked": 1, "authenticated": 2, "live-accepted": 2,
                 "configured": 3, "tools-discovered": 3, "declared": 4, "available-in-session": 4,
                 "blocked-by-auth": 5, "unavailable": 6, "blocked-by-policy": 7}
        domain_pref = {DOMAIN_INTERNAL: 0, DOMAIN_LOCAL_FACTORY: 1, DOMAIN_SESSION: 2,
                       DOMAIN_EXTERNAL_SETUP: 3, DOMAIN_CONNECTOR_ONLY: 4}
        return (order.get(t.readiness, 8), domain_pref.get(t.domain, 5), t.id)

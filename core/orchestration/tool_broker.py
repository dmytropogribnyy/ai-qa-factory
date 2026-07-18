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

import importlib.util
import shutil
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.orchestration.internal_bindings import binding_for

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

# Conceptual readiness levels shown in the operator UI (v3.1 M0.3). These never overstate: a binding
# existing is "Binding Available" (not runtime health), a runtime/executable checked is "Runtime
# Available", a genuine fixture run is "Fixture Verified", and "Live Verified" stays false unless a
# real live acceptance actually occurred.
UI_READINESS_LEVELS = ("Declared", "Binding Available", "Runtime Available", "Fixture Verified",
                       "Live Verified", "Blocked", "Unavailable")


def ui_readiness_level(kind: str, readiness: str) -> str:
    if readiness == "unavailable":
        return "Unavailable"
    if readiness in ("blocked-by-auth", "blocked-by-policy"):
        return "Blocked"
    if readiness == "live-accepted":
        return "Live Verified"
    if readiness in ("fixture-tested", "sandbox-accepted"):
        return "Fixture Verified"
    if readiness == "health-checked":
        # A local binary on PATH is a real runtime; an internal binding present is not yet runtime.
        return "Runtime Available" if kind == "local_bin" else "Binding Available"
    if readiness == "authenticated":
        return "Runtime Available"
    if readiness in ("configured", "tools-discovered"):
        return "Binding Available"
    return "Declared"   # declared / available-in-session / anything not proven


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
    ui_level: str = ""          # v3.1 M0.3: conceptual UI readiness level (never overstated)

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
                setup="pip install playwright axe-core-python && python -m playwright install chromium",
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


def _default_module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


class ToolBroker:
    def __init__(self, *, env: Optional[Dict[str, str]] = None, which: Callable[[str], Any] = shutil.which,
                 clock: Optional[Callable[[], str]] = None, gmail_status_fn: Optional[Callable[[], Dict]] = None,
                 module_available: Optional[Callable[[str], bool]] = None) -> None:
        self._env = env
        self._which = which
        self._clock = clock or (lambda: "")
        self._gmail_status_fn = gmail_status_fn
        self._module_available = module_available or _default_module_available

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
            checked_at=self._clock(), check_result=result, setup_instruction=setup,
            ui_level=ui_readiness_level(p.kind, readiness))

    def _readiness(self, p: ToolProfile):
        if p.kind == "internal":
            # Catalogue presence alone is only 'declared'. A tool exceeds 'declared' ONLY when its
            # PRODUCTION module imports, the expected callable adapter exists and is callable, and a
            # bounded health check passes (see internal_bindings). A tests/ file is never a binding.
            binding = binding_for(p.id)
            if binding is None:
                return ("declared", "internal runner declared; no production binding registered",
                        p.setup)
            res = binding.evaluate(module_available=self._module_available)
            if res.ok:
                return res.readiness, res.detail, ""
            return "declared", res.detail, res.setup or p.setup
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

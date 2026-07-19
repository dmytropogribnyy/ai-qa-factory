"""Access & Identity Bootstrap (v3.2 Section 8).

Inspects ACTUAL local readiness for the runtimes/integrations autonomous execution needs, WITHOUT
printing or persisting any secret. Every integration gets an honest readiness state, its purpose,
the required scope, the owner (operator vs client), a bounded verification result, and a precise
Setup/Verify action. Secrets are referenced only by environment-variable NAME, never by value.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional

# Extended readiness states (Section 8).
DECLARED = "Declared"
INSTALLED = "Installed"
CONNECTED = "Connected"
AUTHENTICATED = "Authenticated"
RUNTIME_VERIFIED = "Runtime Verified"
FIXTURE_VERIFIED = "Fixture Verified"
LIVE_VERIFIED = "Live Verified"
NEEDS_OPERATOR = "Needs Operator"
NEEDS_CLIENT = "Needs Client"
BLOCKED = "Blocked"
UNAVAILABLE = "Unavailable"


@dataclass
class Integration:
    id: str
    name: str
    purpose: str
    readiness: str
    required_scope: str
    owner: str                    # operator | client | local
    check_result: str
    setup_action: str
    secret_ref: str = ""          # env-var NAME only, never a value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _default_module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def _run(cmd: List[str], timeout: int = 8) -> Optional[str]:
    """Run a bounded version/status command; return trimmed stdout+stderr or None. Never returns a
    secret (callers only pass ``--version`` / status commands that do not echo secrets)."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)  # noqa: S603
        out = ((p.stdout or "") + (p.stderr or "")).strip()
        return out if p.returncode == 0 else (out or None)
    except (OSError, subprocess.SubprocessError):
        return None


class AccessBootstrap:
    def __init__(self, *, which: Callable[[str], Any] = shutil.which,
                 run: Callable[[List[str], int], Optional[str]] = None,
                 module_available: Optional[Callable[[str], bool]] = None,
                 env: Optional[Dict[str, str]] = None) -> None:
        self._which = which
        self._run = run or (lambda cmd, timeout=8: _run(cmd, timeout))
        self._mod = module_available or _default_module_available
        self._env = env if env is not None else dict(os.environ)

    def _bin(self, name: str) -> bool:
        return bool(self._which(name))

    def _probe_versions(self) -> Dict[str, Optional[str]]:
        """Run the (bounded) version/status probes CONCURRENTLY so a request never blocks on the sum
        of several subprocess calls."""
        import concurrent.futures
        # Bounded to 3s each and run CONCURRENTLY, so the cold-cache first hit stays well under a
        # typical 5s request timeout even on a slow runner (total ~= the slowest single probe).
        jobs = {
            "node": (["node", "--version"], 3),
            "claude": (["claude", "--version"], 3),
            "docker": (["docker", "--version"], 3),
            "gh": (["gh", "auth", "status"], 3),
        }
        results: Dict[str, Optional[str]] = {k: None for k in jobs}

        def _one(name_cmd):
            name, (cmd, to) = name_cmd
            if not self._bin(cmd[0]):
                return name, None
            return name, self._run(cmd, to)

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            for name, val in ex.map(_one, jobs.items()):
                results[name] = val
        return results

    def inspect(self) -> List[Integration]:
        out: List[Integration] = []
        probes = self._probe_versions()

        # --- local runtimes ---
        out.append(Integration(
            "python", "Python runtime", "run tests, static analysis, and the local pipeline",
            RUNTIME_VERIFIED, "local", "local", "python is executing this process", ""))

        node_v = probes["node"]
        out.append(Integration(
            "node", "Node.js", "run the generated TypeScript Playwright framework",
            INSTALLED if node_v else UNAVAILABLE, "local", "local",
            f"node {node_v}" if node_v else "node not on PATH",
            "" if node_v else "install Node.js LTS"))

        claude_v = probes["claude"]
        out.append(Integration(
            "claude_code", "Claude Code CLI", "autonomous bounded execution worker",
            INSTALLED if claude_v else NEEDS_OPERATOR, "local", "operator",
            (f"detected: {claude_v}" if claude_v else "claude CLI not detected"),
            ("verify auth + a tiny bounded headless run (flags verified via `claude --help`, "
             "consistent with the worker): "
             "`claude -p \"ok\" --output-format json --max-budget-usd 0.05`"
             if claude_v else "install Claude Code and authenticate")))

        docker_v = probes["docker"]
        out.append(Integration(
            "docker", "Docker", "reproducible test environments + containerized DB smoke",
            INSTALLED if docker_v else UNAVAILABLE, "local", "local",
            (docker_v or "docker not on PATH"),
            "" if docker_v else "install Docker Desktop / engine"))

        # --- browser + accessibility ---
        pw = self._mod("playwright")
        out.append(Integration(
            "playwright_python", "Playwright (Python)", "real Chromium acceptance + audits",
            INSTALLED if pw else NEEDS_OPERATOR, "local", "operator",
            "importable" if pw else "not installed",
            "" if pw else "pip install playwright && python -m playwright install chromium"))
        axe = self._mod("axe_core_python")
        out.append(Integration(
            "axe", "axe-core (Python)", "accessibility acceptance",
            INSTALLED if axe else NEEDS_OPERATOR, "local", "operator",
            "importable" if axe else "not installed",
            "" if axe else "pip install axe-core-python"))
        rt = self._env.get("PLAYWRIGHT_TEST_RUNTIME", "")
        out.append(Integration(
            "playwright_npm", "@playwright/test runtime", "execute the generated TS framework",
            INSTALLED if rt else NEEDS_OPERATOR, "local", "operator",
            (f"runtime dir set: {os.path.basename(rt)}" if rt else "not provisioned"),
            "" if rt else "provision an npm @playwright/test runtime (CI does this in browser job)"))

        # --- version control / CI ---
        out.append(Integration(
            "git", "Git", "repository operations", RUNTIME_VERIFIED if self._bin("git") else UNAVAILABLE,
            "local", "local", "git on PATH" if self._bin("git") else "not on PATH",
            "" if self._bin("git") else "install Git"))
        gh_auth = probes["gh"]
        gh_ready = bool(gh_auth) and "Logged in" in (gh_auth or "")
        out.append(Integration(
            "github", "GitHub (gh CLI)", "repo/PR/Actions access + hosted CI",
            AUTHENTICATED if gh_ready else (INSTALLED if self._bin("gh") else UNAVAILABLE),
            "repo, workflow", "operator",
            ("authenticated" if gh_ready else ("gh present, not authenticated"
                                               if self._bin("gh") else "gh not on PATH")),
            "" if gh_ready else "run `gh auth login` (never commit a PAT)",
            secret_ref="GH_TOKEN"))

        # --- session/connector integrations (never auto-authorized) ---
        for cid, name, purpose in (
                ("github_mcp", "GitHub MCP", "repo/PR/CI via Claude session"),
                ("chrome_devtools_mcp", "Chrome DevTools MCP", "browser/perf via Claude session"),
                ("context7_mcp", "Context7 MCP", "current official library docs"),
                ("lovable_mcp", "Lovable MCP", "optional one-time visual critique")):
            out.append(Integration(
                cid, name, purpose, DECLARED, "session", "operator",
                "declared; connect in Claude Code (/mcp) to use",
                "connect the MCP in Claude Code (/mcp) if a task needs it"))

        # --- Gmail test identity (read-only readiness; never sends) ---
        gmail = self._gmail_status()
        if not gmail.get("client_config_present"):
            g_ready, g_note = NEEDS_OPERATOR, "no OAuth client configured"
        elif not gmail.get("token_present"):
            g_ready, g_note = NEEDS_OPERATOR, "not authorized"
        else:
            g_ready, g_note = AUTHENTICATED, "OAuth token present (read-only verification only)"
        out.append(Integration(
            "gmail_test", "Gmail test inbox (read-only)",
            "authorized read-only test identity for inbox checks (never sends)",
            g_ready, "gmail.readonly (test identity)", "operator", g_note,
            "" if g_ready == AUTHENTICATED else
            ("set env GMAIL_OAUTH_CLIENT_JSON (OAuth client) + GMAIL_OAUTH_TOKEN_JSON (authorized "
             "token) — names only, never values; see docs/GMAIL_PROVIDER_SETUP.md (read-only test "
             "inbox)"),
            secret_ref="GMAIL_OAUTH_CLIENT_JSON, GMAIL_OAUTH_TOKEN_JSON"))

        # --- Upwork / direct client intake is ALWAYS manual (item 34) ---
        out.append(Integration(
            "upwork_intake", "Upwork / direct client intake", "manual job intake (paste text or file)",
            RUNTIME_VERIFIED, "manual", "operator",
            "manual only — no scraping, no unofficial API, no automated browser form submission",
            "paste the job text into `analyze-job` (or the dashboard intake); intake is always manual"))

        # --- client-provided access (never local; typed access ids the Tool-Gap report resolves) ---
        for cid, name, purpose, scope, action in (
                ("client_test_account", "Client test/staging account",
                 "authorized client QA execution (app/URL/endpoint)", "client-defined",
                 "client provides a dedicated test/staging account + authorized target"),
                ("client_database", "Client database (read-only)", "safe read-only DB validation",
                 "read-only connection",
                 "client provides a read-only DB connection (or a Docker DB)"),
                ("client_oauth_tenant", "Client OAuth test tenant", "authorized auth-flow testing",
                 "test tenant",
                 "client provides an OAuth test tenant / bounded pre-authorized session"),
                ("client_repository", "Client repository / test suite",
                 "run against the client's real code (framework build, migration, stabilization, BDD)",
                 "repo read access",
                 "client shares the repository / existing test suite to work against real code"),
                ("client_ci_access", "Client CI provider access",
                 "run non-GitHub pipelines (Azure DevOps / GitLab CI / Jenkins)", "CI provider access",
                 "client grants access to the target CI provider to genuinely run the pipeline"),
                ("client_workflow_platform", "Client n8n/Make workspace",
                 "build + sandbox-validate a workflow", "workspace + credentials",
                 "client provides authorized n8n/Make access + credentials"),
                ("client_cloud_scope", "Client AWS scope + credentials",
                 "bounded AWS QA diagnostics", "explicit bounded scope",
                 "client provides AWS credentials + an explicit bounded scope"),
                ("client_control_framework", "Client compliance control framework",
                 "compliance/legal-tech evidence mapping", "control framework + sources",
                 "client supplies the control framework; a qualified reviewer signs off")):
            out.append(Integration(cid, name, purpose, NEEDS_CLIENT, scope, "client",
                                   "not provided", action))
        return out

    def _gmail_status(self) -> Dict[str, Any]:
        try:
            from core.scout.comms.gmail import gmail_config_from_env
            from core.scout.comms.gmail_oauth import gmail_status
            return gmail_status(gmail_config_from_env(self._env)) or {}
        except Exception:
            return {}

    def snapshot(self) -> Dict[str, Any]:
        items = self.inspect()
        return {"schema": "access-bootstrap/v1", "count": len(items),
                "any_secret_shown": False, "integrations": [i.to_dict() for i in items]}

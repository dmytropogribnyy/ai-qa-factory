"""v3.2 P0-E - execution trust + work-isolation preflight for client repositories.

Path confinement stops the worker/validation from *writing* outside the workspace, but it does NOT
sandbox code that npm/pytest *execute* — that code could read the operator's credentials, home
directory, or the network. v3.2 therefore does **not** claim to safely execute arbitrary untrusted
repositories. Instead (a tested, honest bounded gate — never simulated isolation):

- execution of client code is gated to TRUSTED / operator-approved workspaces (an explicit approval
  marker, or a configured trusted root); untrusted execution is REFUSED with an exact action;
- a preflight fails closed unless the work/evidence directory is PRIVATE (git-ignored, or outside any
  tracked repo), so real client artifacts never enter the public source repo or hosted CI;
- the subprocess environment for executing (possibly untrusted) code is stripped of credential-like
  variables where feasible, so executed code cannot read operator secrets from the environment.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional

TRUST_MARKER = "EXECUTION_APPROVED.json"
TRUSTED_ROOTS_ENV = "AIQA_TRUSTED_ROOTS"
_CRED_RE = re.compile(r"(KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|_PAT\b|SESSION|COOKIE|AUTH)", re.I)
# Non-secret worker/runtime config that must survive the strip.
_KEEP_EXACT = frozenset({"AIQA_CLAUDE_BIN", "AIQA_CLAUDE_MODEL", "AIQA_CLAUDE_BUDGET",
                         "PLAYWRIGHT_TEST_RUNTIME"})


@dataclass
class TrustDecision:
    trusted: bool
    reason: str
    action: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"trusted": str(self.trusted), "reason": self.reason, "action": self.action}


def assess_execution_trust(workspace: str, *, env: Optional[Dict[str, str]] = None) -> TrustDecision:
    """Trusted only when the operator has approved this workspace for execution (the TRUST_MARKER is
    written by ``WorkExecutionService.approve``), or when it resolves under a configured trusted root.
    Otherwise untrusted, with an exact operator action. Never executes untrusted code by default."""
    env = env if env is not None else dict(os.environ)
    ws = Path(workspace)
    if (ws / TRUST_MARKER).is_file():
        return TrustDecision(True, "operator-approved for execution (marker present)")
    roots = [r for r in env.get(TRUSTED_ROOTS_ENV, "").split(os.pathsep) if r.strip()]
    try:
        wsr = ws.resolve()
        for r in roots:
            rr = Path(r).resolve()
            if wsr == rr or rr in wsr.parents:
                return TrustDecision(True, f"under a configured {TRUSTED_ROOTS_ENV} root")
    except OSError:
        pass
    return TrustDecision(
        False, "workspace is not operator-approved for execution",
        f"approve this project for execution (writes {TRUST_MARKER}) or add a trusted root to "
        f"{TRUSTED_ROOTS_ENV}; untrusted client code is not executed outside isolation")


@dataclass
class PreflightResult:
    ok: bool
    reason: str
    action: str = ""

    def to_dict(self) -> Dict[str, str]:
        return {"ok": str(self.ok), "reason": self.reason, "action": self.action}


def preflight_work_isolation(workspace: str) -> PreflightResult:
    """Fail CLOSED unless the work directory is PRIVATE: outside any tracked git repo, or git-ignored.
    Ensures real client artifacts/evidence never land in the public source repo or hosted CI."""
    ws = Path(workspace)
    try:
        ws.mkdir(parents=True, exist_ok=True)
        inside = subprocess.run(["git", "-C", str(ws), "rev-parse", "--is-inside-work-tree"],
                                capture_output=True, text=True, timeout=10, check=False)
        if inside.returncode != 0 or "true" not in (inside.stdout or "").lower():
            return PreflightResult(True, "outside any tracked git repository (private)")
        ignored = subprocess.run(["git", "-C", str(ws), "check-ignore", "-q", "."],
                                 capture_output=True, text=True, timeout=10, check=False)
        if ignored.returncode == 0:
            return PreflightResult(True, "inside a repo but git-ignored (private)")
        return PreflightResult(
            False, "work directory is tracked by a public repository",
            "use a private, git-ignored work directory (e.g. OUTPUT_DIR under outputs/) so client "
            "artifacts and evidence never enter the public repo or hosted CI")
    except (OSError, subprocess.SubprocessError) as exc:
        return PreflightResult(False, f"could not verify isolation: {type(exc).__name__}",
                               "ensure git is available and the work directory is private")


def stripped_subprocess_env(base_env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """A copy of the environment with credential-like variables removed, for executing (possibly
    untrusted) client code. Keeps only what a headless tool needs (PATH, HOME, runtime config)."""
    base = dict(base_env if base_env is not None else os.environ)
    return {k: v for k, v in base.items() if k in _KEEP_EXACT or not _CRED_RE.search(k)}

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


def _read_json(path: Path) -> Dict:
    import json
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def assess_execution_trust(workspace: str, *, env: Optional[Dict[str, str]] = None) -> TrustDecision:
    """Trusted only when the operator has genuinely approved THIS project for execution. A bare file
    named ``EXECUTION_APPROVED.json`` is NOT enough (a client checkout could pre-create it): the marker
    must be structured (``approved_for_execution=true`` + a non-empty reviewer + the project id) AND
    consistent with the canonical control-plane records — ``APPROVAL.json`` (same reviewer, approved)
    and a genuine approval transition to ``READY_TO_EXECUTE`` by that reviewer in the work-run state
    history. Alternatively an operator-configured ``AIQA_TRUSTED_ROOTS`` root (outside client content)
    grants trust. Otherwise untrusted, with an exact action. Never trusts a self-asserted client file."""
    env = env if env is not None else dict(os.environ)
    ws = Path(workspace)

    # Operator control-plane override (outside editable client content).
    roots = [r for r in env.get(TRUSTED_ROOTS_ENV, "").split(os.pathsep) if r.strip()]
    try:
        wsr = ws.resolve()
        for r in roots:
            rr = Path(r).resolve()
            if wsr == rr or rr in wsr.parents:
                return TrustDecision(True, f"under a configured {TRUSTED_ROOTS_ENV} root")
    except OSError:
        pass

    _deny = TrustDecision(
        False, "workspace is not operator-approved for execution",
        f"approve this project (writes a validated {TRUST_MARKER} bound to APPROVAL.json + the "
        f"work-run state) or add a trusted root to {TRUSTED_ROOTS_ENV}; a self-asserted marker file "
        "is not trusted and untrusted client code is not executed outside isolation")

    marker = _read_json(ws / TRUST_MARKER)
    if marker.get("approved_for_execution") is not True:
        return _deny                                          # missing / empty {} / malformed / false
    reviewer = str(marker.get("reviewer") or "").strip()
    if not reviewer:
        return _deny
    # Project/workspace binding: ws is <output>/<project_id>/40_ark_work.
    if str(marker.get("project_id") or "") != ws.parent.name:
        return _deny
    # Consistency with the canonical approval record (same reviewer, genuinely approved).
    approval = _read_json(ws / "APPROVAL.json")
    if approval.get("approved") is not True or str(approval.get("reviewer") or "") != reviewer:
        return _deny
    # Consistency with the canonical state machine: a real approval transition by this reviewer.
    state = _read_json(ws / "WORK_RUN_STATE.json")
    history = state.get("history", []) if isinstance(state.get("history"), list) else []
    if not any(isinstance(h, dict) and h.get("to_state") == "READY_TO_EXECUTE"
               and reviewer in str(h.get("actor", "")) for h in history):
        return _deny
    return TrustDecision(True, "operator-approved (marker consistent with APPROVAL.json + state)")


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

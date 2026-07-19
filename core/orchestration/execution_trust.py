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

TRUST_MARKER = "EXECUTION_APPROVED.json"          # workspace copy = EVIDENCE only, never authority
TRUSTED_ROOTS_ENV = "AIQA_TRUSTED_ROOTS"
CONTROL_DIR_ENV = "AIQA_CONTROL_DIR"              # operator-only control store (outside client content)
_CONTROL_SUBDIR = ".aiqa_control"                 # default: <OUTPUT_DIR>/.aiqa_control (sibling of projects)
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


def _output_root(ws: Path) -> Path:
    # ws is <output>/<project_id>/40_ark_work -> output root is two levels up.
    return ws.parent.parent


def control_dir(workspace: str, *, env: Optional[Dict[str, str]] = None) -> Path:
    """The operator-only control store, OUTSIDE the editable client work directory. Configurable via
    AIQA_CONTROL_DIR; defaults to <OUTPUT_DIR>/.aiqa_control (a sibling of every project, never inside
    a project's 40_ark_work). This is where the authoritative execution grant lives."""
    env = env if env is not None else dict(os.environ)
    override = (env.get(CONTROL_DIR_ENV) or "").strip()
    return Path(override) if override else (_output_root(Path(workspace)) / _CONTROL_SUBDIR)


def _grant_path(workspace: str, *, env: Optional[Dict[str, str]] = None) -> Path:
    pid = Path(workspace).parent.name
    return control_dir(workspace, env=env) / f"{pid}.grant.json"


def grant_execution_authority(workspace: str, *, reviewer: str, approval_at: str, generation: int,
                              env: Optional[Dict[str, str]] = None) -> None:
    """Write the AUTHORITATIVE execution grant into the operator-only control store (outside client
    content). Bound to the project id, the resolved workspace path, the approval timestamp, and the
    approval generation (state version). Called by ``WorkExecutionService.approve``. Client code in the
    work dir cannot create this file to self-assert trust."""
    ws = Path(workspace)
    gp = _grant_path(workspace, env=env)
    gp.parent.mkdir(parents=True, exist_ok=True)
    grant = {"schema": "execution-grant/v1", "project_id": ws.parent.name,
             "workspace": str(ws.resolve()), "reviewer": reviewer, "approval_at": approval_at,
             "generation": int(generation), "revoked": False}
    tmp = gp.with_name(gp.name + ".tmp")
    tmp.write_text(json_dumps(grant), encoding="utf-8")
    os.replace(tmp, gp)


def revoke_execution_authority(workspace: str, *, env: Optional[Dict[str, str]] = None) -> None:
    """Revoke the execution grant (fail-closed thereafter). Idempotent."""
    gp = _grant_path(workspace, env=env)
    grant = _read_json(gp)
    if grant:
        grant["revoked"] = True
        gp.write_text(json_dumps(grant), encoding="utf-8")


def _latest_ready_to_execute_at(state: Dict) -> str:
    history = state.get("history", []) if isinstance(state.get("history"), list) else []
    at = ""
    for h in history:
        if isinstance(h, dict) and h.get("to_state") == "READY_TO_EXECUTE":
            at = str(h.get("at", "") or at)          # last one wins (most recent approval generation)
    return at


def assess_execution_trust(workspace: str, *, env: Optional[Dict[str, str]] = None) -> TrustDecision:
    """Trusted only when a genuine operator approval GRANT exists in the operator-only control store
    (outside client-writable content) AND it is current for THIS project/workspace/approval-generation.
    A client checkout that pre-creates any/all workspace files (EXECUTION_APPROVED.json, APPROVAL.json,
    WORK_RUN_STATE.json) CANNOT self-assert trust — those are evidence only, never authority. Revoked
    or stale (superseded/tampered) approvals fail closed. An operator-configured AIQA_TRUSTED_ROOTS
    root also grants trust. Otherwise untrusted, with an exact action."""
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
        wsr = ws

    _deny = TrustDecision(
        False, "no current operator execution grant in the control store",
        f"run `approve` (writes the authoritative grant to {CONTROL_DIR_ENV} / <OUTPUT_DIR>/"
        f"{_CONTROL_SUBDIR}, outside client content) or add a trusted root to {TRUSTED_ROOTS_ENV}; "
        "workspace files cannot self-assert trust and untrusted client code is not executed")

    grant = _read_json(_grant_path(workspace, env=env))
    if grant.get("revoked") is True or not grant:
        return _deny
    reviewer = str(grant.get("reviewer") or "").strip()
    if grant.get("project_id") != ws.parent.name or not reviewer:
        return _deny
    if str(grant.get("workspace") or "") != str(wsr):        # workspace binding
        return _deny
    # Staleness: the grant's approval timestamp must still match the canonical approval EVIDENCE — a
    # re-approval or tampering that does not go through approve() (which rewrites both) fails closed.
    approval_at = str(grant.get("approval_at") or "")
    if not approval_at:
        return _deny
    approval = _read_json(ws / "APPROVAL.json")
    if str(approval.get("at") or "") != approval_at or approval.get("approved") is not True:
        return _deny
    state = _read_json(ws / "WORK_RUN_STATE.json")
    if _latest_ready_to_execute_at(state) != approval_at:    # superseded/reset approval => stale
        return _deny
    return TrustDecision(True, "operator-approved (authoritative grant current + consistent evidence)")


def json_dumps(obj) -> str:
    import json
    return json.dumps(obj, indent=2, sort_keys=True)


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

"""Bounded Claude Code execution worker (v3.2 Sections 9-10).

A pluggable autonomous-execution adapter over the installed Claude Code headless interface
(`claude -p ... --output-format json`). It is bounded and safe by construction:

- NEVER uses --dangerously-skip-permissions; edits are gated with --permission-mode acceptEdits and
  an explicit --allowedTools list, confined to the project workspace (cwd).
- accepts a structured Work Order, enforces a turn limit + timeout + optional budget, supports
  cancellation, records a resumable session id, and returns a structured result.
- stdout/stderr are secret-redacted before persistence; the execution session is written atomically;
  produced artifacts are hashed by the existing lifecycle.

It is not exposed as arbitrary HTTP execution: the Dashboard may only start a validated Work Order.
A deterministic ``FixtureClaudeWorker`` (is_acceptance_fixture=True) is used in unit tests.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.orchestration.content_safety import redact_intake_text

_FORBIDDEN_FLAGS = ("--dangerously-skip-permissions", "--allow-dangerously-skip-permissions")


@dataclass
class WorkOrder:
    project_id: str
    objective: str                              # the bounded task the worker must accomplish
    acceptance: str = ""                        # how success is judged (informational)
    allowed_tools: List[str] = field(default_factory=lambda: ["Edit", "Write", "Read"])
    max_turns: int = 6
    timeout_s: int = 300
    model: str = ""                             # optional model override
    mode: str = "AUTONOMOUS_LOCAL"

    def prompt(self) -> str:
        parts = [self.objective.strip()]
        if self.acceptance:
            parts.append("Acceptance: " + self.acceptance.strip())
        parts.append("Work only within this workspace. Do not run destructive commands or contact "
                     "external services.")
        return "\n\n".join(parts)

    def digest(self) -> str:
        import hashlib
        payload = json.dumps({"objective": self.objective, "acceptance": self.acceptance,
                              "allowed_tools": sorted(self.allowed_tools), "max_turns": self.max_turns},
                             sort_keys=True)
        return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WorkerResult:
    ok: bool
    executor: str
    version: str
    mode: str
    session_id: str
    returncode: Optional[int]
    files_changed: List[str]
    stop_reason: str
    duration_s: float
    tokens: Optional[int] = None
    cost_usd: Optional[float] = None
    evidence: List[str] = field(default_factory=list)     # relative evidence paths
    blockers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_worker_command(order: WorkOrder, *, exe: str = "claude", resume_session: str = "") -> List[str]:
    """Build the bounded headless command (pure/testable). NEVER includes a skip-permissions flag.
    ``exe`` is the resolved Claude executable (on Windows the npm shim is ``claude.CMD``)."""
    cmd = [exe, "-p", order.prompt(), "--output-format", "json",
           "--max-turns", str(int(order.max_turns)), "--permission-mode", "acceptEdits"]
    if order.allowed_tools:
        cmd += ["--allowedTools", *order.allowed_tools]
    if order.model:
        cmd += ["--model", order.model]
    if resume_session:
        cmd += ["--resume", resume_session]
    assert not any(f in cmd for f in _FORBIDDEN_FLAGS), "skip-permissions is forbidden"
    return cmd


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClaudeCodeWorker:
    """Runs a Work Order via the real Claude Code CLI, bounded and confined."""

    is_acceptance_fixture = False
    executor_id = "worker:claude-code"

    def __init__(self, *, which=shutil.which, run=subprocess.run) -> None:
        self._which = which
        self._run = run

    def _exe(self) -> Optional[str]:
        # Resolve the real executable (on Windows shutil.which returns the npm claude.CMD shim;
        # subprocess must invoke the resolved path/name, not the bare "claude").
        return self._which("claude")

    def detect(self) -> Dict[str, Any]:
        exe = self._exe()
        if not exe:
            return {"available": False, "version": ""}
        try:
            p = self._run([exe, "--version"], capture_output=True, text=True, timeout=15,
                          check=False)
            return {"available": p.returncode == 0, "version": (p.stdout or "").strip()}
        except (OSError, subprocess.SubprocessError):
            return {"available": False, "version": ""}

    def run(self, order: WorkOrder, workspace: str, *, resume_session: str = "",
            cancel: Optional[threading.Event] = None) -> WorkerResult:
        ws = Path(workspace)
        ws.mkdir(parents=True, exist_ok=True)
        det = self.detect()
        version = det.get("version", "")
        before = self._snapshot(ws)
        started = datetime.now(timezone.utc)
        cmd = build_worker_command(order, exe=(self._exe() or "claude"), resume_session=resume_session)
        session_id, returncode, stop_reason = "", None, ""
        tokens: Optional[int] = None
        cost: Optional[float] = None
        raw_out, raw_err = "", ""
        if not det.get("available"):
            stop_reason = "claude CLI unavailable (Needs Operator: install + authenticate)"
        else:
            try:
                proc = self._run(cmd, cwd=str(ws), capture_output=True, text=True,  # noqa: S603
                                 timeout=order.timeout_s, check=False)
                returncode, raw_out, raw_err = proc.returncode, proc.stdout or "", proc.stderr or ""
                session_id, tokens, cost = _parse_result_json(raw_out)
                stop_reason = "completed" if returncode == 0 else f"exit {returncode}"
            except subprocess.TimeoutExpired:
                stop_reason = f"timeout after {order.timeout_s}s"
            except OSError as exc:
                stop_reason = f"spawn error: {type(exc).__name__}"
        if cancel is not None and cancel.is_set():
            stop_reason = "cancelled by operator"
        duration = (datetime.now(timezone.utc) - started).total_seconds()
        # Redact + persist bounded evidence.
        ev_dir = ws / "evidence" / "worker"
        ev_dir.mkdir(parents=True, exist_ok=True)
        (ev_dir / "stdout.txt").write_text(redact_intake_text(raw_out).text[-16000:], encoding="utf-8")
        (ev_dir / "stderr.txt").write_text(redact_intake_text(raw_err).text[-16000:], encoding="utf-8")
        after = self._snapshot(ws)
        files_changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k)
                               and not k.startswith("evidence/worker/"))
        ok = bool(det.get("available")) and returncode == 0 and stop_reason == "completed"
        result = WorkerResult(
            ok=ok, executor=self.executor_id, version=version, mode=order.mode,
            session_id=session_id, returncode=returncode, files_changed=files_changed,
            stop_reason=stop_reason, duration_s=round(duration, 3), tokens=tokens, cost_usd=cost,
            evidence=["evidence/worker/stdout.txt", "evidence/worker/stderr.txt"],
            blockers=([] if ok else [stop_reason]))
        self._write_session(ws, order, result, version)
        return result

    @staticmethod
    def _snapshot(ws: Path) -> Dict[str, str]:
        import hashlib
        out: Dict[str, str] = {}
        for f in ws.rglob("*"):
            if f.is_file() and ".git" not in f.parts and "node_modules" not in f.parts:
                try:
                    out[str(f.relative_to(ws)).replace("\\", "/")] = hashlib.sha256(
                        f.read_bytes()).hexdigest()
                except OSError:
                    continue
        return out

    def _write_session(self, ws: Path, order: WorkOrder, result: WorkerResult, version: str) -> None:
        session = {
            "schema": "execution-session/v1", "executor": self.executor_id, "version": version,
            "mode": order.mode, "workspace": str(ws), "work_order_digest": order.digest(),
            "authorized_tools": order.allowed_tools, "session_id": result.session_id,
            "started_at": _now(), "returncode": result.returncode,
            "files_changed": result.files_changed, "stop_reason": result.stop_reason,
            "duration_s": result.duration_s, "tokens": result.tokens, "cost_usd": result.cost_usd,
            "blockers": result.blockers, "ok": result.ok,
            "note": "stdout/stderr are secret-redacted; no dangerously-skip-permissions was used",
        }
        path = ws / "EXECUTION_SESSION.json"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(session, indent=2, sort_keys=True), encoding="utf-8")
        import os
        os.replace(tmp, path)                       # atomic


def _parse_result_json(stdout: str):
    """Best-effort parse of the headless JSON result for session id + usage (never a secret)."""
    txt = (stdout or "").strip()
    start = txt.rfind("{")
    if start == -1:
        return "", None, None
    try:
        obj = json.loads(txt[start:])
    except ValueError:
        try:
            obj = json.loads(txt)
        except ValueError:
            return "", None, None
    sid = str(obj.get("session_id") or obj.get("sessionId") or "")
    usage = obj.get("usage") or {}
    tokens = usage.get("output_tokens") or usage.get("total_tokens")
    cost = obj.get("total_cost_usd") or obj.get("cost_usd")
    return sid, (int(tokens) if isinstance(tokens, (int, float)) else None), \
        (float(cost) if isinstance(cost, (int, float)) else None)


class FixtureClaudeWorker(ClaudeCodeWorker):
    """A deterministic worker for unit tests (labeled). It applies a fixed edit instead of invoking
    the provider, so the orchestration/lifecycle can be exercised without a live provider."""

    is_acceptance_fixture = True
    executor_id = "worker:fixture"

    def __init__(self, edits: Optional[Dict[str, str]] = None) -> None:
        super().__init__()
        self._edits = edits or {}

    def run(self, order: WorkOrder, workspace: str, *, resume_session: str = "",
            cancel: Optional[threading.Event] = None) -> WorkerResult:
        ws = Path(workspace)
        ws.mkdir(parents=True, exist_ok=True)
        before = self._snapshot(ws)
        for rel, content in self._edits.items():
            target = (ws / rel)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
        ev_dir = ws / "evidence" / "worker"
        ev_dir.mkdir(parents=True, exist_ok=True)
        (ev_dir / "stdout.txt").write_text("[fixture worker] applied deterministic edits\n",
                                           encoding="utf-8")
        (ev_dir / "stderr.txt").write_text("", encoding="utf-8")
        after = self._snapshot(ws)
        files_changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k)
                               and not k.startswith("evidence/worker/"))
        result = WorkerResult(
            ok=True, executor=self.executor_id, version="fixture", mode=order.mode,
            session_id="fixture-session", returncode=0, files_changed=files_changed,
            stop_reason="completed", duration_s=0.0,
            evidence=["evidence/worker/stdout.txt", "evidence/worker/stderr.txt"])
        self._write_session(ws, order, result, "fixture")
        return result

"""Bounded Claude Code execution worker (v3.2 Sections 9-10).

A pluggable autonomous-execution adapter over the installed Claude Code headless interface
(`claude -p ... --output-format json`). It is bounded and safe by construction:

- NEVER uses --dangerously-skip-permissions; edits are gated with --permission-mode acceptEdits and
  an explicit --allowedTools list, confined to the project workspace (cwd).
- accepts a structured Work Order, enforces a hard timeout + budget (`--max-budget-usd`) + allowed
  tools + permission mode (there is no `--max-turns`), supports
  cancellation, records a resumable session id, and returns a structured result.
- stdout/stderr are secret-redacted before persistence; the execution session is written atomically;
  produced artifacts are hashed by the existing lifecycle.

It is not exposed as arbitrary HTTP execution: the Dashboard may only start a validated Work Order.
A deterministic ``FixtureClaudeWorker`` (is_acceptance_fixture=True) is used in unit tests.
"""
from __future__ import annotations

import json
import os
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
    max_budget_usd: float = 0.50                # genuine bound via the CLI's --max-budget-usd
    timeout_s: int = 300                        # hard wall-clock bound enforced by the runner
    model: str = ""                             # optional model override
    session_id: str = ""                        # deterministic/resumable session id
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
                              "allowed_tools": sorted(self.allowed_tools),
                              "max_budget_usd": self.max_budget_usd}, sort_keys=True)
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
    """Build the bounded headless command (pure/testable) using ONLY flags the installed Claude CLI
    actually supports (verified against ``claude --help``): ``--output-format``, ``--permission-mode
    acceptEdits``, ``--allowedTools``, ``--max-budget-usd`` (the real budget bound), ``--session-id``,
    ``--resume``, ``--model``. It NEVER includes a skip-permissions flag and there is no ``--max-turns``
    (that flag does not exist). ``exe`` is the resolved executable (Windows npm shim is ``claude.CMD``)."""
    cmd = [exe, "-p", order.prompt(), "--output-format", "json",
           "--permission-mode", "acceptEdits"]
    if order.allowed_tools:
        cmd += ["--allowedTools", *order.allowed_tools]
    if order.max_budget_usd and order.max_budget_usd > 0:
        cmd += ["--max-budget-usd", str(order.max_budget_usd)]
    if order.session_id and not resume_session:
        cmd += ["--session-id", order.session_id]
    if order.model:
        cmd += ["--model", order.model]
    if resume_session:
        cmd += ["--resume", resume_session]
    assert not any(f in cmd for f in _FORBIDDEN_FLAGS), "skip-permissions is forbidden"
    return cmd


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _terminate_tree(proc) -> None:
    """Kill a process and its children safely on Windows (taskkill /T) and POSIX (killpg)."""
    import os as _os
    import signal
    import time
    try:
        if _os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],  # noqa: S603,S607
                           capture_output=True, timeout=15, check=False)
        else:
            try:
                _os.killpg(_os.getpgid(proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                return
            time.sleep(0.8)
            if proc.poll() is None:
                _os.killpg(_os.getpgid(proc.pid), signal.SIGKILL)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


class ClaudeCodeWorker:
    """Runs a Work Order via the real Claude Code CLI, bounded and confined."""

    is_acceptance_fixture = False
    executor_id = "worker:claude-code"

    def __init__(self, *, which=shutil.which, run=subprocess.run, popen=subprocess.Popen,
                 env: Optional[Dict[str, str]] = None, os_name: Optional[str] = None) -> None:
        self._which = which
        self._run = run
        self._popen = popen
        self._env = env if env is not None else dict(os.environ)
        # Injectable OS name so a test can exercise the Windows resolver branch WITHOUT patching the
        # global os.name (which would make pathlib construct a WindowsPath on Linux and crash). The
        # branch is logical only; the Path objects stay the real platform's type.
        self._os_name = os_name if os_name is not None else os.name

    # Windows shell wrappers npm installs alongside the native binary. Invoking these via subprocess
    # goes through cmd.exe/powershell, which re-parses the multi-line ``-p`` prompt and corrupts it,
    # so the CLI silently ignores ``--permission-mode`` / ``--output-format`` and drops into an
    # interactive "approve the pending write" prose flow (proven by an A/B test: native exe passes,
    # .CMD shim fails, all else identical). We therefore never execute these for the worker.
    _WIN_WRAPPER_SUFFIXES = (".cmd", ".bat", ".ps1")

    def _resolve_claude_bin(self) -> tuple[Optional[str], str]:
        """Portably resolve a NATIVE Claude executable to invoke directly (no shell re-parsing).
        Order: (1) an explicit ``AIQA_CLAUDE_BIN`` operator override (validated); (2) ``which`` on
        POSIX (its shim exec's the native binary cleanly); (3) on Windows, the native ``claude.exe``
        that the resolved npm wrapper targets. Never hard-codes a user path and never executes an
        arbitrary batch file. Returns ``(path, "")`` on success, or ``(None, reason)`` with an exact
        operator action when no trusted native executable can be resolved."""
        override = (self._env.get("AIQA_CLAUDE_BIN") or "").strip()
        if override:
            p = Path(override)
            if not p.is_file():
                return None, f"AIQA_CLAUDE_BIN is set but is not a file: {override}"
            if self._os_name == "nt" and p.suffix.lower() in self._WIN_WRAPPER_SUFFIXES:
                return None, ("AIQA_CLAUDE_BIN points to a shell wrapper "
                              f"({p.suffix}); set it to the native claude.exe (a .cmd/.bat/.ps1 "
                              "wrapper corrupts the multi-line prompt via cmd.exe)")
            return str(p), ""
        found = self._which("claude")
        if not found:
            return None, ""                              # simply not installed (detect() handles it)
        if self._os_name != "nt":
            return str(found), ""                        # POSIX shim exec's the native binary cleanly
        fp = Path(found)
        if fp.suffix.lower() in self._WIN_WRAPPER_SUFFIXES:
            native = fp.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin" / "claude.exe"
            if native.is_file():
                return str(native), ""                   # derived from where `which` found the wrapper
            return None, ("resolved a Windows shell wrapper "
                          f"(claude{fp.suffix}) that corrupts the multi-line prompt via cmd.exe, and "
                          "the native claude.exe was not found beside it; set AIQA_CLAUDE_BIN to the "
                          "native Anthropic claude executable")
        return str(found), ""                            # `which` already returned a native executable

    def _exe(self) -> Optional[str]:
        return self._resolve_claude_bin()[0]

    def detect(self) -> Dict[str, Any]:
        """Honest worker readiness: ``Ready`` (a native executable resolves and ``--version`` runs),
        ``Needs Operator`` (installed but not worker-usable, e.g. a Windows wrapper without the native
        exe, or ``--version`` fails), or ``Unavailable`` (not installed). Never runs a shell wrapper."""
        exe, reason = self._resolve_claude_bin()
        if not exe:
            return {"available": False, "version": "", "exe": "",
                    "readiness": ("Needs Operator" if reason else "Unavailable"),
                    "reason": reason, "action": (reason or "install Claude Code and authenticate")}
        try:
            p = self._run([exe, "--version"], capture_output=True, text=True, timeout=15,
                          check=False)
            ok = p.returncode == 0
            return {"available": ok, "version": (p.stdout or "").strip(), "exe": exe,
                    "readiness": ("Ready" if ok else "Needs Operator"),
                    "reason": ("" if ok else "`claude --version` did not succeed"),
                    "action": ("" if ok else "verify the Claude Code install + authentication")}
        except (OSError, subprocess.SubprocessError) as exc:
            return {"available": False, "version": "", "exe": exe, "readiness": "Needs Operator",
                    "reason": f"{type(exc).__name__}", "action": "verify the Claude Code install"}

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
        parsed = _ResultJson()
        if not det.get("available"):
            stop_reason = (det.get("reason") or det.get("action")
                           or "claude CLI unavailable (Needs Operator: install + authenticate)")
        else:
            returncode, raw_out, raw_err, stop_reason = self._run_controlled(cmd, ws, order, cancel)
            parsed = _parse_result_json(raw_out)
            session_id, tokens, cost = parsed.session_id, parsed.tokens, parsed.cost
        duration = (datetime.now(timezone.utc) - started).total_seconds()
        # Redact + persist bounded evidence.
        ev_dir = ws / "evidence" / "worker"
        ev_dir.mkdir(parents=True, exist_ok=True)
        (ev_dir / "stdout.txt").write_text(redact_intake_text(raw_out).text[-16000:], encoding="utf-8")
        (ev_dir / "stderr.txt").write_text(redact_intake_text(raw_err).text[-16000:], encoding="utf-8")
        after = self._snapshot(ws)
        files_changed = sorted(k for k in set(before) | set(after) if before.get(k) != after.get(k)
                               and not k.startswith("evidence/worker/"))
        # A run is only genuinely OK when the process completed AND the headless JSON result was a
        # real, non-error completion. When the provider instead returns prose (e.g. an interactive
        # permission prompt that was not auto-granted) --output-format json yields no result object;
        # we must NOT report success in that case (honest failure, not a false green).
        ok = bool(det.get("available")) and returncode == 0 and stop_reason == "completed"
        if ok and det.get("available"):
            if parsed.is_error:
                ok = False
                stop_reason = parsed.error or "provider returned an error result"
            elif not parsed.has_result:
                ok = False
                stop_reason = ("no valid JSON result from the provider (possible un-granted "
                               "permission prompt or interruption); no completion recorded")
        result = WorkerResult(
            ok=ok, executor=self.executor_id, version=version, mode=order.mode,
            session_id=session_id, returncode=returncode, files_changed=files_changed,
            stop_reason=stop_reason, duration_s=round(duration, 3), tokens=tokens, cost_usd=cost,
            evidence=["evidence/worker/stdout.txt", "evidence/worker/stderr.txt"],
            blockers=([] if ok else [stop_reason]))
        self._write_session(ws, order, result, version)
        return result

    def _run_controlled(self, cmd, ws, order, cancel):
        """Popen-based execution with a hard wall-clock timeout, genuine cancellation, and a safe
        process-tree kill on both Windows and POSIX. No shell; output is drained without deadlock and
        bounded. Returns (returncode, stdout, stderr, stop_reason)."""
        import time
        popen_kwargs: Dict[str, Any] = dict(
            cwd=str(ws), stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if os.name == "nt":
            popen_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        else:
            popen_kwargs["start_new_session"] = True   # own process group for killpg
        try:
            proc = self._popen(cmd, **popen_kwargs)     # noqa: S603 - shell=False, fixed argv
        except OSError as exc:
            return None, "", f"{type(exc).__name__}: {exc}", f"spawn error: {type(exc).__name__}"

        collected: Dict[str, str] = {"out": "", "err": ""}

        def _drain():
            try:
                collected["out"], collected["err"] = proc.communicate()
            except Exception as exc:                    # pragma: no cover - defensive
                collected["err"] = f"{type(exc).__name__}: {exc}"

        t = threading.Thread(target=_drain, daemon=True)
        t.start()
        deadline = time.monotonic() + max(1, int(order.timeout_s))
        stop = "completed"
        cancel_marker = Path(ws) / "WORKER_CANCEL.json"
        while t.is_alive():
            if (cancel is not None and cancel.is_set()) or cancel_marker.exists():
                _terminate_tree(proc)
                stop = "cancelled by operator"
                break
            if time.monotonic() > deadline:
                _terminate_tree(proc)
                stop = f"timeout after {order.timeout_s}s"
                break
            t.join(0.2)
        t.join(8)                                        # let communicate() return after a kill
        out = (collected.get("out") or "")[-16000:]
        err = (collected.get("err") or "")[-16000:]
        rc = proc.returncode
        if stop == "completed":
            stop = "completed" if rc == 0 else f"exit {rc}"
        return rc, out, err, stop

    @staticmethod
    def _read_session_static(ws: Path) -> Dict[str, Any]:
        try:
            return json.loads((ws / "EXECUTION_SESSION.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    # Agent/tooling scaffold directories that are never a client deliverable and must not count as
    # produced artifacts (e.g. the operator's global memory hook writes .remember/ into the cwd).
    _SCAFFOLD = frozenset({".git", "node_modules", ".remember", ".claude", "__pycache__"})

    @classmethod
    def _snapshot(cls, ws: Path) -> Dict[str, str]:
        import hashlib
        out: Dict[str, str] = {}
        for f in ws.rglob("*"):
            if f.is_file() and not (set(f.parts) & cls._SCAFFOLD):
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
        import time as _t
        for _attempt in range(12):                  # atomic; retry the Windows concurrent-reader race
            try:
                os.replace(tmp, path)
                break
            except PermissionError:
                if _attempt == 11:
                    raise
                _t.sleep(0.02)


def worker_readiness(*, which=shutil.which, run=subprocess.run,
                     env: Optional[Dict[str, str]] = None,
                     os_name: Optional[str] = None) -> Dict[str, Any]:
    """Read-only Claude Worker readiness for the dashboard (Ready / Needs Operator / Unavailable).
    Bounded (one `--version` probe); never executes a Work Order and never a shell wrapper."""
    d = ClaudeCodeWorker(which=which, run=run, env=env, os_name=os_name).detect()
    return {"component": "claude_worker", "readiness": d.get("readiness", "Unavailable"),
            "version": d.get("version", ""), "reason": d.get("reason", ""),
            "action": d.get("action", ""),
            "exe_kind": (Path(d["exe"]).suffix.lower() or ".exe") if d.get("exe") else ""}


@dataclass
class _ResultJson:
    session_id: str = ""
    tokens: Optional[int] = None
    cost: Optional[float] = None
    has_result: bool = False        # a real headless result object was parsed
    is_error: bool = False          # the provider reported an error (e.g. budget/permission)
    error: str = ""


def _parse_result_json(stdout: str) -> "_ResultJson":
    """Parse the headless JSON result for session id + usage + error state (never a secret). Robust
    to trailing/leading non-JSON noise: scans candidate objects and keeps the one that looks like the
    result. When ``--output-format json`` produced no result object (e.g. the provider returned prose
    for an un-granted permission prompt), ``has_result`` stays False so the caller fails honestly."""
    txt = (stdout or "").strip()
    obj = None
    # Try the whole blob, then progressively later '{' positions (handles a leading banner) and each
    # line, keeping the last object that carries result-shaped fields.
    candidates = []
    try:
        candidates.append(json.loads(txt))
    except ValueError:
        pass
    for line in reversed(txt.splitlines()):
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                candidates.append(json.loads(line))
            except ValueError:
                continue
    for cand in candidates:
        if isinstance(cand, dict) and (cand.get("session_id") or cand.get("type") == "result"
                                       or "usage" in cand):
            obj = cand
            break
    if obj is None:
        return _ResultJson()
    sid = str(obj.get("session_id") or obj.get("sessionId") or "")
    usage = obj.get("usage") or {}
    tokens = usage.get("output_tokens") or usage.get("total_tokens")
    cost = obj.get("total_cost_usd") or obj.get("cost_usd")
    is_error = bool(obj.get("is_error")) or str(obj.get("subtype", "")).startswith("error")
    errs = obj.get("errors") or []
    error = "; ".join(str(e) for e in errs) if errs else (
        str(obj.get("subtype", "")) if is_error else "")
    return _ResultJson(
        session_id=sid, tokens=(int(tokens) if isinstance(tokens, (int, float)) else None),
        cost=(float(cost) if isinstance(cost, (int, float)) else None),
        has_result=True, is_error=is_error, error=error)


_ORDER_NS = __import__("uuid").UUID("7b1e2c9a-4d3f-5a6b-8c7d-9e0f1a2b3c4d")


def build_order_from_context(ctx, *, allowed_tools: Optional[List[str]] = None,
                             max_budget_usd: float = 0.50, timeout_s: int = 300) -> WorkOrder:
    """Build the Work Order ONLY from the validated persisted project state handed in by
    WorkExecutionService (requirements + profile). It never accepts an arbitrary prompt, command,
    argv, workspace path, allowed-tools list, model, or budget from an HTTP caller. The session id is
    derived deterministically from the project id so a worker can be resumed."""
    import uuid
    reqs = [str(r) for r in (getattr(ctx, "requirements", None) or [])][:25]
    objective = ("Implement or repair the deliverables for this project WITHIN this workspace so its "
                 "recorded requirements and acceptance criteria are satisfied. Make the smallest "
                 "correct change and add or fix tests as needed. Do not touch anything outside the "
                 "workspace or contact external services.")
    if reqs:
        objective += "\n\nRecorded requirements:\n" + "\n".join(f"- {r}" for r in reqs)
    return WorkOrder(project_id=ctx.project_id, objective=objective,
                     acceptance="the project's own validation command passes",
                     allowed_tools=allowed_tools or ["Edit", "Write", "Read"],
                     max_budget_usd=max_budget_usd, timeout_s=timeout_s,
                     session_id=str(uuid.uuid5(_ORDER_NS, ctx.project_id)))


class ClaudeWorkerExecutor:
    """Production executor satisfying the WorkExecutionService contract. It builds the Work Order
    from persisted state, runs the (real or fixture) worker confined to the project workspace, and
    records the GENUINE produced files as artifacts + the worker session/output as evidence. It never
    fabricates an artifact list and never claims validation success - validation is a separate step
    through the existing validation executor."""

    def __init__(self, worker: Optional[ClaudeCodeWorker] = None, *,
                 allowed_tools: Optional[List[str]] = None, max_budget_usd: float = 0.50,
                 timeout_s: int = 300, resume: bool = False,
                 cancel: Optional[threading.Event] = None) -> None:
        self._worker = worker or ClaudeCodeWorker()
        self._allowed_tools = allowed_tools
        self._budget = max_budget_usd
        self._timeout = timeout_s
        self._resume = resume
        self._cancel = cancel

    @property
    def is_acceptance_fixture(self) -> bool:
        return bool(getattr(self._worker, "is_acceptance_fixture", False))

    @property
    def executes_client_code(self) -> bool:
        # A real Claude worker runs the provider against the client workspace (client code); a
        # deterministic acceptance fixture applies fixed edits and executes nothing untrusted.
        return not self.is_acceptance_fixture

    @property
    def executor_id(self) -> str:
        return getattr(self._worker, "executor_id", "worker:claude-code")

    def execute(self, ctx):
        from core.schemas.work_execution import EvidenceItem, ExecutionArtifact, ExecutionOutcome
        order = build_order_from_context(ctx, allowed_tools=self._allowed_tools,
                                         max_budget_usd=self._budget, timeout_s=self._timeout)
        resume_id = ""
        if self._resume:
            prior = ClaudeCodeWorker._read_session_static(Path(ctx.workspace_dir))
            resume_id = str(prior.get("session_id") or "")
        result = self._worker.run(order, ctx.workspace_dir, resume_session=resume_id,
                                  cancel=self._cancel)
        artifacts = [ExecutionArtifact(f, "fix") for f in result.files_changed
                     if f not in ("EXECUTION_SESSION.json",)]
        evidence = [
            EvidenceItem("worker-session", "log", "EXECUTION_SESSION.json",
                         "claude worker execution session (redacted)", ctx.now),
            EvidenceItem("worker-stdout", "log", "evidence/worker/stdout.txt",
                         "worker stdout (bounded, redacted)", ctx.now),
            EvidenceItem("worker-stderr", "log", "evidence/worker/stderr.txt",
                         "worker stderr (bounded, redacted)", ctx.now),
        ]
        notes = [f"claude worker: {result.stop_reason}; {len(artifacts)} file(s) changed; "
                 f"session={result.session_id or order.session_id}; budget<=${self._budget}"]
        blockers = [] if (result.ok and artifacts) else (
            result.blockers or ["worker produced no file changes"])
        return ExecutionOutcome(artifacts=artifacts, evidence=evidence,
                                files_changed=result.files_changed, progress_notes=notes,
                                blockers=blockers)

    def validate(self, ctx):
        raise ValueError("the worker records execution only; run `client-work validate` with a real "
                         "command (the existing validation executor + integrity gates apply)")


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

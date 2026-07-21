"""Durable local supervisor for the Dashboard + Direct Collaboration Driver (Issue #14 P0 5039502213).

Runs OUTSIDE the Claude session lifecycle (via a Windows Scheduled Task at logon, restart-on-failure)
so the owner can leave the machine and the system stays recoverable:

- keeps exactly ONE Dashboard on 8765 serving the latest checked-out main (restart if down or stale);
- runs one Direct-Driver cycle tick each interval — deterministic and FREE when idle (GPT is invoked
  only for a new QUESTION/PROPOSAL/CHECKPOINT; caps + cache stay enforced);
- restarts only the failed component and never spawns duplicates (single-instance lock);
- writes bounded local logs + a truthful status file surfaced in /collab and /activity.

This is a minimal operational closure of Issue #14, not a general agent platform.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))                       # importable as a standalone Scheduled Task
VENV_PY = REPO / ".venv" / "Scripts" / "python.exe"
PORT = 8765
_HEARTBEAT_MAX_S = 300.0
_LOG_MAX_BYTES = 512_000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class SupervisorConfig:
    output_root: str = "outputs"
    port: int = PORT
    interval_s: float = 30.0
    heartbeat_max_s: float = _HEARTBEAT_MAX_S


@dataclass
class SupervisorDeps:
    """Injectable side effects so the decision logic is unit-testable without real processes."""
    health: Callable[[], Dict[str, Any]]
    current_head: Callable[[], str]
    start_dashboard: Callable[[], None]
    kill_dashboards: Callable[[], None]
    driver_tick: Callable[[], Dict[str, Any]]
    heartbeat_age_s: Callable[[], float]
    clock: Callable[[], str] = field(default=_now)


def supervise_once(deps: SupervisorDeps, cfg: SupervisorConfig) -> Dict[str, Any]:
    """One supervision cycle (pure decisions + injected effects). Restarts only what is unhealthy."""
    health = deps.health()
    dashboard = "ok"
    # Restart on down OR stale, and ALWAYS kill first: a running-but-unresponsive Dashboard reports
    # down over HTTP yet still holds :8765, so a bare start would race a duplicate. kill_dashboards is
    # a no-op when nothing is running.
    if not health.get("up") or health.get("stale"):
        deps.kill_dashboards()
        deps.start_dashboard()
        dashboard = "restarted" if health.get("up") else "started"

    tick = deps.driver_tick()                       # free when idle; GPT only for new messages
    owner_action = bool(tick.get("owner_action"))

    status = {
        "checked_at": deps.clock(),
        # These are the health SAMPLE AT CHECK TIME (before any remediation this cycle); the action
        # taken is `dashboard_action`. They are deliberately not relabelled as the current live state,
        # since a freshly (re)started Dashboard is not yet serving when the cycle records the sample.
        "dashboard_up_at_check": bool(health.get("up")),
        "dashboard_stale_at_check": bool(health.get("stale")),
        "running_sha": health.get("sha", ""),
        "expected_head": deps.current_head(),
        "dashboard_action": dashboard,
        "driver_stage": (tick.get("health") or {}).get("stage", ""),
        "driver_heartbeat_age_s": round(deps.heartbeat_age_s(), 1),
        "owner_action_required": owner_action,
    }
    _write_status(cfg.output_root, status)
    return {"dashboard": dashboard, "owner_action": owner_action, "status": status}


def _status_path(output_root: str) -> Path:
    path = Path(output_root) / "_review_relay" / "collab_supervisor.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _write_status(output_root: str, status: Dict[str, Any]) -> None:
    path = _status_path(output_root)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


# --- real (non-test) side effects -----------------------------------------------------------------
def _log(output_root: str, message: str) -> None:
    path = Path(output_root) / "_review_relay" / "collab_supervisor.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    _rotate(path)                                       # bounded: truncate to the recent half at the cap
    try:
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"{_now()} {message}\n")
    except OSError:
        pass


def _real_health(port: int) -> Dict[str, Any]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/build", timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return {"up": True, "stale": bool(data.get("stale")), "sha": data.get("running_sha", "")}
    except Exception:
        return {"up": False, "stale": True, "sha": ""}


def _real_head() -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(REPO), capture_output=True,
                              text=True, timeout=10, check=False)
        return (proc.stdout or "").strip()[:12]
    except (OSError, subprocess.SubprocessError):
        return ""


def _kill_dashboards() -> None:
    # Windows: stop every python running `main.py dashboard` (except the supervisor). Read-only query
    # then a targeted stop; never touches other processes.
    if os.name != "nt":
        subprocess.run(["pkill", "-f", "main.py dashboard"], check=False)
        return
    ps = ("Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
          "Where-Object { $_.CommandLine -match 'main.py dashboard' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=False,
                   capture_output=True, timeout=30)


def _rotate(path: Path) -> None:
    """Keep a bounded log — truncate to the recent half when it exceeds the cap (no unbounded growth)."""
    try:
        if path.exists() and path.stat().st_size > _LOG_MAX_BYTES:
            tail = path.read_text(encoding="utf-8", errors="replace")[-_LOG_MAX_BYTES // 2:]
            path.write_text(tail, encoding="utf-8")
    except OSError:
        pass


def _start_dashboard(output_root: str) -> None:
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "DETACHED_PROCESS", 0)
    # Discard the Dashboard's stdout entirely: a captured file the long-lived Dashboard keeps open would
    # grow unbounded and cannot be rotated by the supervisor while held. The Dashboard's own state is
    # observed via /api/build, so its stdout carries nothing the supervisor needs.
    subprocess.Popen([str(VENV_PY), "main.py", "dashboard"], cwd=str(REPO),
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)


def _heartbeat_age_s(output_root: str) -> float:
    path = Path(output_root) / "_review_relay" / "collab_driver" / "state.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        beat = datetime.fromisoformat(str(data.get("updated_at", "")))
        return (datetime.now(timezone.utc) - beat).total_seconds()
    except (OSError, ValueError, TypeError):
        return 1e9


def _real_driver_tick(output_root: str) -> Dict[str, Any]:
    from core.collaboration.service import CollaborationCycle
    from core.collaboration.session_delivery import SessionRegistry
    reg = SessionRegistry(str(REPO / ".aiqa_collab_sessions.json"))
    cycle = CollaborationCycle(output_root, str(REPO), registry=reg)
    return cycle.tick()


def _real_deps(cfg: SupervisorConfig) -> SupervisorDeps:
    return SupervisorDeps(
        health=lambda: _real_health(cfg.port),
        current_head=_real_head,
        start_dashboard=lambda: _start_dashboard(cfg.output_root),
        kill_dashboards=_kill_dashboards,
        driver_tick=lambda: _real_driver_tick(cfg.output_root),
        heartbeat_age_s=lambda: _heartbeat_age_s(cfg.output_root))


def _acquire_lock() -> Optional[Path]:
    """Single-instance lock via ATOMIC O_EXCL create (no read-then-write race). A stale lock left by a
    dead process is reclaimed once; a lock held by a live supervisor refuses the new instance."""
    lock = REPO / ".aiqa_supervisor.lock"
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, str(os.getpid()).encode("utf-8"))
            os.close(fd)
            return lock
        except FileExistsError:
            try:
                pid = int(lock.read_text(encoding="utf-8").strip() or "0")
            except (OSError, ValueError):
                pid = 0
            if pid and _pid_alive(pid):
                return None                             # another live supervisor holds it
            try:
                lock.unlink()                           # stale lock from a dead process -> reclaim
            except OSError:
                return None
    return None


def _pid_alive(pid: int) -> bool:
    if os.name == "nt":
        out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True, text=True,
                             check=False)
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="AI QA Factory Dashboard + Driver supervisor")
    ap.add_argument("--output-root", default="outputs")
    ap.add_argument("--interval", type=float, default=30.0)
    ap.add_argument("--once", action="store_true", help="run a single supervision cycle and exit")
    args = ap.parse_args(argv)
    cfg = SupervisorConfig(output_root=args.output_root, interval_s=args.interval)
    deps = _real_deps(cfg)

    if args.once:
        out = supervise_once(deps, cfg)
        print(json.dumps(out["status"], ensure_ascii=False))
        return 0

    lock = _acquire_lock()
    if lock is None:
        _log(cfg.output_root, "another supervisor instance is alive; exiting")
        return 0
    _log(cfg.output_root, "supervisor started")
    try:
        while True:
            try:
                out = supervise_once(deps, cfg)
                _log(cfg.output_root, f"dashboard={out['dashboard']} owner_action={out['owner_action']}")
            except Exception as exc:  # noqa: BLE001 - a bad cycle must not kill the supervisor
                _log(cfg.output_root, f"cycle error: {type(exc).__name__}: {exc}")
            time.sleep(max(5.0, cfg.interval_s))
    finally:
        try:
            lock.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Shared local process-liveness helpers (Issue #17 P0-A fencing).

A single small utility so the product-packet recovery, the relaunch heartbeat, and the supervisor all
judge "is the writer's owner process still alive?" the same way — instead of an expired lease TIME
alone, which is NOT evidence a writer is dead (the live E2E produced a double-writer exactly because
recovery trusted time alone). ``core`` owns this; ``tools/collab_supervisor.py`` reuses it (never the
reverse — core must not import from tools).

Liveness is only meaningful on the SAME host. Cross-host we cannot inspect PIDs, so callers must fail
closed (treat as unknown) rather than time-reclaim, to avoid split-brain double writers.
"""
from __future__ import annotations

import os
import socket
import subprocess
from typing import Iterable, List, Optional


def local_host() -> str:
    try:
        return socket.gethostname()
    except OSError:
        return ""


def pid_alive(pid: int) -> bool:
    """True iff a process with ``pid`` currently exists on this host (best-effort, reuses the
    supervisor's original check). Never raises."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"], capture_output=True,
                                 text=True, check=False, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return True                                   # cannot prove death -> fail closed (assume alive)
        return str(pid) in (out.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                                       # exists but not ours -> alive
    except OSError:
        return False


def any_alive(pids: Iterable[int]) -> bool:
    return any(pid_alive(p) for p in pids)


def child_pids_of(pid: int) -> List[int]:
    """Best-effort DIRECT children of ``pid`` on this host (one level is enough: relaunch -> claude).
    Used by the heartbeat to persist the real worker child so a reparented survivor of a dead relaunch
    parent is still detected. Never raises; returns [] when it cannot enumerate."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return []
    if os.name == "nt":
        ps = f"(Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}').ProcessId"
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                                 text=True, check=False, timeout=15)
        except (OSError, subprocess.SubprocessError):
            return []
        return [int(x) for x in (out.stdout or "").split() if x.strip().isdigit()]
    try:
        out = subprocess.run(["pgrep", "-P", str(pid)], capture_output=True, text=True,
                             check=False, timeout=15)
    except (OSError, subprocess.SubprocessError):
        return []
    return [int(x) for x in (out.stdout or "").split() if x.strip().isdigit()]


def owner_liveness(*, owner_host: str, owner_pids: Iterable[int]) -> Optional[bool]:
    """Fencing verdict for a claim owner: ``True`` (a locally-verifiable owner process is alive → do
    NOT reclaim), ``False`` (same host, every owner pid is dead → safe to reclaim), or ``None``
    (liveness is unknowable here — different/empty host, or no pid info — the caller must FAIL CLOSED to
    a visible blocked state, never time-reclaim)."""
    host = str(owner_host or "").strip()
    if not host or host != local_host():
        return None
    pids = []
    for p in owner_pids or []:
        try:
            pids.append(int(p))
        except (TypeError, ValueError):
            continue
    if not pids:
        return None
    return any_alive(pids)

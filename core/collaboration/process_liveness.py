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


def _parent_map() -> dict:
    """One snapshot of {pid: parent_pid} for this host (single query — cheap enough for a heartbeat)."""
    out_map: dict = {}
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process | ForEach-Object "
              "{ \"$($_.ProcessId) $($_.ParentProcessId)\" }")
        try:
            out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                                 text=True, check=False, timeout=20)
        except (OSError, subprocess.SubprocessError):
            return out_map
        for line in (out.stdout or "").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
                out_map[int(parts[0])] = int(parts[1])
        return out_map
    try:
        out = subprocess.run(["ps", "-eo", "pid=,ppid="], capture_output=True, text=True,
                             check=False, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return out_map
    for line in (out.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            out_map[int(parts[0])] = int(parts[1])
    return out_map


def descendant_pids(pid: int) -> List[int]:
    """Best-effort FULL descendant subtree of ``pid`` on this host (all levels: relaunch -> claude ->
    bash -> git/pytest), from a single process snapshot. The heartbeat persists this whole set so a
    reparented survivor of a dead ancestor is still detected on recovery — direct children alone were
    the P0-A gap (a grandchild could survive). Never raises; returns [] when it cannot enumerate."""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return []
    parents = _parent_map()
    if not parents:
        return []
    children: dict = {}
    for child, parent in parents.items():
        children.setdefault(parent, []).append(child)
    out: List[int] = []
    seen = {pid}
    stack = list(children.get(pid, []))
    while stack:
        c = stack.pop()
        if c in seen:
            continue
        seen.add(c)
        out.append(c)
        stack.extend(children.get(c, []))
    return out


# Back-compat alias (now returns the FULL subtree, not just direct children).
child_pids_of = descendant_pids


def owner_liveness(*, owner_host: str, owner_pids: Iterable[int]) -> Optional[bool]:
    """Fencing verdict for a claim owner: ``True`` (a locally-verifiable owner process is alive → do
    NOT reclaim), ``False`` (same host, the FULLY-captured owner tree is every-pid dead → safe to
    reclaim), or ``None`` (liveness is unknowable here — the caller must FAIL CLOSED to a visible
    blocked state, never time-reclaim).

    ``None`` (fail closed) when: the host is different/empty; OR fewer than two owner pids were captured
    — a single recorded pid is typically just the relaunch parent before its worker child was persisted,
    and a lone dead pid can NOT prove the whole writer tree is dead (the P0-A reclaim-too-early gap)."""
    host = str(owner_host or "").strip()
    if not host or host != local_host():
        return None
    pids = []
    for p in owner_pids or []:
        try:
            pids.append(int(p))
        except (TypeError, ValueError):
            continue
    if len(pids) < 2:
        return None                                       # incomplete tree capture -> cannot prove death
    return any_alive(pids)

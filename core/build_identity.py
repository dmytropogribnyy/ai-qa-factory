"""Running-build identity + stale-process detection (P0-B).

The Dashboard/Observer are run from source. If someone updates the checkout (git pull / new commit)
but does not restart the process, the server keeps serving the OLD code. This module surfaces that:

  - ``running_sha``  — the commit HEAD captured ONCE at process start (what this process is serving);
  - ``head_sha``     — the repository HEAD resolved fresh on each call (what is on disk now);
  - ``stale``        — True when both are known and differ -> "Restart required".

It returns only non-sensitive values: short SHAs, a product version, an ISO start time, and booleans.
No secrets, no absolute paths. ``git`` resolution is best-effort and never raises to the caller.
"""
from __future__ import annotations

import subprocess
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_STALE_WARNING = "Restart required — Dashboard is serving older code"


def _git_head(cwd: Optional[str] = None) -> str:
    """Best-effort ``git rev-parse HEAD``; returns "" when git/repo is unavailable (never raises)."""
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=cwd, capture_output=True,
                             text=True, timeout=3)
        if out.returncode == 0:
            return (out.stdout or "").strip()
    except Exception:
        pass
    return ""


# The immutable running-build identity: the commit + wall-clock time the SERVER PROCESS started
# serving. It is frozen ONCE (idempotently) — captured eagerly by the server bootstrap
# (``freeze_running_identity`` in ``start_dashboard``), NOT lazily at first import, so it truly
# reflects the running process and does not drift with import timing.
_RUNNING: Dict[str, Any] = {"sha": None, "started_at": None}

# Short TTL cache so a per-page footer never pays a git subprocess on every render.
_HEAD_CACHE: Dict[str, Any] = {"sha": None, "at": 0.0}
_HEAD_TTL_S = 15.0


def freeze_running_identity(repo_dir: Optional[str] = None) -> Dict[str, Any]:
    """Eagerly capture the immutable running identity at process start (idempotent).

    Call this from the server bootstrap so ``running_sha``/``started_at`` reflect the commit and time
    the process actually began serving — never whenever this module first happened to be imported.
    Captures exactly once; later calls return the already-frozen values unchanged."""
    if _RUNNING["sha"] is None:
        _RUNNING["sha"] = _git_head(repo_dir)
        _RUNNING["started_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return dict(_RUNNING)


def _running() -> Dict[str, Any]:
    """Return the frozen running identity, capturing it now if the bootstrap never did (e.g. a
    direct library/test caller). Server processes freeze eagerly in ``start_dashboard``."""
    if _RUNNING["sha"] is None:
        freeze_running_identity()
    return _RUNNING


def _product_version() -> str:
    try:
        from core.scout import SCOUT_PRODUCT_NAME, SCOUT_VERSION
        return f"{SCOUT_PRODUCT_NAME} {SCOUT_VERSION}"
    except Exception:
        return "AI QA Factory"


def compute_identity(*, running_sha: str, head_sha: str, product_version: str,
                     started_at: str) -> Dict[str, Any]:
    """Pure, testable core: shape the identity dict and derive the stale flag.

    ``stale`` is True ONLY when both SHAs are known and differ — an unknown HEAD (no git) must never
    raise a false alarm. SHAs are truncated to 12 chars for display; they are not secrets."""
    running = (running_sha or "").strip()
    head = (head_sha or "").strip()
    stale = bool(running and head and running != head)
    return {
        "product_version": product_version,
        "running_sha": running[:12],
        "head_sha": head[:12] if head else "",
        "process_started_at": started_at,
        "stale": stale,
        "warning": _STALE_WARNING if stale else "",
    }


def current_identity(repo_dir: Optional[str] = None) -> Dict[str, Any]:
    """Live identity for this process. ``running_sha``/``started_at`` are the frozen process-start
    values; ``head_sha`` is resolved fresh (cached for a few seconds) so a moved HEAD is detected
    immediately — even before the first request is served."""
    run = _running()
    now = time.time()
    cached = _HEAD_CACHE["sha"]
    if cached is None or (now - _HEAD_CACHE["at"]) >= _HEAD_TTL_S:
        cached = _git_head(repo_dir)
        _HEAD_CACHE["sha"] = cached
        _HEAD_CACHE["at"] = now
    return compute_identity(running_sha=run["sha"], head_sha=cached,
                            product_version=_product_version(), started_at=run["started_at"])

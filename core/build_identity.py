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

import hashlib
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_STALE_WARNING = "Restart required — Dashboard is serving older code"

# The executable code this process actually runs. Docs, outputs, evidence, test data and the test
# suite are deliberately excluded: editing them cannot change what the running server does, and
# raising "restart required" for a docs edit teaches the operator to ignore the flag.
_CODE_ROOTS = ("main.py", "core")

# A commit SHA alone is a lie about a process started from a dirty tree, so the identity carries
# both: the SHA it started from AND whether uncommitted code was on disk at that moment.
_LOCAL_SUFFIX = " + local changes"


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
_RUNNING: Dict[str, Any] = {"sha": None, "started_at": None, "code": "", "dirty": None}

# Short TTL cache so a per-page footer never pays a git subprocess on every render.
_HEAD_CACHE: Dict[str, Any] = {"sha": None, "at": 0.0}
_HEAD_TTL_S = 15.0

# The code fingerprint is a stat walk, not a subprocess, so it can be refreshed far more often.
_CODE_CACHE: Dict[str, Any] = {"fp": None, "at": 0.0}
_CODE_TTL_S = 5.0


def code_fingerprint(repo_dir: Optional[str] = None) -> str:
    """Fingerprint the executable code on disk — committed or not.

    Uses (relative path, size, mtime) rather than file contents: this is recomputed on a short
    interval, and a stat walk over a few hundred files is cheap where hashing their contents is not.
    Returns "" when the tree cannot be read, which callers must treat as "unknown" — never as
    "changed", so an unreadable checkout cannot raise a false restart alarm.
    """
    try:
        root = Path(repo_dir or ".").resolve()
        digest = hashlib.sha256()
        seen = 0
        for rel in _CODE_ROOTS:
            target = root / rel
            if target.is_file():
                paths = [target]
            elif target.is_dir():
                paths = sorted(p for p in target.rglob("*.py") if "__pycache__" not in p.parts)
            else:
                continue
            for path in paths:
                stat = path.stat()
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(f"{stat.st_size}:{stat.st_mtime_ns}".encode("ascii"))
                seen += 1
        # No code found at all means we are not looking at a checkout (wrong cwd, unmounted drive).
        # Returning the digest of nothing would differ from the frozen baseline and raise a restart
        # alarm for a tree we simply cannot see, so report "unknown" instead.
        return digest.hexdigest()[:16] if seen else ""
    except OSError:
        return ""


def _local_code_changes(repo_dir: Optional[str] = None) -> Optional[bool]:
    """Does the checkout carry uncommitted changes to executable code? None when git cannot say."""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", *_CODE_ROOTS],
                             cwd=repo_dir, capture_output=True, text=True, timeout=5)
        if out.returncode == 0:
            return bool((out.stdout or "").strip())
    except Exception:
        pass
    return None


def freeze_running_identity(repo_dir: Optional[str] = None) -> Dict[str, Any]:
    """Eagerly capture the immutable running identity at process start (idempotent).

    Call this from the server bootstrap so ``running_sha``/``started_at`` reflect the commit and time
    the process actually began serving — never whenever this module first happened to be imported.
    Captures exactly once; later calls return the already-frozen values unchanged."""
    if _RUNNING["sha"] is None:
        _RUNNING["sha"] = _git_head(repo_dir)
        _RUNNING["started_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        # Both are captured HERE, at the same instant as the SHA: the fingerprint is the baseline a
        # later edit is compared against, and the dirty flag is what keeps the reported build honest
        # for a process that started from a working tree rather than a clean commit.
        _RUNNING["code"] = code_fingerprint(repo_dir)
        _RUNNING["dirty"] = _local_code_changes(repo_dir)
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
                     started_at: str, running_code: str = "", current_code: str = "",
                     local_changes_at_start: Optional[bool] = None) -> Dict[str, Any]:
    """Pure, testable core: shape the identity dict and derive the restart flags.

    ``stale`` is True ONLY when both SHAs are known and differ — an unknown HEAD (no git) must never
    raise a false alarm. ``code_changed`` applies the same rule to the fingerprint, so it catches the
    case a SHA cannot see at all: an uncommitted edit to executable code. ``restart_required`` is the
    one an operator should read; it is either.

    ``running_build`` is the honest name of what this process serves. A process started from a dirty
    tree is NOT the commit it started from, so it is reported as ``<sha> + local changes`` — never as
    a clean commit. SHAs are truncated to 12 chars for display; they are not secrets."""
    running = (running_sha or "").strip()
    head = (head_sha or "").strip()
    stale = bool(running and head and running != head)
    code_changed = bool(running_code and current_code and running_code != current_code)
    restart_required = stale or code_changed
    build = running[:12] or "unknown"
    if local_changes_at_start:
        build += _LOCAL_SUFFIX
    return {
        "product_version": product_version,
        "running_sha": running[:12],
        "head_sha": head[:12] if head else "",
        "running_build": build,
        "local_changes_at_start": local_changes_at_start,
        "process_started_at": started_at,
        "stale": stale,
        "code_changed": code_changed,
        "restart_required": restart_required,
        "warning": _STALE_WARNING if restart_required else "",
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
    code_now = _CODE_CACHE["fp"]
    if code_now is None or (now - _CODE_CACHE["at"]) >= _CODE_TTL_S:
        code_now = code_fingerprint(repo_dir)
        _CODE_CACHE["fp"] = code_now
        _CODE_CACHE["at"] = now
    # Read the freshness fields defensively: a caller (or a test) may inject a running identity that
    # predates them, and a missing baseline must read as "unknown" rather than blow up or alarm.
    return compute_identity(running_sha=run["sha"], head_sha=cached,
                            product_version=_product_version(), started_at=run["started_at"],
                            running_code=run.get("code") or "", current_code=code_now,
                            local_changes_at_start=run.get("dirty"))

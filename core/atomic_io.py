"""Replacing a file on Windows, where another reader can make that fail for a moment.

``os.replace`` is the last step of every atomic write in this codebase: content goes to a temp file,
then one rename makes it visible. On POSIX that rename cannot fail because something is reading the
destination. On Windows it can — the Dashboard polling a run's state while the engine saves it is
enough — and it surfaces as ``PermissionError [WinError 5]``. One live discovery run has already
died that way, losing a state write that had nothing wrong with it.

The fix is a short retry, and the discipline is in what is NOT retried. A missing source, a path
that is a directory, a genuinely read-only destination: those fail the same way on the fifth attempt
as on the first, and retrying them turns an immediate, clear error into a slow, confusing one. Only
the sharing-violation family is transient, and only while the temp file still exists.

When the attempts run out the ORIGINAL error is raised, with context added rather than replaced —
the winerror a reader will search for must survive. The temp file is removed on the way out: the
destination still holds the last good content, so the abandoned copy is an orphan, not a backup.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Union

# Windows error codes worth waiting out. 5 is ACCESS_DENIED, which a concurrent reader produces;
# 32 and 33 are the explicit sharing/lock violations.
_TRANSIENT_WINERRORS = frozenset({5, 32, 33})
_ATTEMPTS = 5
_BASE_DELAY_S = 0.02
_MAX_DELAY_S = 0.2


def _is_transient(exc: OSError, tmp: Path, path: Path) -> bool:
    """Is this failure worth another attempt in a few milliseconds?

    Only when the operation could still succeed unchanged: the source must still be there, the
    destination must not be a directory, and the platform must have named a contention error.
    """
    if not isinstance(exc, PermissionError):
        return False
    if not tmp.exists() or path.is_dir():
        return False
    winerror = getattr(exc, "winerror", None)
    if winerror is None:              # POSIX: a permission error here is a real permission error
        return False
    return winerror in _TRANSIENT_WINERRORS


def atomic_replace(tmp: Union[str, Path], path: Union[str, Path], *,
                   attempts: int = _ATTEMPTS) -> None:
    """``os.replace`` with a bounded retry for transient Windows contention.

    Performs the replace exactly once on success — a retry re-attempts the SAME rename and never
    re-runs whatever produced the content, so nothing is written or recorded twice.
    """
    source, target = Path(tmp), Path(path)
    delay = _BASE_DELAY_S
    for attempt in range(1, max(1, attempts) + 1):
        try:
            os.replace(source, target)
            return
        except OSError as exc:
            if attempt >= attempts or not _is_transient(exc, source, target):
                _discard(source, keep=isinstance(exc, FileNotFoundError))
                raise _with_context(exc, attempt, attempts)
            time.sleep(delay)
            delay = min(delay * 2, _MAX_DELAY_S)


def _discard(source: Path, *, keep: bool) -> None:
    """Remove the temp copy the destination never took. ``keep`` when the source is what went
    missing — there is then nothing to remove and nothing to lose."""
    if keep:
        return
    try:
        source.unlink(missing_ok=True)
    except OSError:
        pass          # an undeletable temp file must not replace the error the caller needs to see


def _with_context(exc: OSError, attempt: int, attempts: int) -> OSError:
    """Return the SAME error, with the retry history appended to its message.

    Deliberately not a new exception type: callers and logs match on ``PermissionError`` and on the
    winerror, and wrapping the failure would hide exactly what a reader is looking for.
    """
    detail = (f"{exc.strerror or exc}" if attempt == 1 else
              f"{exc.strerror or exc} (still failing after {attempts} attempts)")
    exc.strerror = detail
    return exc

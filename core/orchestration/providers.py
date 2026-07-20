"""Deterministic clock and id providers — Phase 8.1.

Injecting these into the planning workflow makes runs reproducible: with a fixed
clock and id sequence, the same input yields byte-identical artifacts. Production
runs use the real providers (wall clock + uuid4).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from uuid import uuid4


class ClockProvider:
    """Wall-clock provider (real time)."""

    def now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()


class IdProvider:
    """Random id provider (uuid4)."""

    def new_id(self) -> str:
        return str(uuid4())

    def short_id(self) -> str:
        return uuid4().hex[:8]


def slugify(text: str, max_len: int = 32) -> str:
    """Deterministic, path-safe slug from free text (project-id safe charset)."""
    slug = re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")
    slug = slug[:max_len].strip("-")
    return slug or "work"


def generate_project_id(seed_text: str, ids: "IdProvider", prefix: str = "") -> str:
    """Build a safe, readable project id: '<slug>-<short-id>'.

    `prefix` (e.g. an inferred profile) takes precedence over the brief text for the
    slug. Uses the injected id provider so tests are deterministic.
    """
    base = prefix if prefix else " ".join((seed_text or "").split()[:6])
    return f"{slugify(base)}-{ids.short_id()}"


# One public project-id contract, reused by the CLI and the Dashboard (no separate rules). The
# rules are OS-INDEPENDENT (they do not consult the current platform) so a candidate accepted on
# Linux is equally safe on Windows and vice-versa.
_PROJECT_ID_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
# Windows reserved device basenames (rejected case-insensitively, with or without an extension).
_WINDOWS_RESERVED = frozenset(
    {"CON", "PRN", "AUX", "NUL", "CLOCK$"}
    | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)})


def validate_project_id(pid: str) -> bool:
    """A safe project id: ``[A-Za-z0-9._-]{1,64}`` that cannot escape the output root on any OS.

    Rejects: empty; disallowed characters (which excludes spaces, ``/``, ``\\``, ``:``, control
    chars); ``.`` / ``..`` / any double-dot; leading or trailing dot or space; and Windows reserved
    device names (CON, PRN, AUX, NUL, CLOCK$, COM1-9, LPT1-9), including with an extension.
    """
    if not pid or _PROJECT_ID_RE.fullmatch(pid) is None:
        return False
    if ".." in pid or pid in (".", ".."):
        return False
    if pid.startswith(".") or pid.endswith(".") or pid.startswith(" ") or pid.endswith(" "):
        return False
    if "/" in pid or "\\" in pid or ":" in pid:      # explicit separator/drive guard (OS-independent)
        return False
    if any(ord(c) < 0x20 or ord(c) == 0x7F for c in pid):
        return False
    stem = pid.split(".", 1)[0].strip().upper()
    if stem in _WINDOWS_RESERVED or pid.strip().upper() in _WINDOWS_RESERVED:
        return False
    return True


class FixedClock(ClockProvider):
    """Deterministic clock returning a fixed ISO timestamp."""

    def __init__(self, iso: str = "2026-01-01T00:00:00+00:00") -> None:
        self._iso = iso

    def now_iso(self) -> str:
        return self._iso


class SequentialIds(IdProvider):
    """Deterministic id provider returning prefix-000, prefix-001, ..."""

    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._n = 0

    def new_id(self) -> str:
        val = f"{self._prefix}-{self._n:04d}"
        self._n += 1
        return val

    def short_id(self) -> str:
        val = f"{self._n:04d}"
        self._n += 1
        return val

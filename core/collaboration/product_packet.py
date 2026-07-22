"""Persisted product-work packets for the session-independent writer loop (Issue #17).

A *packet* is one bounded product task (objective, acceptance, safety boundary, next action) persisted
under the SAME ``_review_relay`` base the Direct Driver already uses — there is no second state store.
The task-managed supervisor picks the next pending packet and launches a bounded Claude writer on it;
because the packet + its status live on disk, a fresh session (after a quota reset or a restart) resumes
exactly where the last one stopped, and an in-progress claim prevents a duplicate launch.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

_STATUSES = {"pending", "in_progress", "done", "failed", "needs_owner"}
_SAFE_ID = re.compile(r"^pkt-[0-9A-Za-z._-]{6,80}$")

# A claim lease must exceed the bounded writer's own timeout (default 1800s) so a genuinely-running
# writer is never mistaken for an orphan; a claim older than this is a dead process and is recovered.
DEFAULT_LEASE_SECONDS = 2700


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _now_dt(now: Optional[datetime] = None) -> datetime:
    return now if now is not None else datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _parse_iso(value: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(value)) if value else None
    except (TypeError, ValueError):
        return None


class ProductPacketError(ValueError):
    """Raised for an invalid or conflicting product-packet operation."""


class ProductPacketStore:
    """Append/update store of bounded product packets under the shared _review_relay base."""

    def __init__(self, output_root: str = "outputs") -> None:
        self._output_root = str(output_root)
        self._dir = Path(output_root) / "_review_relay" / "product_packets"
        self._dir.mkdir(parents=True, exist_ok=True)

    @property
    def output_root(self) -> str:
        """The base output root (parent of ``_review_relay``) — lets callers reach the sibling
        collaboration store that holds a packet's protocol evidence (Issue #17 P0-1)."""
        return self._output_root

    def create(self, *, objective: str, acceptance: str = "", safety: str = "",
               next_action: str = "", area: str = "scout_dashboard") -> Dict[str, Any]:
        if not str(objective).strip():
            raise ProductPacketError("objective is required")
        pid = f"pkt-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        record = {"packet_id": pid, "objective": str(objective).strip(),
                  "acceptance": str(acceptance).strip(), "safety": str(safety).strip(),
                  "next_action": str(next_action).strip() or str(objective).strip(),
                  "area": str(area), "status": "pending", "attempts": 0,
                  "created_at": _now(), "updated_at": _now(), "branch": "", "pr_number": None,
                  "last_result": "",
                  # Issue #17 P0-1: canonical protocol phase, advanced only from persisted evidence.
                  "phase": "new",
                  # Issue #17 P0-2: claim attribution + lease (empty until claimed).
                  "claim_owner": "", "claimed_at": "", "lease_expires_at": "", "heartbeat_at": "",
                  # Issue #17 P0-3: durable backoff gate (empty = immediately eligible).
                  "next_retry_at": "",
                  # Writer isolation (owner/GPT requirement): the writer runs in this dedicated worktree
                  # / branch off base_sha, never the controller worktree (empty = controller workspace).
                  "workspace_path": "", "base_sha": "",
                  # Conservative bounds for a live run: per-packet launch cap + total spend cap + the
                  # accumulated real writer cost, all surfaced in /collab (0 = use module default).
                  "max_launches": 0, "max_total_usd": 0.0, "spent_usd": 0.0,
                  # Per-packet claim lease (0 = DEFAULT_LEASE_SECONDS). A short lease makes a killed
                  # writer's orphaned claim reclaimable quickly (observable kill/resume recovery).
                  "lease_seconds": 0}
        self._write(pid, record)
        return record

    def get(self, packet_id: str) -> Optional[Dict[str, Any]]:
        pid = self._validate(packet_id)
        path = self._dir / f"{pid}.json"
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return data if isinstance(data, dict) else None

    def list(self) -> List[Dict[str, Any]]:
        rows = []
        for path in self._dir.glob("pkt-*.json"):
            try:
                rows.append(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        rows.sort(key=lambda r: (r.get("created_at", ""), r.get("packet_id", "")))
        return rows

    def next_pending(self, *, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """The next pending packet that is eligible right now. A packet whose ``next_retry_at`` is still
        in the future is backing off (P0-3) and is skipped, so the caller does a free no-op instead of
        relaunching Claude every interval."""
        dt = _now_dt(now)
        for row in self.list():
            if row.get("status") != "pending":
                continue
            retry_at = _parse_iso(row.get("next_retry_at", ""))
            if retry_at is not None and retry_at > dt:
                continue                                       # backing off -> not yet eligible
            return row
        return None

    def claim(self, packet_id: str, *, owner: str = "",
              lease_seconds: int = DEFAULT_LEASE_SECONDS,
              now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """Atomically move a packet pending -> in_progress so only one writer is ever launched for it.
        Records an attributable, time-bounded claim (owner + lease) so a crashed writer can be recovered
        (P0-2). Returns the claimed record, or None if it was not pending (already claimed/finished)."""
        pid = self._validate(packet_id)
        # Atomic claim marker: the first caller to create it wins; a concurrent caller is refused.
        marker = self._dir / f"{pid}.claim"
        try:
            fd = os.open(str(marker), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except FileExistsError:
            return None
        record = self.get(pid)
        if not record or record.get("status") != "pending":
            return None
        dt = _now_dt(now)
        record.update(status="in_progress", attempts=int(record.get("attempts", 0)) + 1,
                      claim_owner=str(owner), claimed_at=_iso(dt), heartbeat_at=_iso(dt),
                      lease_expires_at=_iso(dt + timedelta(seconds=int(lease_seconds))),
                      updated_at=_iso(dt))
        self._write(pid, record)
        return record

    def heartbeat(self, packet_id: str, *, lease_seconds: int = DEFAULT_LEASE_SECONDS,
                  now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        """Extend a live claim's lease (P0-2). A long-running writer refreshes its lease so recovery
        never reclaims it while genuinely alive. No-op for a packet that is not in progress."""
        pid = self._validate(packet_id)
        record = self.get(pid)
        if not record or record.get("status") != "in_progress":
            return None
        dt = _now_dt(now)
        record.update(heartbeat_at=_iso(dt),
                      lease_expires_at=_iso(dt + timedelta(seconds=int(lease_seconds))),
                      updated_at=_iso(dt))
        self._write(pid, record)
        return record

    def recover_orphaned_claims(self, *, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Reset any in-progress packet whose lease has expired back to pending (P0-2).

        The lease is longer than the writer's own timeout, so a genuinely-running writer is never
        reclaimed; only a claim left behind by a dead process/session/machine is recovered. Recovery is
        resumable — the writer_session is preserved — and clears the stale ``.claim`` marker so a fresh
        cycle can re-claim without launching a duplicate. Returns the recovered records.
        """
        dt = _now_dt(now)
        recovered: List[Dict[str, Any]] = []
        for row in self.list():
            if row.get("status") != "in_progress":
                continue
            expires = _parse_iso(row.get("lease_expires_at", ""))
            if expires is None or expires >= dt:
                continue                                       # no lease or still valid -> live writer
            rec = self.update(row["packet_id"], status="pending",
                              last_result="recovered orphaned claim (lease expired)")
            recovered.append(rec)
        return recovered

    def update(self, packet_id: str, **changes: Any) -> Dict[str, Any]:
        pid = self._validate(packet_id)
        record = self.get(pid)
        if record is None:
            raise ProductPacketError("packet not found")
        status = changes.get("status")
        if status is not None and status not in _STATUSES:
            raise ProductPacketError(f"invalid status: {status}")
        record.update(changes)
        record["updated_at"] = _now()
        # Releasing back to pending (retry) clears the claim so a later cycle can re-claim it.
        if record.get("status") == "pending":
            (self._dir / f"{pid}.claim").unlink(missing_ok=True)
        self._write(pid, record)
        return record

    @staticmethod
    def _validate(packet_id: str) -> str:
        pid = str(packet_id or "").strip()
        if not _SAFE_ID.fullmatch(pid):
            raise ProductPacketError("invalid packet_id")
        return pid

    def _write(self, pid: str, record: Dict[str, Any]) -> None:
        tmp = self._dir / f"{pid}.json.tmp"
        tmp.write_text(json.dumps(record, ensure_ascii=False, sort_keys=True, indent=2),
                       encoding="utf-8")
        tmp.replace(self._dir / f"{pid}.json")

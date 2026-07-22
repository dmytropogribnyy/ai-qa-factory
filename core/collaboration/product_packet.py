"""Persisted product-work packets for the session-independent writer loop (Issue #17).

A *packet* is one bounded product task (objective, acceptance, safety boundary, next action) persisted
under the SAME ``_review_relay`` base the Direct Driver already uses — there is no second state store.
The task-managed supervisor picks the next pending packet and launches a bounded Claude writer on it;
because the packet + its status live on disk, a fresh session (after a quota reset or a restart) resumes
exactly where the last one stopped, and an in-progress claim prevents a duplicate launch.

P0-A single-writer fencing (Issue #17, GPT comments 5045114314 / 5045130846): an expired lease is NOT
evidence a writer is dead. A claim carries a unique ``claim_token`` plus its owner ``host`` + ``pids``;
a live relaunch heartbeat renews the lease while the writer runs (see ``relaunch.py``), every
heartbeat/terminal update is gated on the CURRENT ``claim_token`` (a stale owner or a reused PID becomes
a no-op), and recovery reclaims only when the lease is expired AND the owner process tree is provably
dead on this host — otherwise it fails closed to a visible ``blocked`` state, never a time-only reclaim.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

from core.collaboration.process_liveness import local_host, owner_liveness

_STATUSES = {"pending", "in_progress", "done", "failed", "needs_owner", "blocked",
             "stopped", "cancelled"}
_SAFE_ID = re.compile(r"^pkt-[0-9A-Za-z._-]{6,80}$")

# A claim lease must exceed the bounded writer's own timeout (default 1800s) so a genuinely-running
# writer is never mistaken for an orphan; a claim older than this WITH a dead owner is recovered. A
# shorter lease is safe only because the relaunch heartbeat renews it while the writer is alive.
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


def _default_owner_alive(record: Dict[str, Any]) -> Optional[bool]:
    """Real process-tree liveness for a claim owner (injectable in tests). True=alive, False=dead,
    None=unknown → the caller fails closed to ``blocked``."""
    return owner_liveness(owner_host=record.get("owner_host", ""),
                          owner_pids=record.get("owner_pids", []))


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
                  # Issue #17 P0-2/P0-A: claim attribution + lease + fencing identity (empty until claimed).
                  "claim_owner": "", "claimed_at": "", "lease_expires_at": "", "heartbeat_at": "",
                  "claim_token": "", "owner_host": "", "owner_pids": [],
                  # Issue #17 P0-3: durable backoff gate (empty = immediately eligible).
                  "next_retry_at": "",
                  # Writer isolation (owner/GPT requirement): the writer runs in this dedicated worktree
                  # / branch off base_sha, never the controller worktree (empty = controller workspace).
                  "workspace_path": "", "base_sha": "",
                  # Conservative bounds for a live run: per-packet launch cap + REAL-dollar spend cap +
                  # honest billing split (subscription token-equivalent usage vs actually-charged API $).
                  "max_launches": 0, "max_total_usd": 0.0,
                  "usage_usd_equiv": 0.0, "actual_charged_usd": 0.0, "billing_source": "",
                  # Per-packet claim lease (0 = DEFAULT_LEASE_SECONDS). Kept fresh by the relaunch
                  # heartbeat; a short lease is safe only with that heartbeat active.
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
              lease_seconds: int = DEFAULT_LEASE_SECONDS, now: Optional[datetime] = None,
              owner_pids: Optional[List[int]] = None, owner_host: Optional[str] = None,
              claim_token: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Atomically move a packet pending -> in_progress so only one writer is ever launched for it.
        Records an attributable, time-bounded, fenced claim: owner id + a unique ``claim_token`` + the
        owner ``host`` and ``pids`` so a crashed writer can be recovered only when it is provably dead
        (P0-A). Returns the claimed record, or None if it was not pending (already claimed/finished)."""
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
        pids = [int(p) for p in (owner_pids or []) if str(p).strip().lstrip("-").isdigit()]
        record.update(status="in_progress", attempts=int(record.get("attempts", 0)) + 1,
                      claim_owner=str(owner), claim_token=str(claim_token or uuid4().hex),
                      owner_host=(local_host() if owner_host is None else str(owner_host)),
                      owner_pids=pids, claimed_at=_iso(dt), heartbeat_at=_iso(dt),
                      lease_expires_at=_iso(dt + timedelta(seconds=int(lease_seconds))),
                      updated_at=_iso(dt))
        self._write(pid, record)
        return record

    def heartbeat(self, packet_id: str, *, claim_token: str = "",
                  lease_seconds: int = DEFAULT_LEASE_SECONDS, now: Optional[datetime] = None,
                  owner_pids: Optional[List[int]] = None) -> Optional[Dict[str, Any]]:
        """Extend a live claim's lease while the writer genuinely runs (P0-A). Token-gated: a stale
        heartbeat thread or a reused PID whose ``claim_token`` no longer matches the current claim is a
        NO-OP (cannot renew or mutate a newer claim). No-op for a packet that is not in progress."""
        pid = self._validate(packet_id)
        record = self.get(pid)
        if not record or record.get("status") != "in_progress":
            return None
        # Unconditional token gate: once a claim has a token, ONLY that exact token may renew it. A
        # missing/empty or mismatched token (a stale heartbeat thread or a reused PID) is a no-op.
        if record.get("claim_token") and claim_token != record.get("claim_token"):
            return None
        dt = _now_dt(now)
        changes: Dict[str, Any] = {
            "heartbeat_at": _iso(dt),
            "lease_expires_at": _iso(dt + timedelta(seconds=int(lease_seconds))),
            "updated_at": _iso(dt)}
        if owner_pids is not None:
            changes["owner_pids"] = [int(p) for p in owner_pids
                                     if str(p).strip().lstrip("-").isdigit()]
        record.update(changes)
        self._write(pid, record)
        return record

    def resolve(self, packet_id: str, *, claim_token: str = "", **changes: Any) -> Optional[Dict[str, Any]]:
        """Token-gated terminal update by the CLAIM OWNER (release/complete). If a newer claim now owns
        the packet (``claim_token`` mismatch), this is a no-op returning None, so a late/stale relaunch
        can never clobber a fresh claim's state (P0-A)."""
        pid = self._validate(packet_id)
        record = self.get(pid)
        if record is None:
            return None
        # Unconditional token gate (see heartbeat): a missing/empty or mismatched token is a no-op, so a
        # late/stale relaunch can never clobber a fresh claim's state.
        if record.get("claim_token") and claim_token != record.get("claim_token"):
            return None
        return self.update(pid, **changes)

    def recover_orphaned_claims(
            self, *, now: Optional[datetime] = None,
            is_owner_alive: Optional[Callable[[Dict[str, Any]], Optional[bool]]] = None
    ) -> List[Dict[str, Any]]:
        """Reclaim an in-progress packet ONLY when its lease is expired AND its owner process tree is
        provably dead on this host (P0-A). A live owner is never reclaimed (no double writer); an
        unknowable owner (different/empty host) fails CLOSED to a visible ``blocked`` state rather than a
        time-only reclaim that could split-brain. Recovery is resumable (``writer_session`` preserved)
        and clears the stale ``.claim`` marker. Returns the records reclaimed to pending.
        """
        dt = _now_dt(now)
        alive_fn = is_owner_alive or _default_owner_alive
        recovered: List[Dict[str, Any]] = []
        for row in self.list():
            if row.get("status") != "in_progress":
                continue
            expires = _parse_iso(row.get("lease_expires_at", ""))
            if expires is None or expires >= dt:
                continue                                       # no lease or still valid -> live writer
            alive = alive_fn(row)
            if alive is True:
                continue                                       # provably alive -> never reclaim
            if alive is None:
                # Fail closed: liveness unknowable here. Make it owner-visible; do NOT time-reclaim.
                if row.get("status") != "blocked":
                    self.update(row["packet_id"], status="blocked",
                                last_result="fenced: owner liveness unknown (host mismatch); "
                                            "expired lease is not proof of death — needs owner")
                continue
            rec = self.update(row["packet_id"], status="pending",
                              last_result="recovered orphaned claim (lease expired + owner tree dead)")
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

"""Durable local job queue (Final Phase I).

A SQLite-backed queue for the pipeline's internal work (discovery, triage, deep QA,
verification, recheck, review, disclosure prep, draft review, retention, backup). It provides
leased claiming (no duplicate execution after restart), retry ceilings with backoff, a
dead-letter state, lease reclamation (a crashed worker's job returns to PENDING rather than
staying falsely LEASED forever), heartbeats, and pause/resume/global-kill/per-queue-stop.
There is **no external-communication worker** — nothing here sends anything.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from core.scout.memory.db import MemoryDB

# Job states.
PENDING, LEASED, DONE, DEAD_LETTER, KILLED = "PENDING", "LEASED", "DONE", "DEAD_LETTER", "KILLED"

# Queues that may exist. No queue performs external communication in Final Phase I.
QUEUES = frozenset({
    "discovery", "triage", "deep_qa", "verification", "recheck", "company_identity_review",
    "contact_review", "manual_action", "disclosure_prep", "draft_review", "retention", "backup",
})


def _now() -> datetime:
    return datetime.now(timezone.utc)


class QueueControl:
    """Persisted pause/resume/kill controls (global + per-queue)."""

    def __init__(self, db: MemoryDB) -> None:
        self.db = db
        db.execute("CREATE TABLE IF NOT EXISTS queue_controls "
                   "(scope TEXT PRIMARY KEY, state TEXT NOT NULL)")

    def _set(self, scope: str, state: str) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT INTO queue_controls (scope, state) VALUES (?,?) "
                      "ON CONFLICT(scope) DO UPDATE SET state=excluded.state", (scope, state))

    def _get(self, scope: str) -> str:
        rows = self.db.query("SELECT state FROM queue_controls WHERE scope=?", (scope,))
        return rows[0]["state"] if rows else "RUNNING"

    def pause(self, queue: Optional[str] = None) -> None:
        self._set(queue or "__global__", "PAUSED")

    def resume(self, queue: Optional[str] = None) -> None:
        self._set(queue or "__global__", "RUNNING")

    def kill(self) -> None:
        self._set("__global__", "KILLED")

    def is_killed(self) -> bool:
        return self._get("__global__") == "KILLED"

    def is_paused(self, queue: str) -> bool:
        return (self._get("__global__") == "PAUSED"
                or self._get(queue) == "PAUSED"
                or self.is_killed())


class JobQueue:
    def __init__(self, db: MemoryDB, clock: Callable[[], datetime] = _now) -> None:
        self.db = db
        self.clock = clock
        self.control = QueueControl(db)

    def enqueue(self, queue: str, payload: Dict[str, Any], *, job_id: Optional[str] = None,
                max_attempts: int = 3) -> str:
        if queue not in QUEUES:
            raise ValueError(f"unknown queue: {queue!r}")
        now = self.clock().isoformat()
        jid = job_id or f"job-{queue}-{self._next_seq()}"
        with self.db.transaction() as c:
            # Idempotent: a job id already present is not re-enqueued.
            c.execute("INSERT OR IGNORE INTO jobs (job_id, queue, payload, state, attempts, "
                      "max_attempts, created_at, updated_at) VALUES (?,?,?, 'PENDING', 0, ?, ?, ?)",
                      (jid, queue, json.dumps(payload), max_attempts, now, now))
        return jid

    def _next_seq(self) -> int:
        row = self.db.query("SELECT COUNT(*) AS n FROM jobs")[0]
        return int(row["n"]) + 1

    def claim(self, worker: str, queue: str, *, lease_s: int = 60) -> Optional[Dict[str, Any]]:
        """Atomically lease the oldest claimable job for a queue (None if paused/killed/empty)."""
        if self.control.is_paused(queue) or self.control.is_killed():
            return None
        now = self.clock()
        with self.db.transaction() as c:
            self._reclaim(c, now)
            rows = c.execute(
                "SELECT job_id FROM jobs WHERE queue=? AND state='PENDING' "
                "ORDER BY created_at, job_id LIMIT 1", (queue,)).fetchall()
            if not rows:
                return None
            jid = rows[0]["job_id"]
            expires = (now + timedelta(seconds=lease_s)).isoformat()
            c.execute("UPDATE jobs SET state='LEASED', lease_owner=?, lease_expires_at=?, "
                      "attempts=attempts+1, updated_at=? WHERE job_id=? AND state='PENDING'",
                      (worker, expires, now.isoformat(), jid))
        job = self.db.query("SELECT * FROM jobs WHERE job_id=?", (jid,))[0]
        return {**dict(job), "payload": json.loads(job["payload"])}

    def heartbeat(self, job_id: str, worker: str, *, lease_s: int = 60) -> bool:
        now = self.clock()
        expires = (now + timedelta(seconds=lease_s)).isoformat()
        with self.db.transaction() as c:
            cur = c.execute("UPDATE jobs SET lease_expires_at=?, updated_at=? "
                            "WHERE job_id=? AND state='LEASED' AND lease_owner=?",
                            (expires, now.isoformat(), job_id, worker))
        return cur.rowcount == 1

    def complete(self, job_id: str) -> None:
        with self.db.transaction() as c:
            c.execute("UPDATE jobs SET state='DONE', updated_at=? WHERE job_id=?",
                      (self.clock().isoformat(), job_id))

    def fail(self, job_id: str, error: str) -> str:
        """Fail a job: retry (back to PENDING) until the ceiling, then DEAD_LETTER."""
        row = self.db.query("SELECT attempts, max_attempts FROM jobs WHERE job_id=?", (job_id,))
        if not row:
            return "unknown"
        attempts, max_attempts = row[0]["attempts"], row[0]["max_attempts"]
        new_state = DEAD_LETTER if attempts >= max_attempts else PENDING
        with self.db.transaction() as c:
            c.execute("UPDATE jobs SET state=?, last_error=?, lease_owner='', lease_expires_at='', "
                      "updated_at=? WHERE job_id=?",
                      (new_state, error[:400], self.clock().isoformat(), job_id))
        return new_state

    def _reclaim(self, c, now: datetime) -> None:
        """Return LEASED jobs whose lease expired to PENDING (crash recovery)."""
        c.execute("UPDATE jobs SET state='PENDING', lease_owner='', lease_expires_at='', "
                  "updated_at=? WHERE state='LEASED' AND lease_expires_at != '' "
                  "AND lease_expires_at < ?", (now.isoformat(), now.isoformat()))

    def reclaim_expired(self) -> int:
        now = self.clock()
        with self.db.transaction() as c:
            cur = c.execute("UPDATE jobs SET state='PENDING', lease_owner='', lease_expires_at='', "
                            "updated_at=? WHERE state='LEASED' AND lease_expires_at != '' "
                            "AND lease_expires_at < ?", (now.isoformat(), now.isoformat()))
        return cur.rowcount

    def drain(self, queue: str, handler: Callable[[Dict[str, Any]], None], *, worker: str = "w1",
              max_jobs: int = 1000) -> Dict[str, int]:
        """Deterministically process claimable jobs in a queue (single worker). Failing handlers
        retry/dead-letter; nothing is lost or left falsely LEASED."""
        done = failed = dead = 0
        for _ in range(max_jobs):
            job = self.claim(worker, queue)
            if job is None:
                break
            try:
                handler(job["payload"])
                self.complete(job["job_id"])
                done += 1
            except Exception as exc:  # a handler failure never loses the job
                state = self.fail(job["job_id"], f"{type(exc).__name__}: {exc}")
                failed += 1
                dead += 1 if state == DEAD_LETTER else 0
        return {"done": done, "failed": failed, "dead_letter": dead}

    def stats(self, queue: Optional[str] = None) -> Dict[str, int]:
        where = "WHERE queue=?" if queue else ""
        params = (queue,) if queue else ()
        rows = self.db.query(f"SELECT state, COUNT(*) AS n FROM jobs {where} GROUP BY state", params)
        return {r["state"]: int(r["n"]) for r in rows}

    def list_jobs(self, queue: Optional[str] = None) -> List[Dict[str, Any]]:
        where = "WHERE queue=?" if queue else ""
        params = (queue,) if queue else ()
        return [dict(r) for r in self.db.query(f"SELECT * FROM jobs {where} ORDER BY created_at",
                                               params)]

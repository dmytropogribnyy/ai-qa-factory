"""Final Phase I — durable job queue + scheduler controls (deterministic)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.scout.memory.db import MemoryDB
from core.scout.scheduler.queue import DEAD_LETTER, JobQueue


class _Clock:
    def __init__(self):
        self.t = datetime(2026, 7, 17, 10, 0, 0, tzinfo=timezone.utc)

    def __call__(self):
        return self.t

    def advance(self, seconds):
        self.t = self.t + timedelta(seconds=seconds)


def _q(tmp_path):
    return JobQueue(MemoryDB(str(tmp_path / "jobs.db")), clock=_Clock())


def test_enqueue_is_idempotent_and_claim_leases(tmp_path):
    q = _q(tmp_path)
    q.enqueue("deep_qa", {"n": 1}, job_id="j1")
    q.enqueue("deep_qa", {"n": 1}, job_id="j1")  # idempotent
    assert len(q.list_jobs("deep_qa")) == 1
    job = q.claim("w1", "deep_qa")
    assert job["job_id"] == "j1" and job["state"] == "LEASED"
    assert q.claim("w2", "deep_qa") is None  # no duplicate claim while leased


def test_fail_retries_then_dead_letters(tmp_path):
    q = _q(tmp_path)
    q.enqueue("triage", {"x": 1}, job_id="j1", max_attempts=2)

    def _boom(_payload):
        raise RuntimeError("handler failed")

    result = q.drain("triage", _boom)
    assert result["dead_letter"] == 1
    assert q.stats("triage").get(DEAD_LETTER) == 1  # not lost, not stuck LEASED


def test_expired_lease_is_reclaimed_for_crash_recovery(tmp_path):
    clock = _Clock()
    q = JobQueue(MemoryDB(str(tmp_path / "jobs.db")), clock=clock)
    q.enqueue("recheck", {"a": 1}, job_id="j1")
    q.claim("crasher", "recheck", lease_s=1)     # worker leases then "crashes"
    assert q.claim("w2", "recheck") is None       # still leased -> not double-claimed
    clock.advance(5)
    assert q.reclaim_expired() == 1               # lease expired -> back to PENDING
    assert q.claim("w2", "recheck")["job_id"] == "j1"  # now reclaimable


def test_pause_resume_and_global_kill(tmp_path):
    q = _q(tmp_path)
    q.enqueue("deep_qa", {"a": 1}, job_id="j1")
    q.control.pause("deep_qa")
    assert q.claim("w1", "deep_qa") is None
    q.control.resume("deep_qa")
    assert q.claim("w1", "deep_qa") is not None
    q.enqueue("deep_qa", {"a": 2}, job_id="j2")
    q.control.kill()
    assert q.claim("w1", "deep_qa") is None and q.control.is_killed()


def test_restart_preserves_jobs(tmp_path):
    q = _q(tmp_path)
    q.enqueue("deep_qa", {"a": 1}, job_id="j1")
    q.enqueue("deep_qa", {"a": 2}, job_id="j2")
    q.claim("w1", "deep_qa")
    q.db.close()
    q2 = JobQueue(MemoryDB(str(tmp_path / "jobs.db")), clock=_Clock())
    assert len(q2.list_jobs("deep_qa")) == 2  # durable across restart


def test_drain_processes_all_and_reports(tmp_path):
    q = _q(tmp_path)
    for i in range(4):
        q.enqueue("verification", {"i": i}, job_id=f"j{i}")
    seen = []
    result = q.drain("verification", lambda p: seen.append(p["i"]))
    assert result["done"] == 4 and sorted(seen) == [0, 1, 2, 3]

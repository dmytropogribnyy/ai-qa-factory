"""Final Phase II — comms repository state machine (deterministic)."""
from __future__ import annotations

from core.scout.comms.repository import CommsRepository
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-17T13:00:00+00:00"


def _setup(tmp_path):
    db = MemoryDB(str(tmp_path / "m.db"))
    mem = MemoryRepository(db)
    mem.upsert_campaign("camp", "Camp", _NOW)
    mem.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    return db, CommsRepository(db)


def _revision(repo, draft_id="d1"):
    rid = f"rev-{draft_id}-{repo.next_revision_number(draft_id)}"
    repo.create_revision({"revision_id": rid, "draft_id": draft_id,
                          "revision_number": repo.next_revision_number(draft_id),
                          "company_id": "co-1", "channel": "email", "subject": "Hi", "body": "B",
                          "body_hash": "sha256:b", "generated_at": _NOW})
    return rid


def _approve(repo, rid):
    aid = f"ap-{rid}"
    repo.create_approval({"approval_id": aid, "revision_id": rid, "recipient_hash": "r",
                          "body_hash": "sha256:b", "disclosure_hash": "d", "finding_hash": "f",
                          "evidence_hash": "e", "contact_provenance_hash": "cp", "suppression_hash": "s",
                          "channel": "email", "reviewer": "human", "approved_at": _NOW,
                          "reviewed_content_hash": "sha256:reviewed"})
    return aid


def test_approval_is_single_use(tmp_path):
    db, repo = _setup(tmp_path)
    aid = _approve(repo, _revision(repo))
    assert repo.consume_approval(aid) is True    # first consume succeeds
    assert repo.consume_approval(aid) is False   # replay fails (single-use)
    assert repo.get_approval(aid)["state"] == "CONSUMED"
    db.close()


def test_approval_cannot_bind_to_superseded_revision(tmp_path):
    db, repo = _setup(tmp_path)
    rid = _revision(repo)
    repo.supersede_revision(rid)
    from core.scout.comms.repository import CommsError
    import pytest
    with pytest.raises(CommsError):
        _approve(repo, rid)
    db.close()


def test_reservation_is_idempotent_per_key(tmp_path):
    db, repo = _setup(tmp_path)
    rid = _revision(repo)
    aid = _approve(repo, rid)
    msg = {"message_id": "m1", "revision_id": rid, "approval_id": aid, "company_id": "co-1",
           "channel": "email", "provider_id": "local_sink", "idempotency_key": "key-abc", "now": _NOW}
    mid1, created1 = repo.reserve_message(msg)
    mid2, created2 = repo.reserve_message({**msg, "message_id": "m2"})  # same key
    assert created1 is True and created2 is False and mid1 == mid2  # one reservation only
    assert repo.count("outbound_messages") == 1
    db.close()


def test_provider_event_dedup(tmp_path):
    db, repo = _setup(tmp_path)
    ev = {"event_id": "e1", "normalized_type": "DELIVERED", "received_ts": _NOW, "dedup_key": "dk1"}
    assert repo.add_provider_event(ev) is True
    assert repo.add_provider_event({**ev, "event_id": "e2"}) is False  # duplicate dedup_key
    assert repo.count("provider_events") == 1
    db.close()


def test_global_outreach_disabled_by_default(tmp_path):
    db, repo = _setup(tmp_path)
    assert repo.get_control("__global_outreach__") == "DISABLED"
    repo.set_control("__global_outreach__", "ENABLED")
    assert repo.get_control("__global_outreach__") == "ENABLED"
    db.close()

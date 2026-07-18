"""Final Independent Acceptance (v2.0.1) — enforced communication state machines (deterministic)."""
from __future__ import annotations

import pytest

from core.scout.comms.repository import CommsError, CommsRepository
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-17T20:00:00+00:00"


def _repo(tmp_path):
    db = MemoryDB(str(tmp_path / "m.db"))
    mem = MemoryRepository(db)
    mem.upsert_campaign("camp", "Camp", _NOW)
    mem.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    return CommsRepository(db)


def _reserved_message(repo):
    rid = f"rev-d1-{repo.next_revision_number('d1')}"
    repo.create_revision({"revision_id": rid, "draft_id": "d1", "revision_number": 1,
                          "company_id": "co-1", "channel": "email", "subject": "Hi", "body": "B",
                          "body_hash": "sha256:b", "generated_at": _NOW})
    aid = f"ap-{rid}"
    repo.create_approval({"approval_id": aid, "revision_id": rid, "recipient_hash": "r",
                          "body_hash": "sha256:b", "disclosure_hash": "d", "finding_hash": "f",
                          "evidence_hash": "e", "contact_provenance_hash": "cp", "suppression_hash": "s",
                          "channel": "email", "reviewer": "human", "approved_at": _NOW,
                          "reviewed_content_hash": "sha256:reviewed"})
    mid = "m1"
    repo.reserve_and_authorize({"message_id": mid, "revision_id": rid, "company_id": "co-1",
                                "channel": "email", "provider_id": "local_sink",
                                "idempotency_key": "key-1", "now": _NOW}, aid)
    return repo, rid, aid, mid


def test_invalid_message_transition_rejected(tmp_path):
    repo, rid, aid, mid = _reserved_message(_repo(tmp_path))
    with pytest.raises(CommsError):  # RESERVED -> ACCEPTED skips PROVIDER_CALL_IN_PROGRESS
        repo.transition_message(mid, "ACCEPTED", _NOW)


def test_unknown_message_state_rejected(tmp_path):
    repo, rid, aid, mid = _reserved_message(_repo(tmp_path))
    with pytest.raises(CommsError):
        repo.transition_message(mid, "BOGUS_STATE", _NOW)


def test_terminal_message_rewrite_rejected(tmp_path):
    repo, rid, aid, mid = _reserved_message(_repo(tmp_path))
    repo.transition_message(mid, "PROVIDER_CALL_IN_PROGRESS", _NOW)
    repo.transition_message(mid, "ACCEPTED", _NOW)
    with pytest.raises(CommsError):  # ACCEPTED -> RESERVED is not allowed (no terminal rewrite)
        repo.transition_message(mid, "RESERVED", _NOW)


def test_invalid_revision_transition_rejected(tmp_path):
    repo, rid, aid, mid = _reserved_message(_repo(tmp_path))  # revision is RESERVED_FOR_SEND
    with pytest.raises(CommsError):
        repo.transition_revision(rid, "APPROVED", _NOW)       # RESERVED_FOR_SEND -> APPROVED invalid
    with pytest.raises(CommsError):
        repo.transition_revision(rid, "BOGUS", _NOW)


def test_invalid_approval_transition_rejected(tmp_path):
    repo, rid, aid, mid = _reserved_message(_repo(tmp_path))  # approval is CONSUMED
    with pytest.raises(CommsError):
        repo.transition_approval(aid, "APPROVED", _NOW)       # CONSUMED -> APPROVED invalid


def test_valid_transitions_write_lifecycle_events(tmp_path):
    repo, rid, aid, mid = _reserved_message(_repo(tmp_path))
    repo.transition_message(mid, "PROVIDER_CALL_IN_PROGRESS", _NOW)
    repo.transition_message(mid, "ACCEPTED", _NOW)
    events = [e["event"] for e in repo.lifecycle_events("message", mid)]
    assert "RESERVED->PROVIDER_CALL_IN_PROGRESS" in events and "PROVIDER_CALL_IN_PROGRESS->ACCEPTED" in events
    # The reservation itself recorded approval-consumed + revision-reserved events.
    assert any(e["event"] == "->CONSUMED" for e in repo.lifecycle_events("approval", aid))

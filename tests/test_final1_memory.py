"""Final Phase I — transactional SQLite company/site memory (deterministic)."""
from __future__ import annotations

import sqlite3

import pytest

from core.scout.memory.db import (
    MemoryCorruptionError,
    MemoryDB,
    MigrationError,
    SCHEMA_VERSION,
)
from core.scout.memory.repository import CompanyConflict, MemoryRepository, SendBlocked

_NOW = "2026-07-17T09:00:00+00:00"


def _fresh(tmp_path, name="mem.db"):
    return MemoryDB(str(tmp_path / name))


def test_fresh_database_migrates_to_current_version(tmp_path):
    db = _fresh(tmp_path)
    assert db.current_version() == SCHEMA_VERSION
    assert db.integrity_ok()
    repo = MemoryRepository(db)
    assert repo.count("companies") == 0
    db.close()


def test_interrupted_migration_rolls_back(tmp_path):
    db = _fresh(tmp_path)
    # Version 2 is the real schema-v2 migration; use a higher fake version to prove rollback.
    with pytest.raises(MigrationError):
        db.migrate([(99, ["CREATE TABLE t2 (id INTEGER)", "THIS IS NOT VALID SQL"])])
    assert db.current_version() == SCHEMA_VERSION  # version unchanged
    with pytest.raises(sqlite3.OperationalError):
        db.query("SELECT * FROM t2")  # the partial migration was rolled back
    db.close()


def test_duplicate_domain_is_not_auto_merged(tmp_path):
    db = _fresh(tmp_path)
    repo = MemoryRepository(db)
    repo.upsert_campaign("camp", "Camp", _NOW)
    repo.upsert_company("co-a", "camp", "A", "a.example", _NOW)
    repo.upsert_company("co-b", "camp", "B", "b.example", _NOW)
    repo.add_domain("co-a", "shared.example")
    with pytest.raises(CompanyConflict):
        repo.add_domain("co-b", "shared.example")  # never auto-merged across companies
    db.close()


def test_restart_preserves_data(tmp_path):
    db = _fresh(tmp_path)
    repo = MemoryRepository(db)
    repo.upsert_campaign("camp", "Camp", _NOW)
    repo.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    db.close()
    db2 = _fresh(tmp_path)  # reopen the same file
    assert MemoryRepository(db2).count("companies") == 1
    db2.close()


def test_backup_and_restore_reproduces_truth(tmp_path):
    db = _fresh(tmp_path)
    repo = MemoryRepository(db)
    repo.upsert_campaign("camp", "Camp", _NOW)
    repo.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    backup = db.backup(str(tmp_path / "backups" / "mem.bak"))
    db.close()
    restored = MemoryDB.restore(backup, str(tmp_path / "restored.db"))
    assert MemoryRepository(restored).count("companies") == 1
    restored.close()


def test_corrupted_database_fails_closed(tmp_path):
    path = tmp_path / "bad.db"
    path.write_bytes(b"this is definitely not a valid sqlite database file" * 10)
    with pytest.raises(MemoryCorruptionError):
        MemoryDB(str(path))  # never silently falls back to an empty database


def test_draft_cannot_be_marked_sent(tmp_path):
    db = _fresh(tmp_path)
    repo = MemoryRepository(db)
    repo.upsert_campaign("camp", "Camp", _NOW)
    repo.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    repo.add_draft("d1", "co-1", "c1", "email", "sha256:x", _NOW, "2026-08-01T00:00:00+00:00")
    # The application forbids sending...
    with pytest.raises(SendBlocked):
        repo.mark_draft_sent("d1")
    # ...and the DB CHECK makes "sent" unrepresentable.
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE drafts SET sent=1 WHERE draft_id='d1'")
    db.close()


def test_contact_dedup_and_review_queue(tmp_path):
    db = _fresh(tmp_path)
    repo = MemoryRepository(db)
    repo.upsert_campaign("camp", "Camp", _NOW)
    repo.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    contact = {"contact_id": "k1", "company_id": "co-1", "channel": "email",
               "normalized_value": "hi@one.example", "status": "PUBLIC_OBSERVED"}
    repo.upsert_contact(contact)
    repo.upsert_contact({**contact, "contact_id": "k2", "status": "VERIFIED"})  # same value
    assert repo.count("contacts") == 1  # deduped by (company, channel, value)
    repo.add_review_item("r1", "contact_review", "k1", "co-1", _NOW)
    repo.decide_review_item("r1", "human", "approved", "public official contact", _NOW)
    row = repo.review_items("contact_review")[0]
    assert row["state"] == "DECIDED" and row["decision"] == "approved"
    db.close()

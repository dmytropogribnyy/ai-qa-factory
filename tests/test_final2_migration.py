"""Final Phase II — schema v1->v2 migration preserving v1.9.0 data (deterministic)."""
from __future__ import annotations

import sqlite3

from core.scout.memory.db import _MIGRATION_1, _MIGRATION_2, MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-17T13:00:00+00:00"


def _build_v2_db(path):
    """Create a genuine version-2 (v2.0.0) database with v2 comms data, as the old code would."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("BEGIN")
    for stmt in _MIGRATION_1 + _MIGRATION_2:
        conn.execute(stmt)
    conn.execute("CREATE TABLE schema_meta (id INTEGER PRIMARY KEY CHECK (id=1), version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_meta (id, version) VALUES (1, 2)")
    conn.execute("INSERT INTO campaigns (campaign_id, name, created_at, updated_at) VALUES (?,?,?,?)",
                 ("camp", "Camp", _NOW, _NOW))
    conn.execute("INSERT INTO companies (company_id, campaign_id, canonical_name, primary_domain, "
                 "first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?)",
                 ("co-1", "camp", "One", "one.example", _NOW, _NOW))
    conn.execute("INSERT INTO draft_revisions (revision_id, draft_id, revision_number, company_id, "
                 "channel, generated_at) VALUES (?,?,?,?,?,?)",
                 ("rev-1", "d1", 1, "co-1", "email", _NOW))
    conn.execute("COMMIT")
    conn.close()


def _build_v1_db(path):
    """Create a genuine version-1 (v1.9.0) database with one company, as the old code would."""
    conn = sqlite3.connect(str(path), isolation_level=None)
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("BEGIN")
    for stmt in _MIGRATION_1:
        conn.execute(stmt)
    conn.execute("CREATE TABLE schema_meta (id INTEGER PRIMARY KEY CHECK (id=1), version INTEGER NOT NULL)")
    conn.execute("INSERT INTO schema_meta (id, version) VALUES (1, 1)")
    conn.execute("INSERT INTO campaigns (campaign_id, name, created_at, updated_at) VALUES (?,?,?,?)",
                 ("camp", "Camp", _NOW, _NOW))
    conn.execute("INSERT INTO companies (company_id, campaign_id, canonical_name, primary_domain, "
                 "first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?)",
                 ("co-1", "camp", "One", "one.example", _NOW, _NOW))
    conn.execute("INSERT INTO drafts (draft_id, company_id, content_hash, created_at) "
                 "VALUES (?,?,?,?)", ("d1", "co-1", "sha256:x", _NOW))
    conn.execute("COMMIT")
    conn.close()


def test_v1_database_migrates_through_v2_to_v3_preserving_data(tmp_path):
    path = tmp_path / "v19.db"
    _build_v1_db(path)
    db = MemoryDB(str(path))                      # opening migrates v1 -> v2 -> v3
    assert db.current_version() == 3 and db.integrity_ok()
    repo = MemoryRepository(db)
    assert repo.count("companies") == 1           # v1 data preserved
    # v1 no-send draft history is preserved and still cannot be marked sent.
    rows = db.query("SELECT sent FROM drafts WHERE draft_id='d1'")
    assert rows[0]["sent"] == 0
    # v2 + v3 tables exist and sending is disabled by default.
    tabs = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"draft_revisions", "approval_records", "outbound_messages"}.issubset(tabs)
    assert {"contact_provenance", "suppression_checks", "pre_send_revalidations",
            "policy_decisions"}.issubset(tabs)
    g = db.query("SELECT state FROM outreach_controls WHERE scope='__global_outreach__'")[0]
    assert g["state"] == "DISABLED"
    db.close()


def test_migration_is_idempotent_on_reopen(tmp_path):
    path = tmp_path / "v19.db"
    _build_v1_db(path)
    MemoryDB(str(path)).close()
    db2 = MemoryDB(str(path))                      # reopen: already v3, no double migration
    assert db2.current_version() == 3
    assert MemoryRepository(db2).count("companies") == 1
    db2.close()


def test_v2_database_migrates_to_v3_preserving_comms_data(tmp_path):
    path = tmp_path / "v20.db"
    _build_v2_db(path)
    db = MemoryDB(str(path))                      # opening migrates v2 -> v3
    assert db.current_version() == 3 and db.integrity_ok()
    # v2 comms data (a draft revision) is preserved.
    rows = db.query("SELECT revision_id FROM draft_revisions WHERE draft_id='d1'")
    assert rows and rows[0]["revision_id"] == "rev-1"
    tabs = {r["name"] for r in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"contact_provenance", "suppression_checks", "pre_send_revalidations",
            "policy_decisions"}.issubset(tabs)
    db.close()


def test_backup_restore_across_v2(tmp_path):
    path = tmp_path / "v19.db"
    _build_v1_db(path)
    db = MemoryDB(str(path))
    backup = db.backup(str(tmp_path / "b" / "v2.bak"))
    db.close()
    restored = MemoryDB.restore(backup, str(tmp_path / "restored.db"))
    assert restored.current_version() == 3
    assert MemoryRepository(restored).count("companies") == 1  # send history + data preserved
    restored.close()

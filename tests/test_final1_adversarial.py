"""Final Phase I — adversarial hardening regressions (deterministic)."""
from __future__ import annotations

import pytest

from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository
from core.scout.pipeline.retention import RetentionError, StorageManager

_NOW = "2026-07-17T12:00:00+00:00"


def _repo(tmp_path):
    return MemoryRepository(MemoryDB(str(tmp_path / "m.db")))


def test_sql_injection_is_treated_as_data(tmp_path):
    repo = _repo(tmp_path)
    repo.upsert_campaign("camp", "Camp", _NOW)
    evil = "'); DROP TABLE companies; --"
    repo.upsert_company("co-1", "camp", evil, "x.example", _NOW)
    # The table still exists and the value was stored verbatim (parameterized query).
    rows = repo.db.query("SELECT canonical_name FROM companies WHERE company_id='co-1'")
    assert rows and rows[0]["canonical_name"] == evil
    assert repo.count("companies") == 1


def test_purge_requires_confirmation_and_is_path_confined(tmp_path):
    (tmp_path / "storage" / "sub").mkdir(parents=True)
    (tmp_path / "storage" / "sub" / "f.txt").write_text("x", encoding="utf-8")
    repo = _repo(tmp_path)
    sm = StorageManager(str(tmp_path / "storage"), repo, lambda: _NOW)
    with pytest.raises(RetentionError):
        sm.purge("subject", "sub", confirm=False)          # confirmation required
    with pytest.raises(RetentionError):
        sm.purge("subject", "../evil", confirm=True)        # path-confined
    sm.purge("subject", "sub", confirm=True)                # explicit + confined
    assert not (tmp_path / "storage" / "sub").exists()
    events = repo.db.query("SELECT event FROM lifecycle_events WHERE subject_ref='subject'")
    assert any(e["event"] == "PURGED" for e in events)      # always audited


def test_purge_refuses_storage_root(tmp_path):
    (tmp_path / "storage").mkdir()
    repo = _repo(tmp_path)
    sm = StorageManager(str(tmp_path / "storage"), repo, lambda: _NOW)
    with pytest.raises(RetentionError):
        sm.purge("subject", ".", confirm=True)              # never purge the root itself


def test_evidence_rejects_absolute_path_component(tmp_path):
    from core.scout.pipeline.evidence import EvidenceCenter
    from core.scout.store import RunStore, StoreError
    ec = EvidenceCenter(RunStore(str(tmp_path), "s"), "c", "co", "01-x")
    # A screenshot path component is validated; traversal/absolute names are rejected upstream.
    with pytest.raises(StoreError):
        ec.store.save_bytes(["prospects", "..", "evil.png"], b"x")

"""Final Independent Acceptance (v2.0.1) — real persisted gate references (deterministic)."""
from __future__ import annotations

from core.scout.comms.records import (
    ensure_suppression_check,
    record_pre_send_revalidation,
    references_resolve,
)
from core.scout.comms.repository import CommsRepository
from core.scout.comms.snapshots import is_placeholder_ref
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-17T18:30:00+00:00"


def _seed(tmp_path):
    db = MemoryDB(str(tmp_path / "m.db"))
    mem, comms = MemoryRepository(db), CommsRepository(db)
    mem.upsert_campaign("camp", "Camp", _NOW)
    mem.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    return comms


def test_synthetic_labels_are_rejected_as_placeholders():
    for ref in ("reval-live", "supp-live", "live", "current", "latest", "placeholder", "pending",
                "reval-live-xyz", "", "none"):
        assert is_placeholder_ref(ref), ref
    assert not is_placeholder_ref("supck-abc123def456")
    assert not is_placeholder_ref("reval-abc123def456")


def test_unresolved_and_placeholder_references_do_not_resolve(tmp_path):
    comms = _seed(tmp_path)
    ok, blockers = references_resolve(comms, suppression_check_ref="reval-live", company_id="co-1",
                                      contact_id="k1", now=_NOW)
    assert not ok and "placeholder_suppression_reference" in blockers
    ok2, blockers2 = references_resolve(comms, suppression_check_ref="supck-does-not-exist",
                                        company_id="co-1", contact_id="k1", now=_NOW)
    assert not ok2 and "unresolved_suppression_reference" in blockers2


def test_real_persisted_records_resolve(tmp_path):
    comms = _seed(tmp_path)
    ref = ensure_suppression_check(comms, company_id="co-1", contact_id="k1", blockers=[], now=_NOW)
    assert not is_placeholder_ref(ref)
    ok, blockers = references_resolve(comms, suppression_check_ref=ref, company_id="co-1",
                                      contact_id="k1", now=_NOW)
    assert ok and blockers == []
    row = comms.get_suppression_check(ref)
    assert row["result"] == "clear" and row["content_hash"].startswith("sha256:")


def test_suppressed_record_does_not_resolve_clear(tmp_path):
    comms = _seed(tmp_path)
    ref = ensure_suppression_check(comms, company_id="co-1", contact_id="k1",
                                   blockers=["no_outreach"], now=_NOW)
    ok, blockers = references_resolve(comms, suppression_check_ref=ref, company_id="co-1",
                                      contact_id="k1", now=_NOW)
    assert not ok and "suppression_reference_not_clear" in blockers


def test_reference_company_mismatch_is_rejected(tmp_path):
    comms = _seed(tmp_path)
    ref = ensure_suppression_check(comms, company_id="co-1", contact_id="k1", blockers=[], now=_NOW)
    ok, blockers = references_resolve(comms, suppression_check_ref=ref, company_id="co-OTHER",
                                      contact_id="k1", now=_NOW)
    assert not ok and "suppression_reference_mismatch" in blockers


def test_revalidation_record_is_persisted_and_resolvable(tmp_path):
    comms = _seed(tmp_path)
    rid = record_pre_send_revalidation(comms, company_id="co-1", contact_id="k1",
                                       revision_id="rev-1", approval_id="ap-1", blockers=[], now=_NOW)
    assert not is_placeholder_ref(rid)
    row = comms.get_revalidation(rid)
    assert row and row["result"] == "ok" and row["revision_id"] == "rev-1"

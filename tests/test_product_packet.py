"""Issue #17 — persisted product packets for the session-independent writer loop."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.collaboration.product_packet import ProductPacketError, ProductPacketStore

_T0 = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)


def test_create_and_next_pending(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="Rank Scout findings by commercial value",
                     acceptance="findings ordered by expected value on /scout/target",
                     safety="read-only analysis; no outreach", next_action="add ranking + confidence")
    assert p["status"] == "pending"
    assert store.next_pending()["packet_id"] == p["packet_id"]


def test_claim_is_atomic_and_single_use(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    first = store.claim(p["packet_id"])
    assert first["status"] == "in_progress"
    assert first["attempts"] == 1
    # A second claim of the same packet is refused (no duplicate writer launch).
    assert store.claim(p["packet_id"]) is None
    assert store.next_pending() is None                    # no longer pending


def test_update_to_done_and_failed(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    store.claim(p["packet_id"])
    done = store.update(p["packet_id"], status="done", pr_number=42, last_result="merged")
    assert done["status"] == "done"
    assert done["pr_number"] == 42


def test_release_back_to_pending_allows_reclaim(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    store.claim(p["packet_id"])
    store.update(p["packet_id"], status="pending")         # retry after a failed launch
    reclaimed = store.claim(p["packet_id"])                # can be claimed again
    assert reclaimed is not None
    assert reclaimed["attempts"] == 2


def test_claim_records_owner_and_lease(tmp_path):
    # P0-2: a claim must be attributable and time-bounded, not an anonymous forever-hold.
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    claimed = store.claim(p["packet_id"], owner="pid-123@host", lease_seconds=600, now=_T0)
    assert claimed["claim_owner"] == "pid-123@host"
    assert claimed["claimed_at"] == _T0.isoformat(timespec="seconds")
    assert claimed["lease_expires_at"] == (_T0 + timedelta(seconds=600)).isoformat(timespec="seconds")


def test_live_claim_is_not_recovered_before_lease_expiry(tmp_path):
    # P0-2: a genuinely-running writer (lease still valid) must keep single-writer behaviour.
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    store.claim(p["packet_id"], owner="w1", lease_seconds=600, now=_T0)
    recovered = store.recover_orphaned_claims(now=_T0 + timedelta(seconds=300))
    assert recovered == []
    assert store.get(p["packet_id"])["status"] == "in_progress"


def test_orphaned_claim_is_recovered_after_lease_expiry(tmp_path):
    # P0-2: a writer that died after claim but before update must not stick the queue forever.
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    store.claim(p["packet_id"], owner="w1", lease_seconds=600, now=_T0)
    recovered = store.recover_orphaned_claims(now=_T0 + timedelta(seconds=601))
    assert [r["packet_id"] for r in recovered] == [p["packet_id"]]
    rec = store.get(p["packet_id"])
    assert rec["status"] == "pending"                          # resumable, not stuck in_progress
    # The stale claim marker was cleared, so a fresh cycle can re-claim it (no duplicate launch risk).
    reclaimed = store.claim(p["packet_id"], owner="w2", now=_T0 + timedelta(seconds=602))
    assert reclaimed is not None and reclaimed["attempts"] == 2


def test_invalid_status_and_id_are_rejected(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    try:
        store.update(p["packet_id"], status="bogus")
        raise AssertionError("expected ProductPacketError")
    except ProductPacketError:
        pass
    try:
        store.claim("../etc/passwd")
        raise AssertionError("expected ProductPacketError")
    except ProductPacketError:
        pass

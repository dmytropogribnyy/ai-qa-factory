"""Issue #17 — persisted product packets for the session-independent writer loop."""
from __future__ import annotations

from core.collaboration.product_packet import ProductPacketError, ProductPacketStore


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

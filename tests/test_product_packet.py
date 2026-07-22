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


def test_orphaned_claim_recovered_only_when_owner_dead(tmp_path):
    # P0-A: an expired lease AND a provably-dead owner -> recover; a fresh cycle can re-claim.
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    store.claim(p["packet_id"], owner="w1", lease_seconds=600, now=_T0)
    recovered = store.recover_orphaned_claims(now=_T0 + timedelta(seconds=601),
                                              is_owner_alive=lambda rec: False)
    assert [r["packet_id"] for r in recovered] == [p["packet_id"]]
    rec = store.get(p["packet_id"])
    assert rec["status"] == "pending"                          # resumable, not stuck in_progress
    # The stale claim marker was cleared, so a fresh cycle can re-claim it (no duplicate launch risk).
    reclaimed = store.claim(p["packet_id"], owner="w2", now=_T0 + timedelta(seconds=602))
    assert reclaimed is not None and reclaimed["attempts"] == 2


def test_expired_lease_but_live_owner_is_NOT_recovered(tmp_path):
    # P0-A CORE: the double-writer root cause — an expired lease is NOT proof the writer is dead. A
    # still-alive owner (long run whose heartbeat lapsed) must never be reclaimed into a second writer.
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    store.claim(p["packet_id"], owner="w1", lease_seconds=150, now=_T0)
    recovered = store.recover_orphaned_claims(now=_T0 + timedelta(seconds=1000),
                                              is_owner_alive=lambda rec: True)
    assert recovered == []
    assert store.get(p["packet_id"])["status"] == "in_progress"


def test_expired_lease_unknown_owner_fails_closed_to_blocked(tmp_path):
    # P0-A: liveness unknowable (e.g. different host) -> fail closed to a visible blocked state, NOT a
    # time-only reclaim that could split-brain into two writers.
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    store.claim(p["packet_id"], owner="w1", lease_seconds=150, now=_T0)
    recovered = store.recover_orphaned_claims(now=_T0 + timedelta(seconds=1000),
                                              is_owner_alive=lambda rec: None)
    assert recovered == []
    assert store.get(p["packet_id"])["status"] == "blocked"


def test_claim_records_token_host_and_pids(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    c = store.claim(p["packet_id"], owner="pid-1@h", owner_host="h", owner_pids=[111, 222], now=_T0)
    assert c["claim_token"] and isinstance(c["claim_token"], str)
    assert c["owner_host"] == "h"
    assert c["owner_pids"] == [111, 222]


def test_heartbeat_extends_only_matching_claim_token(tmp_path):
    # P0-A regression D: a stale heartbeat / reused PID with the wrong token cannot renew or mutate a
    # newer claim.
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    c = store.claim(p["packet_id"], owner="w1", lease_seconds=150, now=_T0)
    token = c["claim_token"]
    ok = store.heartbeat(p["packet_id"], claim_token=token, lease_seconds=150,
                         now=_T0 + timedelta(seconds=60))
    assert ok is not None
    assert ok["lease_expires_at"] == (_T0 + timedelta(seconds=210)).isoformat(timespec="seconds")
    # Wrong token -> no-op, lease unchanged.
    stale = store.heartbeat(p["packet_id"], claim_token="not-the-token",
                            now=_T0 + timedelta(seconds=120))
    assert stale is None
    # Empty/missing token is ALSO a no-op once the claim has a token (unconditional token gate).
    assert store.heartbeat(p["packet_id"], claim_token="", now=_T0 + timedelta(seconds=125)) is None
    assert store.get(p["packet_id"])["lease_expires_at"] == \
        (_T0 + timedelta(seconds=210)).isoformat(timespec="seconds")


def test_resolve_is_token_gated_against_stale_owner(tmp_path):
    # P0-A: a late/stale relaunch (old token) must not clobber a fresh claim's state.
    store = ProductPacketStore(str(tmp_path))
    p = store.create(objective="x")
    old = store.claim(p["packet_id"], owner="A", now=_T0)["claim_token"]
    # simulate recovery + a fresh re-claim under a NEW token
    store.update(p["packet_id"], status="pending")
    new = store.claim(p["packet_id"], owner="B", now=_T0 + timedelta(seconds=1))["claim_token"]
    assert new != old
    # The stale owner A tries to finish the packet -> no-op.
    assert store.resolve(p["packet_id"], claim_token=old, status="done") is None
    # An empty/missing token is ALSO a no-op (unconditional token gate).
    assert store.resolve(p["packet_id"], claim_token="", status="done") is None
    assert store.get(p["packet_id"])["status"] == "in_progress"
    # The current owner B can resolve it.
    assert store.resolve(p["packet_id"], claim_token=new, status="pending") is not None


def test_truthful_terminal_statuses_are_accepted(tmp_path):
    # P1: an intentional stop must have a truthful terminal status, not a mislabelled needs_owner.
    store = ProductPacketStore(str(tmp_path))
    for status in ("stopped", "cancelled", "blocked"):
        p = store.create(objective="x")
        rec = store.update(p["packet_id"], status=status)
        assert rec["status"] == status


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

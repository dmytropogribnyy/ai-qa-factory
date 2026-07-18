"""Final Phase II — event processing, follow-up gating, and metrics (deterministic)."""
from __future__ import annotations

from core.scout.comms.events import process_event
from core.scout.comms.followup import evaluate_followup
from core.scout.comms.metrics import compute_metrics
from core.scout.comms.repository import CommsRepository
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-17T15:00:00+00:00"


def _seed(tmp_path):
    db = MemoryDB(str(tmp_path / "m.db"))
    mem = MemoryRepository(db)
    comms = CommsRepository(db)
    mem.upsert_campaign("camp", "Camp", _NOW)
    for cid in ("co-1", "co-2"):
        mem.upsert_company(cid, "camp", cid, f"{cid}.example", _NOW)
    for k, cid in (("k1", "co-1"), ("k2", "co-2")):
        mem.upsert_contact({"contact_id": k, "company_id": cid, "channel": "email",
                            "normalized_value": f"{k}@x.example", "status": "VERIFIED"})
    return db, mem, comms


def _ev(t, dk, **kw):
    base = {"event_id": f"ev-{dk}", "normalized_type": t, "received_ts": _NOW, "dedup_key": dk,
            "trust_class": "deterministic_fixture_event"}
    base.update(kw)
    return base


def test_opt_out_creates_durable_suppression(tmp_path):
    db, mem, comms = _seed(tmp_path)
    assert process_event(mem, comms, _ev("OPTED_OUT", "d1", contact_id="k1", company_id="co-1"),
                         now=_NOW) == "processed"
    assert mem.get_contact("k1")["status"] == "DO_NOT_CONTACT"
    assert mem.is_suppressed("co-1", "NO_OUTREACH")
    db.close()


def test_hard_bounce_invalidates_contact(tmp_path):
    db, mem, comms = _seed(tmp_path)
    process_event(mem, comms, _ev("BOUNCED_HARD", "d1", contact_id="k1", company_id="co-1"), now=_NOW)
    assert mem.get_contact("k1")["status"] == "INVALID"
    db.close()


def test_duplicate_event_is_idempotent(tmp_path):
    db, mem, comms = _seed(tmp_path)
    assert process_event(mem, comms, _ev("DELIVERED", "d1", contact_id="k1"), now=_NOW) == "processed"
    assert process_event(mem, comms, _ev("DELIVERED", "d1", contact_id="k1"), now=_NOW) == "duplicate"
    assert comms.count("provider_events") == 1
    db.close()


def test_unknown_event_does_not_mutate(tmp_path):
    db, mem, comms = _seed(tmp_path)
    assert process_event(mem, comms, _ev("WHAT", "d1", contact_id="k1"), now=_NOW) == "unknown_type"
    assert mem.get_contact("k1")["status"] == "VERIFIED"  # unchanged
    db.close()


def test_positive_reply_opens_commercial_review(tmp_path):
    db, mem, comms = _seed(tmp_path)
    process_event(mem, comms, _ev("REPLIED_POSITIVE", "d1", contact_id="k1", company_id="co-1"),
                  now=_NOW)
    assert any(r["queue"] == "commercial_review" for r in mem.review_items())
    db.close()


def test_followup_blocked_after_reply_but_eligible_when_clean(tmp_path):
    db, mem, comms = _seed(tmp_path)
    comms.add_contact_event("k1", "co-1", "REPLIED", "REPLIED_POSITIVE", _NOW)
    blocked = evaluate_followup(mem, comms, company_id="co-1", contact_id="k1",
                                parent_message_id="m1", sequence_no=1, now=_NOW)
    assert blocked["state"] == "BLOCKED"
    eligible = evaluate_followup(mem, comms, company_id="co-2", contact_id="k2",
                                 parent_message_id="m2", sequence_no=1, now=_NOW)
    assert eligible["state"] == "ELIGIBLE"
    assert any(r["queue"] == "draft_review" for r in mem.review_items())  # review item, not a send
    db.close()


def test_metrics_are_factual_and_zero_incident(tmp_path):
    db, mem, comms = _seed(tmp_path)
    comms.add_commercial_event("co-1", "positive_reply", _NOW, source="fixture")
    m = compute_metrics(mem, comms)
    assert m["data_source"] == "fixture" and m["companies"] == 2
    for k in ("duplicate_send_incidents", "stale_finding_send_incidents",
              "unapproved_send_incidents", "side_effect_incidents_outside_sink"):
        assert m[k] == 0
    db.close()

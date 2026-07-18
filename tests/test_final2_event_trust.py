"""Final Independent Acceptance (v2.0.1) — provider-event trust model (deterministic).

A forged contact/company relationship can never mutate state; only verified, trusted events do.
"""
from __future__ import annotations

from core.scout.comms.events import process_event
from core.scout.comms.repository import CommsRepository
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-17T22:00:00+00:00"


def _seed(tmp_path):
    db = MemoryDB(str(tmp_path / "m.db"))
    mem, comms = MemoryRepository(db), CommsRepository(db)
    mem.upsert_campaign("camp", "Camp", _NOW)
    for co in ("coA", "coB"):
        mem.upsert_company(co, "camp", co, f"{co}.example", _NOW)
    for k, co in (("kA", "coA"), ("kB", "coB")):
        mem.upsert_contact({"contact_id": k, "company_id": co, "channel": "email",
                            "normalized_value": f"{k}@x.example", "status": "VERIFIED"})
    # An outbound message that genuinely belongs to kA/coA (via the reservation).
    rid = "rev-d1-1"
    comms.create_revision({"revision_id": rid, "draft_id": "d1", "revision_number": 1,
                           "company_id": "coA", "contact_id": "kA", "channel": "email",
                           "subject": "Hi", "body": "B", "body_hash": "sha256:b", "generated_at": _NOW})
    comms.create_approval({"approval_id": "ap-1", "revision_id": rid, "recipient_hash": "r",
                           "body_hash": "sha256:b", "disclosure_hash": "d", "finding_hash": "f",
                           "evidence_hash": "e", "contact_provenance_hash": "cp", "suppression_hash": "s",
                           "channel": "email", "reviewer": "human", "approved_at": _NOW,
                           "reviewed_content_hash": "sha256:reviewed"})
    comms.reserve_and_authorize({"message_id": "mA", "revision_id": rid, "company_id": "coA",
                                 "contact_id": "kA", "channel": "email", "provider_id": "local_sink",
                                 "idempotency_key": "key-A", "now": _NOW}, "ap-1")
    comms.transition_message("mA", "PROVIDER_CALL_IN_PROGRESS", _NOW)
    comms.transition_message("mA", "ACCEPTED", _NOW)
    return mem, comms


def _ev(**kw):
    base = {"event_id": "ev1", "normalized_type": "OPTED_OUT", "received_ts": _NOW, "dedup_key": "d1"}
    base.update(kw)
    return base


def test_forged_company_cannot_suppress_another_company(tmp_path):
    mem, comms = _seed(tmp_path)
    # Authenticated event references message mA (coA/kA) but claims coB/kB.
    r = process_event(mem, comms, _ev(trust_class="authenticated_provider_event", message_ref="mA",
                                      provider="local_sink", signature_status="verified",
                                      company_id="coB", contact_id="kB"), now=_NOW)
    assert r == "quarantined"
    assert not mem.is_suppressed("coB", "NO_OUTREACH")     # the other company is untouched
    assert mem.get_contact("kB")["status"] == "VERIFIED"
    assert any(x["queue"] == "event_review" for x in mem.review_items())


def test_wrong_provider_relationship_quarantined(tmp_path):
    mem, comms = _seed(tmp_path)
    r = process_event(mem, comms, _ev(trust_class="authenticated_provider_event", message_ref="mA",
                                      provider="evil_provider", signature_status="verified"), now=_NOW)
    assert r == "quarantined" and not mem.is_suppressed("coA", "NO_OUTREACH")


def test_unverified_signature_cannot_mutate(tmp_path):
    mem, comms = _seed(tmp_path)
    r = process_event(mem, comms, _ev(trust_class="authenticated_provider_event", message_ref="mA",
                                      provider="local_sink", signature_status="unverified"), now=_NOW)
    assert r == "quarantined" and mem.get_contact("kA")["status"] == "VERIFIED"


def test_untrusted_class_cannot_mutate(tmp_path):
    mem, comms = _seed(tmp_path)
    r = process_event(mem, comms, _ev(trust_class="anonymous_webhook", message_ref="mA"), now=_NOW)
    assert r == "quarantined" and mem.get_contact("kA")["status"] == "VERIFIED"


def test_authenticated_verified_event_mutates(tmp_path):
    mem, comms = _seed(tmp_path)
    r = process_event(mem, comms, _ev(trust_class="authenticated_provider_event", message_ref="mA",
                                      provider="local_sink", signature_status="verified"), now=_NOW)
    assert r == "processed" and mem.get_contact("kA")["status"] == "DO_NOT_CONTACT"
    assert mem.is_suppressed("coA", "NO_OUTREACH")


def test_duplicate_event_is_noop(tmp_path):
    mem, comms = _seed(tmp_path)
    ev = _ev(trust_class="deterministic_fixture_event", message_ref="mA")
    assert process_event(mem, comms, ev, now=_NOW) == "processed"
    assert process_event(mem, comms, {**ev, "event_id": "ev2"}, now=_NOW) == "duplicate"
    assert comms.count("provider_events") == 1


def test_manual_import_requires_approver(tmp_path):
    mem, comms = _seed(tmp_path)
    # No message reference + manual import without an approver -> quarantined.
    r = process_event(mem, comms, _ev(trust_class="explicitly_approved_manual_import",
                                      contact_id="kA", company_id="coA", message_ref=""), now=_NOW)
    assert r == "quarantined" and mem.get_contact("kA")["status"] == "VERIFIED"
    r2 = process_event(mem, comms, _ev(event_id="ev3", dedup_key="d3",
                                       trust_class="explicitly_approved_manual_import",
                                       contact_id="kA", company_id="coA", approved_by="ops"), now=_NOW)
    assert r2 == "processed" and mem.get_contact("kA")["status"] == "DO_NOT_CONTACT"

"""Final Independent Acceptance (v2.0.1) — complete fake-Gmail E2E (deterministic; no real send)."""
from __future__ import annotations

import base64

from core.scout.comms.approval import approve_revision, build_revision
from core.scout.comms.events import process_event
from core.scout.comms.gmail import GmailProvider
from core.scout.comms.provenance import fixture_provenance
from core.scout.comms.repository import CommsRepository
from core.scout.comms.review import preview_hash_for
from core.scout.comms.send import S_ACCEPTED, SendService
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-18T10:00:00+00:00"
_RECIP = "owner@one.example"          # a fixture address, never a real prospect
_EXPECTED = "dipptrue@gmail.com"


class _CaptureTransport:
    def __init__(self):
        self.calls = 0
        self.mime = ""

    def __call__(self, token, raw_b64):
        self.calls += 1
        self.mime = base64.urlsafe_b64decode(raw_b64.encode()).decode("utf-8")
        return {"status_code": 200, "body": {"id": "gmail-msg-1", "threadId": "gmail-thread-1"}}


class _Registry:
    def __init__(self, provider):
        self._p = {provider.metadata.provider_id: provider}

    def get(self, pid):
        return self._p[pid]

    def snapshot(self):
        return [{"metadata": self._p[k].metadata.to_dict(), "readiness": self._p[k].readiness()}
                for k in self._p]


def test_complete_fake_gmail_e2e_no_real_send(tmp_path):
    db = MemoryDB(str(tmp_path / "m.db"))
    mem, comms = MemoryRepository(db), CommsRepository(db)
    mem.upsert_campaign("camp", "Camp", _NOW)
    mem.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    mem.add_session("s1", "camp", "co-1", "https://one.example/", "agency", _NOW)
    mem.upsert_contact({"contact_id": "k1", "company_id": "co-1", "channel": "email",
                        "normalized_value": _RECIP, "status": "VERIFIED",
                        "data_subject_category": "organization", "manual_review_required": False,
                        "last_verified_at": _NOW})
    mem.add_provenance(fixture_provenance("k1", "co-1", _NOW, domain="one.example"))
    mem.upsert_finding({"finding_id": "f1", "capability": "accessibility", "category": "accessibility",
                        "severity": "medium", "title": "Alt text", "root_impact_key": "axe:img",
                        "verification_state": "VERIFIED", "lifecycle_state": "ACTIVE",
                        "is_client_safe": True, "first_seen_at": _NOW, "last_seen_at": _NOW}, "s1", "co-1")
    mem.add_evidence({"evidence_id": "e1", "finding_id": "f1", "content_hash": "sha256:aa",
                      "storage_ref": "x", "sanitization_status": "sanitized", "client_safe": True,
                      "retention_deadline": "2026-12-01T00:00:00+00:00"}, "s1")

    transport = _CaptureTransport()
    provider = GmailProvider(from_email=_EXPECTED, from_name="Dmytro Pogribnyy",
                             expected_account=_EXPECTED, transport=transport,
                             token_provider=lambda: "fake-access-token")
    svc = SendService(mem, comms, _Registry(provider), lambda: _NOW)

    rid = build_revision(mem, comms, draft_id="d1", company_id="co-1", contact_id="k1",
                         finding_id="f1", channel="email", subject="A quick QA note",
                         body="Hello, we noticed one issue.", now=_NOW)
    aid = approve_revision(mem, comms, rid, reviewer="human", now=_NOW,
                           reviewed_content_hash=preview_hash_for(comms, rid))
    comms.set_control("__global_outreach__", "ENABLED")
    comms.add_allowlist(_RECIP, "self-test", _NOW)

    out = svc.send(rid, aid, "gmail_personal", campaign_id="camp", channel="email", live=True,
                   reviewer="human", confirm_recipient=_RECIP)
    assert out.status == S_ACCEPTED and out.provider_message_id == "gmail-msg-1"
    assert transport.calls == 1
    # The EXACT approved payload reached the Gmail transport.
    assert f"To: {_RECIP}" in transport.mime and "Subject: A quick QA note" in transport.mime
    assert "Hello, we noticed one issue." in transport.mime
    assert "From: Dmytro Pogribnyy <dipptrue@gmail.com>" in transport.mime

    msg = comms.get_message(out.message_id)
    assert msg["state"] == "ACCEPTED" and msg["provider_id"] == "gmail_personal"
    att = comms.attempts_for(out.message_id)[0]
    assert att["outcome"] == "ACCEPTED" and att["provider_response_ref"] == "gmail-msg-1"
    # The attempt stores no plaintext recipient/body.
    blob = "".join(str(v) for v in att.values())
    assert _RECIP not in blob and "we noticed one issue" not in blob

    # A delivered + positive-reply event (authenticated) advances the message and opens review.
    process_event(mem, comms, {"event_id": "d1", "normalized_type": "DELIVERED", "received_ts": _NOW,
                               "dedup_key": "gd1", "trust_class": "authenticated_provider_event",
                               "provider": "gmail_personal", "signature_status": "verified",
                               "message_ref": out.message_id}, now=_NOW)
    assert comms.get_message(out.message_id)["state"] == "DELIVERED"
    # The approval was single-use and the revision is consumed.
    assert comms.get_approval(aid)["state"] == "CONSUMED"
    assert comms.get_revision(rid)["state"] == "CONSUMED"
    db.close()

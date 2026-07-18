"""Final Independent Acceptance (v2.0.1) — daily outreach safety limits (deterministic)."""
from __future__ import annotations

from core.scout.comms.approval import approve_revision, build_revision
from core.scout.comms.limits import (
    DEFAULT_DAILY_MAX,
    HARD_DAILY_CEILING,
    daily_limit_blockers,
    real_send_count_today,
)
from core.scout.comms.provenance import fixture_provenance
from core.scout.comms.providers import ACCEPTED, ProviderMetadata, SendResult
from core.scout.comms.repository import CommsRepository
from core.scout.comms.review import preview_hash_for
from core.scout.comms.send import S_ACCEPTED, S_BLOCKED, SendService
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-17T23:00:00+00:00"


class _Gmailish:
    """A fake gmail_personal provider (counts calls, never touches a network)."""

    def __init__(self):
        self.metadata = ProviderMetadata(provider_id="gmail_personal", channel="email",
                                         readiness="adapter-ready")
        self.calls = 0

    def sender(self):
        return ("dipptrue@gmail.com", "Dmytro")

    def send(self, envelope):
        self.calls += 1
        return SendResult(outcome=ACCEPTED, provider_message_id=f"g-{self.calls}",
                          provider_id="gmail_personal")

    def readiness(self):
        return {"provider_id": "gmail_personal", "readiness": "adapter-ready", "live_accepted": False}


class _Registry:
    def __init__(self, provider):
        self._p = {provider.metadata.provider_id: provider}

    def get(self, pid):
        return self._p[pid]

    def snapshot(self):
        return []


def _base(tmp_path):
    db = MemoryDB(str(tmp_path / "m.db"))
    mem, comms = MemoryRepository(db), CommsRepository(db)
    mem.upsert_campaign("camp", "Camp", _NOW)
    mem.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    mem.add_session("s1", "camp", "co-1", "https://one.example/", "agency", _NOW)
    mem.upsert_finding({"finding_id": "f1", "capability": "accessibility", "category": "accessibility",
                        "severity": "medium", "title": "Alt", "root_impact_key": "axe:img",
                        "verification_state": "VERIFIED", "lifecycle_state": "ACTIVE",
                        "is_client_safe": True, "first_seen_at": _NOW, "last_seen_at": _NOW}, "s1", "co-1")
    mem.add_evidence({"evidence_id": "e1", "finding_id": "f1", "content_hash": "sha256:aa",
                      "storage_ref": "x", "sanitization_status": "sanitized", "client_safe": True,
                      "retention_deadline": "2026-12-01T00:00:00+00:00"}, "s1")
    comms.set_control("__global_outreach__", "ENABLED")
    return db, mem, comms


def _prepare(mem, comms, n):
    recip = f"k{n}@one.example"
    mem.upsert_contact({"contact_id": f"k{n}", "company_id": "co-1", "channel": "email",
                        "normalized_value": recip, "status": "VERIFIED",
                        "data_subject_category": "organization", "manual_review_required": False,
                        "last_verified_at": _NOW})
    mem.add_provenance(fixture_provenance(f"k{n}", "co-1", _NOW, domain="one.example"))
    comms.add_allowlist(recip, "test", _NOW)
    rid = build_revision(mem, comms, draft_id=f"d{n}", company_id="co-1", contact_id=f"k{n}",
                         finding_id="f1", channel="email", subject="Hi", body="Body.", now=_NOW)
    aid = approve_revision(mem, comms, rid, reviewer="human", now=_NOW,
                           reviewed_content_hash=preview_hash_for(comms, rid))
    return rid, aid, recip


def test_local_sink_is_never_limited(tmp_path):
    _, _, comms = _base(tmp_path)
    assert daily_limit_blockers(comms, provider_id="local_sink", campaign_id="camp", now=_NOW) == []


def test_defaults(tmp_path):
    assert DEFAULT_DAILY_MAX == 5 and HARD_DAILY_CEILING == 10


def test_real_provider_daily_ceiling_blocks_after_default_max(tmp_path):
    db, mem, comms = _base(tmp_path)
    provider = _Gmailish()
    svc = SendService(mem, comms, _Registry(provider), lambda: _NOW)
    for n in range(DEFAULT_DAILY_MAX):
        rid, aid, recip = _prepare(mem, comms, n)
        out = svc.send(rid, aid, "gmail_personal", campaign_id="camp", channel="email", live=True,
                       reviewer="human", confirm_recipient=recip)
        assert out.status == S_ACCEPTED, out.blockers
    assert real_send_count_today(comms, "gmail_personal", _NOW) == DEFAULT_DAILY_MAX
    # The next send is cancelled before the provider (zero extra provider calls).
    rid, aid, recip = _prepare(mem, comms, 99)
    out = svc.send(rid, aid, "gmail_personal", campaign_id="camp", channel="email", live=True,
                   reviewer="human", confirm_recipient=recip)
    assert out.status == S_BLOCKED and "daily_send_ceiling_reached" in out.blockers
    assert provider.calls == DEFAULT_DAILY_MAX  # the 6th never reached the provider
    db.close()


def test_configured_override_is_clamped_to_hard_ceiling(tmp_path):
    db, mem, comms = _base(tmp_path)
    comms.set_control("daily_max:gmail_personal", "ENABLED", {"max": 50})  # clamped to 10
    provider = _Gmailish()
    svc = SendService(mem, comms, _Registry(provider), lambda: _NOW)
    for n in range(HARD_DAILY_CEILING):
        rid, aid, recip = _prepare(mem, comms, n)
        assert svc.send(rid, aid, "gmail_personal", campaign_id="camp", channel="email", live=True,
                        reviewer="human", confirm_recipient=recip).status == S_ACCEPTED
    rid, aid, recip = _prepare(mem, comms, 99)
    out = svc.send(rid, aid, "gmail_personal", campaign_id="camp", channel="email", live=True,
                   reviewer="human", confirm_recipient=recip)
    assert out.status == S_BLOCKED and "daily_send_ceiling_reached" in out.blockers
    assert provider.calls == HARD_DAILY_CEILING
    db.close()

"""Final Independent Acceptance (v2.0.1) — send-attempt audit + pre-provider control race.

Every send finalizes a complete attempt record; a control/suppression/allowlist change appearing
AFTER reservation but before the provider call cancels the send with ZERO provider calls.
"""
from __future__ import annotations

from core.scout.comms.approval import approve_revision, build_revision
from core.scout.comms.controls import global_kill
from core.scout.comms.provenance import fixture_provenance
from core.scout.comms.providers import ACCEPTED, FAILED_DEFINITE, ProviderMetadata, ProviderTimeout, SendResult
from core.scout.comms.repository import CommsRepository
from core.scout.comms.review import preview_hash_for
from core.scout.comms.send import S_ACCEPTED, S_BLOCKED, S_FAILED, S_UNKNOWN, SendService
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-17T21:00:00+00:00"
_RECIP = "hi@one.example"


class _CountingProvider:
    """Counts provider.send() invocations; never touches a network."""

    def __init__(self, *, outcome=ACCEPTED, raise_timeout=False):
        self.metadata = ProviderMetadata(provider_id="count_sink", readiness="fixture-tested")
        self.calls = 0
        self._outcome = outcome
        self._raise_timeout = raise_timeout

    def send(self, envelope):
        self.calls += 1
        if self._raise_timeout:
            raise ProviderTimeout("ambiguous")
        return SendResult(outcome=self._outcome, provider_message_id="pm-1", provider_id="count_sink")

    def readiness(self):
        return {"provider_id": "count_sink", "readiness": "fixture-tested", "live_accepted": False}


class _Registry:
    def __init__(self, provider):
        self._p = {provider.metadata.provider_id: provider}

    def get(self, pid):
        return self._p[pid]

    def snapshot(self):
        return []


def _seed(tmp_path, *, provider=None):
    provider = provider or _CountingProvider()
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
                        "severity": "medium", "title": "Alt", "root_impact_key": "axe:img",
                        "verification_state": "VERIFIED", "lifecycle_state": "ACTIVE",
                        "is_client_safe": True, "first_seen_at": _NOW, "last_seen_at": _NOW}, "s1", "co-1")
    mem.add_evidence({"evidence_id": "e1", "finding_id": "f1", "content_hash": "sha256:aa",
                      "storage_ref": "x", "sanitization_status": "sanitized", "client_safe": True,
                      "retention_deadline": "2026-12-01T00:00:00+00:00"}, "s1")
    svc = SendService(mem, comms, _Registry(provider), lambda: _NOW)
    rid = build_revision(mem, comms, draft_id="d1", company_id="co-1", contact_id="k1",
                         finding_id="f1", channel="email", subject="Hi", body="Secret body text.",
                         now=_NOW)
    aid = approve_revision(mem, comms, rid, reviewer="human", now=_NOW,
                           reviewed_content_hash=preview_hash_for(comms, rid))
    comms.set_control("__global_outreach__", "ENABLED")
    comms.add_allowlist(_RECIP, "test", _NOW)
    return mem, comms, svc, rid, aid, provider


def _send(svc, rid, aid, provider_id="count_sink"):
    return svc.send(rid, aid, provider_id, campaign_id="camp", channel="email", live=True,
                    reviewer="human", confirm_recipient=_RECIP)


# --- attempt audit --------------------------------------------------------------------------------

def test_accepted_attempt_is_finalized_without_body(tmp_path):
    mem, comms, svc, rid, aid, provider = _seed(tmp_path)
    out = _send(svc, rid, aid)
    assert out.status == S_ACCEPTED and provider.calls == 1
    attempts = comms.attempts_for(out.message_id)
    assert len(attempts) == 1
    att = attempts[0]
    assert att["outcome"] == "ACCEPTED" and att["finished_at"] and att["provider_response_ref"] == "pm-1"
    assert att["request_hash"].startswith("sha256:")
    # No body/recipient plaintext is stored in the attempt.
    blob = "".join(str(v) for v in att.values()).lower()
    assert "secret body text" not in blob and _RECIP not in blob


def test_definite_failure_attempt_is_finalized(tmp_path):
    mem, comms, svc, rid, aid, provider = _seed(tmp_path, provider=_CountingProvider(outcome=FAILED_DEFINITE))
    out = _send(svc, rid, aid)
    assert out.status == S_FAILED and provider.calls == 1
    assert comms.attempts_for(out.message_id)[0]["outcome"] == "FAILED_DEFINITE"


def test_ambiguous_attempt_is_finalized_unknown(tmp_path):
    mem, comms, svc, rid, aid, provider = _seed(tmp_path, provider=_CountingProvider(raise_timeout=True))
    out = _send(svc, rid, aid)
    assert out.status == S_UNKNOWN and provider.calls == 1
    att = comms.attempts_for(out.message_id)[0]
    assert att["outcome"] == "OUTCOME_UNKNOWN" and att["ambiguity_state"]


def test_no_orphan_attempt_or_message(tmp_path):
    mem, comms, svc, rid, aid, provider = _seed(tmp_path)
    out = _send(svc, rid, aid)
    # Every attempt references a real message; the accepted message has a finished attempt.
    for att in comms.attempts_for(out.message_id):
        assert comms.get_message(att["message_id"]) is not None
        assert att["finished_at"]


# --- pre-provider control race (every case: ZERO provider calls) ----------------------------------

def _race(tmp_path, mutate):
    mem, comms, svc, rid, aid, provider = _seed(tmp_path)
    svc.before_invoke = lambda: mutate(mem, comms)
    out = _send(svc, rid, aid)
    assert out.status == S_BLOCKED, out.blockers
    assert provider.calls == 0                                   # the critical invariant
    assert comms.get_message(out.message_id)["state"] == "CANCELLED"
    att = comms.attempts_for(out.message_id)
    assert att and att[0]["outcome"] == "CANCELLED_BEFORE_PROVIDER"
    return out


def test_race_global_kill(tmp_path):
    _race(tmp_path, lambda mem, comms: global_kill(comms))


def test_race_campaign_disable(tmp_path):
    _race(tmp_path, lambda mem, comms: comms.set_control("campaign:camp", "DISABLED"))


def test_race_provider_disable(tmp_path):
    _race(tmp_path, lambda mem, comms: comms.set_control("provider:count_sink", "DISABLED"))


def test_race_channel_pause(tmp_path):
    _race(tmp_path, lambda mem, comms: comms.set_control("channel:email", "PAUSED"))


def test_race_allowlist_removal(tmp_path):
    _race(tmp_path, lambda mem, comms: comms.db.execute(
        "DELETE FROM recipient_allowlist WHERE normalized_value=?", (_RECIP,)))


def test_race_opt_out(tmp_path):
    _race(tmp_path, lambda mem, comms: comms.add_contact_event("k1", "co-1", "OPT_OUT", "x", _NOW))


def test_race_hard_bounce(tmp_path):
    _race(tmp_path, lambda mem, comms: comms.add_contact_event("k1", "co-1", "HARD_BOUNCE", "x", _NOW))


def test_race_contact_status_change(tmp_path):
    _race(tmp_path, lambda mem, comms: mem.set_contact_status("k1", "INVALID"))

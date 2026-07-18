"""Final Phase II — approved, gated, idempotent local-sink sending (deterministic; no network)."""
from __future__ import annotations

from core.scout.comms.approval import approve_revision, build_revision, edit_revision
from core.scout.comms.controls import global_kill
from core.scout.comms.provenance import fixture_provenance
from core.scout.comms.providers import DeterministicLocalSinkProvider, ProviderRegistry
from core.scout.comms.repository import CommsRepository
from core.scout.comms.send import (
    S_ACCEPTED,
    S_BLOCKED,
    S_DRY_RUN,
    S_IDEMPOTENT,
    S_UNKNOWN,
    SendService,
)
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-17T14:00:00+00:00"
_RECIP = "hello@one.example"


def _seed(tmp_path, *, sink_outcome="ACCEPTED", raise_timeout=False):
    clock = lambda: _NOW  # noqa: E731
    db = MemoryDB(str(tmp_path / "m.db"))
    mem = MemoryRepository(db)
    comms = CommsRepository(db)
    mem.upsert_campaign("camp", "Camp", _NOW)
    mem.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    mem.add_session("s1", "camp", "co-1", "https://one.example/", "agency", _NOW)
    mem.upsert_contact({"contact_id": "k1", "company_id": "co-1", "channel": "email",
                        "normalized_value": _RECIP, "status": "VERIFIED",
                        "data_subject_category": "organization", "manual_review_required": False,
                        "last_verified_at": _NOW})
    mem.add_provenance(fixture_provenance("k1", "co-1", _NOW, domain="one.example"))
    mem.upsert_finding({"finding_id": "f1", "capability": "accessibility", "category": "accessibility",
                        "severity": "medium", "title": "Missing alt text",
                        "root_impact_key": "axe:image-alt", "verification_state": "VERIFIED",
                        "lifecycle_state": "ACTIVE", "is_client_safe": True,
                        "first_seen_at": _NOW, "last_seen_at": _NOW}, "s1", "co-1")
    mem.add_evidence({"evidence_id": "e1", "finding_id": "f1", "content_hash": "sha256:aa",
                      "storage_ref": "prospects/s1/evidence/e1.json", "sanitization_status": "sanitized",
                      "client_safe": True, "retention_deadline": "2026-12-01T00:00:00+00:00"}, "s1")
    registry = ProviderRegistry()
    registry.register(DeterministicLocalSinkProvider(str(tmp_path / "sink"), outcome=sink_outcome,
                                                     raise_timeout=raise_timeout))
    svc = SendService(mem, comms, registry, clock)
    rid = build_revision(mem, comms, draft_id="d1", company_id="co-1", contact_id="k1",
                         finding_id="f1", channel="email", subject="A quick QA note",
                         body="Hello, we noticed one issue.", now=_NOW)
    aid = approve_revision(comms, rid, reviewer="human", now=_NOW)
    return mem, comms, svc, rid, aid, tmp_path


def _enable(comms):
    comms.set_control("__global_outreach__", "ENABLED")
    comms.add_allowlist(_RECIP, "acceptance", _NOW)


def _send(svc, rid, aid, **kw):
    base = dict(campaign_id="camp", channel="email", live=True, reviewer="human",
                confirm_recipient=_RECIP)
    base.update(kw)
    return svc.send(rid, aid, "local_sink", **base)


def test_dry_run_never_sends(tmp_path):
    mem, comms, svc, rid, aid, _ = _seed(tmp_path)
    _enable(comms)
    out = svc.send(rid, aid, "local_sink", campaign_id="camp", live=False)
    assert out.status == S_DRY_RUN and not list((tmp_path / "sink").glob("*.json"))
    assert comms.get_approval(aid)["state"] == "APPROVED"  # dry-run does not consume


def test_disabled_by_default_blocks_send(tmp_path):
    mem, comms, svc, rid, aid, _ = _seed(tmp_path)  # outreach DISABLED by default
    out = _send(svc, rid, aid)
    assert out.status == S_BLOCKED and "global_outreach_disabled" in out.blockers


def test_approved_send_to_local_sink(tmp_path):
    mem, comms, svc, rid, aid, tp = _seed(tmp_path)
    _enable(comms)
    out = _send(svc, rid, aid)
    assert out.status == S_ACCEPTED and out.provider_message_id
    assert len(list((tp / "sink").glob("*.json"))) == 1  # exactly one sanitized envelope
    assert comms.get_message(out.message_id)["state"] == "ACCEPTED"
    assert comms.get_approval(aid)["state"] == "CONSUMED"


def test_approval_is_single_use_no_double_send(tmp_path):
    mem, comms, svc, rid, aid, tp = _seed(tmp_path)
    _enable(comms)
    assert _send(svc, rid, aid).status == S_ACCEPTED
    second = _send(svc, rid, aid)                       # same approval replay
    assert second.status in (S_BLOCKED, S_IDEMPOTENT)  # never a second send
    assert len(list((tp / "sink").glob("*.json"))) == 1


def test_recipient_confirmation_must_match(tmp_path):
    mem, comms, svc, rid, aid, _ = _seed(tmp_path)
    _enable(comms)
    out = _send(svc, rid, aid, confirm_recipient="wrong@x.example")
    assert out.status == S_BLOCKED and "recipient_confirmation_mismatch" in out.blockers


def test_missing_reviewer_blocks(tmp_path):
    mem, comms, svc, rid, aid, _ = _seed(tmp_path)
    _enable(comms)
    assert _send(svc, rid, aid, reviewer="  ").status == S_BLOCKED


def test_edit_invalidates_approval(tmp_path):
    mem, comms, svc, rid, aid, _ = _seed(tmp_path)
    _enable(comms)
    edit_revision(mem, comms, rid, subject="Edited", body="New body", now=_NOW)
    out = _send(svc, rid, aid)
    assert out.status == S_BLOCKED
    assert "revision_superseded" in out.blockers or "approval_state_invalidated" in out.blockers


def test_recipient_change_invalidates_approval(tmp_path):
    mem, comms, svc, rid, aid, _ = _seed(tmp_path)
    _enable(comms)
    mem.db.execute("UPDATE contacts SET normalized_value='changed@one.example' WHERE contact_id='k1'")
    out = _send(svc, rid, aid, confirm_recipient=_RECIP)
    assert out.status == S_BLOCKED and any("changed_recipient" in b for b in out.blockers)
    assert comms.get_approval(aid)["state"] == "INVALIDATED"


def test_resolved_finding_cannot_send(tmp_path):
    mem, comms, svc, rid, aid, _ = _seed(tmp_path)
    _enable(comms)
    mem.set_finding_lifecycle("f1", "RESOLVED")
    out = _send(svc, rid, aid)
    assert out.status == S_BLOCKED and "finding_not_sendable" in out.blockers


def test_opt_out_event_blocks_send(tmp_path):
    mem, comms, svc, rid, aid, _ = _seed(tmp_path)
    _enable(comms)
    comms.add_contact_event("k1", "co-1", "OPT_OUT", "unsubscribed", _NOW)
    out = _send(svc, rid, aid)
    assert out.status == S_BLOCKED and "contact_blocked_by_event" in out.blockers


def test_global_kill_blocks_pending_send(tmp_path):
    mem, comms, svc, rid, aid, _ = _seed(tmp_path)
    _enable(comms)
    global_kill(comms)
    out = _send(svc, rid, aid)
    assert out.status == S_BLOCKED and "global_kill" in out.blockers


def test_ambiguous_outcome_is_unknown_and_not_retried(tmp_path):
    mem, comms, svc, rid, aid, tp = _seed(tmp_path, raise_timeout=True)
    _enable(comms)
    out = _send(svc, rid, aid)
    assert out.status == S_UNKNOWN
    assert comms.get_message(out.message_id)["state"] == "OUTCOME_UNKNOWN"
    # A replay does not auto-retry (approval consumed; idempotency key reserved).
    assert _send(svc, rid, aid).status in (S_BLOCKED, S_IDEMPOTENT)


def test_no_secret_leak_in_sink_or_db(tmp_path):
    mem, comms, svc, rid, aid, tp = _seed(tmp_path)
    _enable(comms)
    _send(svc, rid, aid)
    for p in tp.rglob("*"):
        if p.is_file():
            blob = p.read_bytes().lower()
            assert b"password" not in blob and b"api_key" not in blob and b"bearer" not in blob

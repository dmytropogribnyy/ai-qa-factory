"""Final Independent Acceptance (v2.0.1) — complete contact provenance gates (deterministic)."""
from __future__ import annotations

import pytest

from core.scout.comms.approval import ApprovalError, approve_revision, build_revision
from core.scout.comms.provenance import fixture_provenance, is_fixture, provenance_blockers
from core.scout.comms.providers import DeterministicLocalSinkProvider, ProviderRegistry
from core.scout.comms.repository import CommsRepository
from core.scout.comms.review import preview_hash_for
from core.scout.comms.send import S_ACCEPTED, S_BLOCKED, SendService
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-17T18:00:00+00:00"
_RECIP = "hi@one.example"


def _seed(tmp_path, *, provenance="fixture"):
    db = MemoryDB(str(tmp_path / "m.db"))
    mem, comms = MemoryRepository(db), CommsRepository(db)
    mem.upsert_campaign("camp", "Camp", _NOW)
    mem.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    mem.add_session("s1", "camp", "co-1", "https://one.example/", "agency", _NOW)
    mem.upsert_contact({"contact_id": "k1", "company_id": "co-1", "channel": "email",
                        "normalized_value": _RECIP, "status": "VERIFIED",
                        "data_subject_category": "organization", "manual_review_required": False,
                        "last_verified_at": _NOW})
    mem.upsert_finding({"finding_id": "f1", "capability": "accessibility", "category": "accessibility",
                        "severity": "medium", "title": "Missing alt text", "root_impact_key": "axe:img",
                        "verification_state": "VERIFIED", "lifecycle_state": "ACTIVE",
                        "is_client_safe": True, "first_seen_at": _NOW, "last_seen_at": _NOW}, "s1", "co-1")
    mem.add_evidence({"evidence_id": "e1", "finding_id": "f1", "content_hash": "sha256:aa",
                      "storage_ref": "x", "sanitization_status": "sanitized", "client_safe": True,
                      "retention_deadline": "2026-12-01T00:00:00+00:00"}, "s1")
    if provenance == "fixture":
        provenance = fixture_provenance("k1", "co-1", _NOW, domain="one.example")
    if provenance is not None:
        mem.add_provenance(provenance)
    registry = ProviderRegistry()
    registry.register(DeterministicLocalSinkProvider(str(tmp_path / "sink")))
    svc = SendService(mem, comms, registry, lambda: _NOW)
    return mem, comms, svc


def _prepare_and_send(mem, comms, svc):
    rid = build_revision(mem, comms, draft_id="d1", company_id="co-1", contact_id="k1",
                         finding_id="f1", channel="email", subject="Hi", body="Body.", now=_NOW)
    aid = approve_revision(mem, comms, rid, reviewer="human", now=_NOW,
                           reviewed_content_hash=preview_hash_for(comms, rid))
    comms.set_control("__global_outreach__", "ENABLED")
    comms.add_allowlist(_RECIP, "test", _NOW)
    out = svc.send(rid, aid, "local_sink", campaign_id="camp", channel="email", live=True,
                   reviewer="human", confirm_recipient=_RECIP)
    return rid, aid, out


def test_complete_fixture_provenance_allows_send(tmp_path):
    mem, comms, svc = _seed(tmp_path)
    _, _, out = _prepare_and_send(mem, comms, svc)
    assert out.status == S_ACCEPTED


def test_missing_provenance_blocks_at_build(tmp_path):
    mem, comms, svc = _seed(tmp_path, provenance=None)
    with pytest.raises(ApprovalError):
        build_revision(mem, comms, draft_id="d1", company_id="co-1", contact_id="k1",
                       finding_id="f1", channel="email", subject="Hi", body="Body.", now=_NOW)


def test_superseded_provenance_blocks_send(tmp_path):
    mem, comms, svc = _seed(tmp_path)
    rid = build_revision(mem, comms, draft_id="d1", company_id="co-1", contact_id="k1",
                         finding_id="f1", channel="email", subject="Hi", body="Body.", now=_NOW)
    aid = approve_revision(mem, comms, rid, reviewer="human", now=_NOW,
                           reviewed_content_hash=preview_hash_for(comms, rid))
    comms.set_control("__global_outreach__", "ENABLED")
    comms.add_allowlist(_RECIP, "test", _NOW)
    mem.db.execute("UPDATE contact_provenance SET state='SUPERSEDED' WHERE contact_id='k1'")
    out = svc.send(rid, aid, "local_sink", campaign_id="camp", channel="email", live=True,
                   reviewer="human", confirm_recipient=_RECIP)
    assert out.status == S_BLOCKED and "provenance_missing" in out.blockers


def test_unpublished_contact_blocks_send(tmp_path):
    prov = fixture_provenance("k1", "co-1", _NOW, domain="one.example")
    prov["publicly_published_for_contact"] = False
    mem, comms, svc = _seed(tmp_path, provenance=prov)
    _, _, out = _prepare_and_send(mem, comms, svc)
    assert out.status == S_BLOCKED and "contact_not_publicly_published" in out.blockers


def test_terms_blocked_provenance_blocks_send(tmp_path):
    prov = fixture_provenance("k1", "co-1", _NOW, domain="one.example")
    prov["terms_review_status"] = "blocked"
    mem, comms, svc = _seed(tmp_path, provenance=prov)
    _, _, out = _prepare_and_send(mem, comms, svc)
    assert out.status == S_BLOCKED and "provenance_terms_blocked" in out.blockers


def test_expired_provenance_blocks_send(tmp_path):
    prov = fixture_provenance("k1", "co-1", _NOW, domain="one.example")
    prov["freshness_deadline"] = "2020-01-01T00:00:00+00:00"
    mem, comms, svc = _seed(tmp_path, provenance=prov)
    _, _, out = _prepare_and_send(mem, comms, svc)
    assert out.status == S_BLOCKED and "provenance_expired" in out.blockers


def test_named_person_review_required_blocks_send(tmp_path):
    prov = fixture_provenance("k1", "co-1", _NOW, domain="one.example")
    prov.update(person_class="named_person", named_person_review_result="")
    mem, comms, svc = _seed(tmp_path, provenance=prov)
    _, _, out = _prepare_and_send(mem, comms, svc)
    assert out.status == S_BLOCKED and "named_person_review_incomplete" in out.blockers


def test_provenance_change_after_approval_invalidates(tmp_path):
    mem, comms, svc = _seed(tmp_path)
    rid = build_revision(mem, comms, draft_id="d1", company_id="co-1", contact_id="k1",
                         finding_id="f1", channel="email", subject="Hi", body="Body.", now=_NOW)
    aid = approve_revision(mem, comms, rid, reviewer="human", now=_NOW,
                           reviewed_content_hash=preview_hash_for(comms, rid))
    comms.set_control("__global_outreach__", "ENABLED")
    comms.add_allowlist(_RECIP, "test", _NOW)
    # A new ACTIVE provenance from a different source supersedes the approved one.
    mem.add_provenance(fixture_provenance("k1", "co-1", _NOW, domain="other.example"))
    out = svc.send(rid, aid, "local_sink", campaign_id="camp", channel="email", live=True,
                   reviewer="human", confirm_recipient=_RECIP)
    assert out.status == S_BLOCKED and "changed_contact_provenance" in out.blockers
    assert comms.get_approval(aid)["state"] == "INVALIDATED"


def test_fixture_marker_is_explicit_and_synthetic_is_blocked():
    fx = fixture_provenance("k1", "co-1", _NOW)
    assert is_fixture(fx) and provenance_blockers(fx, now=_NOW) == []
    synthetic = dict(fx, source_category="inferred")
    assert "provenance_synthetic_or_defaulted" in provenance_blockers(synthetic, now=_NOW)
    assert not is_fixture(synthetic)

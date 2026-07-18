"""Final Independent Acceptance (v2.0.1) — mandatory reviewed-content proof (deterministic)."""
from __future__ import annotations

import pytest

from core.scout.comms.approval import ApprovalError, approve_revision, build_revision, edit_revision
from core.scout.comms.provenance import fixture_provenance
from core.scout.comms.repository import CommsError, CommsRepository
from core.scout.comms.review import preview_hash, preview_hash_for, review_preview
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-17T19:00:00+00:00"


def _seed(tmp_path):
    db = MemoryDB(str(tmp_path / "m.db"))
    mem, comms = MemoryRepository(db), CommsRepository(db)
    mem.upsert_campaign("camp", "Camp", _NOW)
    mem.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    mem.add_session("s1", "camp", "co-1", "https://one.example/", "agency", _NOW)
    mem.upsert_contact({"contact_id": "k1", "company_id": "co-1", "channel": "email",
                        "normalized_value": "hi@one.example", "status": "VERIFIED",
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
    rid = build_revision(mem, comms, draft_id="d1", company_id="co-1", contact_id="k1",
                         finding_id="f1", channel="email", subject="Hi", body="Body.", now=_NOW)
    return mem, comms, rid


def test_preview_exposes_exact_content_and_hash(tmp_path):
    mem, comms, rid = _seed(tmp_path)
    preview = review_preview(mem, comms, rid)
    assert preview["recipient"] == "hi@one.example" and preview["subject"] == "Hi"
    assert preview["body"] == "Body."
    assert preview["reviewed_content_hash"] == preview_hash_for(comms, rid)
    assert preview["reviewed_content_hash"].startswith("sha256:")


def test_approval_requires_matching_preview_hash(tmp_path):
    mem, comms, rid = _seed(tmp_path)
    aid = approve_revision(mem, comms, rid, reviewer="human", now=_NOW,
                           reviewed_content_hash=preview_hash_for(comms, rid))
    assert comms.get_approval(aid)["reviewed_content_hash"] == preview_hash_for(comms, rid)


def test_empty_reviewed_content_hash_is_rejected(tmp_path):
    mem, comms, rid = _seed(tmp_path)
    with pytest.raises(ApprovalError):
        approve_revision(mem, comms, rid, reviewer="human", now=_NOW, reviewed_content_hash="")


def test_arbitrary_reviewed_content_hash_is_rejected(tmp_path):
    mem, comms, rid = _seed(tmp_path)
    with pytest.raises(ApprovalError):
        approve_revision(mem, comms, rid, reviewer="human", now=_NOW,
                         reviewed_content_hash="sha256:deadbeef")


def test_preview_hash_for_another_revision_is_rejected(tmp_path):
    mem, comms, rid = _seed(tmp_path)
    other = build_revision(mem, comms, draft_id="d2", company_id="co-1", contact_id="k1",
                           finding_id="f1", channel="email", subject="Other", body="Different.",
                           now=_NOW)
    with pytest.raises(ApprovalError):
        approve_revision(mem, comms, rid, reviewer="human", now=_NOW,
                         reviewed_content_hash=preview_hash_for(comms, other))


def test_repository_rejects_direct_empty_reviewed_content_hash(tmp_path):
    mem, comms, rid = _seed(tmp_path)
    rev = comms.get_revision(rid)
    ap = {"approval_id": "ap-x", "revision_id": rid, "recipient_hash": rev["recipient_hash"],
          "body_hash": rev["body_hash"], "disclosure_hash": rev["disclosure_hash"],
          "finding_hash": rev["finding_hash"], "evidence_hash": rev["evidence_hash"],
          "contact_provenance_hash": rev["contact_provenance_hash"],
          "suppression_hash": rev["suppression_hash"], "channel": "email", "reviewer": "human",
          "approved_at": _NOW, "reviewed_content_hash": ""}
    with pytest.raises(CommsError):
        comms.create_approval(ap)


def test_stale_preview_rejected_when_underlying_data_changes(tmp_path):
    mem, comms, rid = _seed(tmp_path)
    good = preview_hash_for(comms, rid)
    # The contact recipient changes after the revision was built -> current truth no longer matches.
    mem.db.execute("UPDATE contacts SET normalized_value='changed@one.example' WHERE contact_id='k1'")
    with pytest.raises(ApprovalError):
        approve_revision(mem, comms, rid, reviewer="human", now=_NOW, reviewed_content_hash=good)


def test_edit_supersedes_and_blocks_approval_of_old_revision(tmp_path):
    mem, comms, rid = _seed(tmp_path)
    edit_revision(mem, comms, rid, subject="Edited", body="New.", now=_NOW)
    # The old revision is superseded; it cannot be previewed-then-approved.
    assert comms.get_revision(rid)["state"] == "SUPERSEDED"
    with pytest.raises(ApprovalError):
        approve_revision(mem, comms, rid, reviewer="human", now=_NOW,
                         reviewed_content_hash=preview_hash(comms.get_revision(rid)))

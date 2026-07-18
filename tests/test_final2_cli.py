"""Final Independent Acceptance (v2.0.1) — human review + Gmail/provider CLI (deterministic)."""
from __future__ import annotations

from argparse import Namespace

from core.scout.comms.cli import (
    cmd_draft_approve,
    cmd_draft_create,
    cmd_draft_preview,
    cmd_draft_status,
    cmd_gmail_status,
    cmd_provider_status,
    cmd_send,
)
from core.scout.comms.provenance import fixture_provenance
from core.scout.comms.repository import CommsRepository
from core.scout.comms.review import preview_hash_for
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-18T09:00:00+00:00"
_RECIP = "hi@one.example"


def _seed(db_path):
    db = MemoryDB(db_path)
    mem = MemoryRepository(db)
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
    db.close()


def _ns(db, **kw):
    base = dict(db=db, draft_id=None, company_id=None, contact_id=None, finding_id=None,
                channel="email", subject=None, body=None, body_file=None, reviewer=None,
                draft_revision=None, reviewed_content_hash=None, confirm=None, reason=None,
                approval_id="", provider=None, approve_send=False, confirm_recipient=None,
                client_config=None, token_store=None, expected_account=None, output="outputs")
    base.update(kw)
    return Namespace(**base)


def test_full_review_flow_create_preview_approve_status(tmp_path, capsys):
    db_path = str(tmp_path / "m.db")
    _seed(db_path)
    assert cmd_draft_create(_ns(db_path, draft_id="d1", company_id="co-1", contact_id="k1",
                                finding_id="f1", subject="A quick QA note",
                                body="Hello, one issue on your site.", reviewer="human")) == 0
    rid = "rev-d1-1"
    assert cmd_draft_preview(_ns(db_path, draft_revision=rid)) == 0
    out = capsys.readouterr().out
    assert _RECIP in out and "A quick QA note" in out and "Hello, one issue" in out

    db = MemoryDB(db_path)
    good = preview_hash_for(CommsRepository(db), rid)
    db.close()

    # Wrong confirmation is refused.
    assert cmd_draft_approve(_ns(db_path, draft_revision=rid, reviewer="human",
                                 reviewed_content_hash=good, confirm="nope")) != 0
    # Wrong hash is refused (exit 2).
    assert cmd_draft_approve(_ns(db_path, draft_revision=rid, reviewer="human",
                                 reviewed_content_hash="sha256:wrong", confirm="APPROVE")) == 2
    # Exact hash + typed confirmation approves.
    assert cmd_draft_approve(_ns(db_path, draft_revision=rid, reviewer="human",
                                 reviewed_content_hash=good, confirm="APPROVE")) == 0
    assert cmd_draft_status(_ns(db_path, draft_revision=rid)) == 0
    status_out = capsys.readouterr().out
    assert "state=APPROVED" in status_out


def test_send_is_dry_run_by_default(tmp_path, capsys):
    db_path = str(tmp_path / "m.db")
    _seed(db_path)
    cmd_draft_create(_ns(db_path, draft_id="d1", company_id="co-1", contact_id="k1", finding_id="f1",
                         subject="S", body="B", reviewer="human"))
    rid = "rev-d1-1"
    db = MemoryDB(db_path)
    good = preview_hash_for(CommsRepository(db), rid)
    db.close()
    cmd_draft_approve(_ns(db_path, draft_revision=rid, reviewer="human", reviewed_content_hash=good,
                          confirm="APPROVE"))
    capsys.readouterr()
    # send without --approve-send is a dry run (exit 0, nothing sent).
    rc = cmd_send(_ns(db_path, draft_revision=rid, provider="local_sink", reviewer="human",
                      confirm_recipient=_RECIP))
    assert rc == 0
    assert "DRY-RUN" in capsys.readouterr().out


def test_gmail_and_provider_status_no_credentials(capsys):
    assert cmd_gmail_status(_ns(db=None)) == 0
    out = capsys.readouterr().out
    assert "adapter-ready" in out and "dipptrue@gmail.com" in out
    assert cmd_provider_status(_ns(db=None)) == 0
    out2 = capsys.readouterr().out
    assert "gmail_personal" in out2 and "local_sink" in out2 and "resend_email" in out2

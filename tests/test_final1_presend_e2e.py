"""Final Phase I — complete pre-send pipeline E2E (deterministic, no browser, nothing sent)."""
from __future__ import annotations

import itertools
import json

from core.scout.demo_site import serve_demo_site
from core.scout.discovery.fixtures import HostMappedStaticBackend
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository
from core.scout.outreach.contacts import inferred_contact, public_contact
from core.scout.pipeline.presend import PreSendPipeline
from core.scout.store import RunStore
from core.scout.url_safety import UrlPolicy

_c = itertools.count()
_NOW = "2026-07-17T11:00:00+00:00"

_ARTIFACTS = (
    "NORMALIZED_FINDINGS.json", "COMPANY_IDENTITY.json", "SITE_FINGERPRINT.json",
    "RECHECK_RESULT.json", "LEAD_SCORECARD.json", "CONTACTS.json", "CONTACT_VERIFICATION.json",
    "SUPPRESSION_CHECK.json", "AUDIT_OFFER.json", "DISCLOSURE_MANIFEST.json", "OUTREACH_DRAFTS.md",
    "REVIEW_QUEUE.json", "RETENTION_PLAN.json", "CAMPAIGN_SUMMARY.md",
)


def _clock():
    return f"2026-07-17T11:00:{next(_c):02d}+00:00"


def _contact_source(cand):
    dom = cand["registrable_domain"]
    return [
        public_contact(f"co-{dom}", dom, "email", f"hello@{dom}", evidence_ref="ev-1",
                       observed_at=_NOW, verify=True, suppression_check_ref="supp-1"),
        public_contact(f"co-{dom}", dom, "email", f"jane@{dom}", evidence_ref="ev-2",
                       observed_at=_NOW, data_subject="named_person", verify=True,
                       suppression_check_ref="supp-1"),
        inferred_contact(f"co-{dom}", dom, "email", f"guess@{dom}", observed_at=_NOW),
    ]


def _run(tmp_path):
    with serve_demo_site() as (_base, hostport):
        host_map = {"acme.example": hostport, "shopmart.example": hostport,
                    "noout.example": hostport}
        backend = HostMappedStaticBackend(UrlPolicy(resolve_dns=False), host_map)
        candidates = [
            {"candidate_id": "c1", "url": "http://acme.example/accessibility/index.html",
             "registrable_domain": "acme.example", "company_name": "Acme",
             "hints": {"business_type_hint": "agency"}},
            {"candidate_id": "c2", "url": "http://shopmart.example/seo/index.html",
             "registrable_domain": "shopmart.example", "company_name": "ShopMart",
             "hints": {"business_type_hint": "ecommerce"}},
            {"candidate_id": "c3", "url": "http://noout.example/mobile/index.html",
             "registrable_domain": "noout.example", "company_name": "NoOut",
             "suppression_status": "NO_OUTREACH", "hints": {"business_type_hint": "agency"}},
        ]
        db = MemoryDB(str(tmp_path / "memory.db"))
        repo = MemoryRepository(db)
        store = RunStore(str(tmp_path), "campaign-presend")
        pipe = PreSendPipeline(store, repo, campaign_id="campaign-presend",
                               policy=UrlPolicy(resolve_dns=False), backend=backend, clock=_clock,
                               contact_source=_contact_source)
        summary = pipe.run(candidates)
        return summary, store, repo, db


def test_full_presend_pipeline_and_artifacts(tmp_path):
    summary, store, repo, db = _run(tmp_path)
    assert summary["any_sent"] is False
    for name in _ARTIFACTS:
        assert (store.report_dir() / name).exists(), f"missing artifact: {name}"

    assert summary["verified_findings"] >= 1
    findings = json.loads((store.report_dir() / "NORMALIZED_FINDINGS.json").read_text("utf-8"))
    assert all(f["is_client_safe"] for f in findings)

    # Memory persisted the truth.
    assert repo.count("companies") == 3
    assert repo.count("findings") >= 1
    assert repo.count("contacts") >= 3  # per company, deduped
    db.close()


def test_no_outreach_candidate_has_no_draft(tmp_path):
    summary, store, repo, db = _run(tmp_path)
    supp = json.loads((store.report_dir() / "SUPPRESSION_CHECK.json").read_text("utf-8"))
    assert any(s["no_outreach"] for s in supp)
    drafts_md = (store.report_dir() / "OUTREACH_DRAFTS.md").read_text("utf-8")
    assert "noout.example" not in drafts_md  # NO_OUTREACH company never gets a draft
    db.close()


def test_inferred_and_named_contact_safety(tmp_path):
    summary, store, repo, db = _run(tmp_path)
    contacts = json.loads((store.report_dir() / "CONTACT_VERIFICATION.json").read_text("utf-8"))
    # Inferred + named-person contacts are not outreach candidates; verified generic ones are.
    assert any(c["outreach_candidate"] for c in contacts)      # verified generic
    assert any(not c["outreach_candidate"] for c in contacts)  # inferred / unreviewed named-person
    # There is a contact-review queue item for the named-person contacts.
    review = json.loads((store.report_dir() / "REVIEW_QUEUE.json").read_text("utf-8"))
    assert any(r.get("queue") == "contact_review" for r in review)
    db.close()


def test_drafts_are_pending_review_and_never_sent(tmp_path):
    summary, store, repo, db = _run(tmp_path)
    assert summary["drafts"] >= 1
    drafts_md = (store.report_dir() / "OUTREACH_DRAFTS.md").read_text("utf-8")
    assert "PENDING HUMAN REVIEW" in drafts_md and "Sent: False" in drafts_md
    # The DB CHECK guarantees no draft is sent.
    rows = repo.db.query("SELECT sent FROM drafts")
    assert all(r["sent"] == 0 for r in rows)
    db.close()


def test_no_secret_leak_across_artifacts_and_db(tmp_path):
    _run(tmp_path)
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert b"secretcookievalue" not in p.read_bytes(), f"leak in {p}"

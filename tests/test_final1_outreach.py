"""Final Phase I — contact intelligence, governance, offers, disclosure, drafts (deterministic)."""
from __future__ import annotations

import pytest

from core.scout.outreach.contacts import (
    governance_blockers,
    inferred_contact,
    is_draft_ready_contact,
    prefer_generic_over_named,
    public_contact,
)
from core.scout.outreach.disclosure import build_manifest, compute_draft_readiness
from core.scout.outreach.drafts import generate_draft
from core.scout.outreach.offers import map_offer

_NOW = "2026-07-17T09:00:00+00:00"


def _verified_generic():
    return public_contact("co-1", "one.example", "email", "hello@one.example",
                          evidence_ref="ev-1", observed_at=_NOW, verify=True,
                          suppression_check_ref="supp-1")


def test_inferred_contact_never_send_eligible():
    c = inferred_contact("co-1", "one.example", "email", "guess@one.example", observed_at=_NOW)
    assert c.status != "VERIFIED" and c.is_inferred_only
    assert not c.is_outreach_candidate
    assert "inferred_contact_not_send_eligible" in governance_blockers(
        c, company_suppressed=False, no_outreach=False, suppression_check_ref="s")


def test_named_person_requires_review():
    c = public_contact("co-1", "one.example", "email", "jane@one.example", evidence_ref="ev-1",
                       observed_at=_NOW, data_subject="named_person", verify=True,
                       suppression_check_ref="supp-1")
    assert c.manual_review_required and not c.is_outreach_candidate  # review not complete
    assert "named_person_review_incomplete" in governance_blockers(
        c, company_suppressed=False, no_outreach=False, suppression_check_ref="s")


def test_no_outreach_permanently_blocks_draft_readiness():
    c = _verified_generic()
    assert c.is_outreach_candidate
    assert not is_draft_ready_contact(c, company_suppressed=False, no_outreach=True,
                                      suppression_check_ref="supp-1")
    blockers = governance_blockers(c, company_suppressed=False, no_outreach=True,
                                   suppression_check_ref="supp-1")
    assert "NO_OUTREACH_suppression" in blockers


def test_verified_generic_contact_is_draft_ready_contact():
    c = _verified_generic()
    assert is_draft_ready_contact(c, company_suppressed=False, no_outreach=False,
                                  suppression_check_ref="supp-1")


def test_prefer_generic_over_named():
    generic = _verified_generic()
    named = public_contact("co-1", "one.example", "email", "jane@one.example", evidence_ref="ev-1",
                           observed_at=_NOW, data_subject="named_person", verify=True,
                           suppression_check_ref="supp-1", manual_review_ref="rev-1")
    assert prefer_generic_over_named([named, generic]).data_subject_category == "organization"


def test_offer_mapping():
    a11y = [{"capability": "accessibility", "severity": "medium", "evidence_ids": ["e1"]}]
    assert map_offer("co-1", a11y, "agency").offer_type == "Accessibility_Audit"
    many = [{"capability": c, "severity": "high", "evidence_ids": [f"e{i}"]}
            for i, c in enumerate(("accessibility", "performance", "seo"))]
    assert map_offer("co-1", many, "saas").offer_type == "Comprehensive_QA_Assessment"


def test_disclosure_ceilings_hold():
    findings = [{"finding_id": f"f{i}", "business_impact": "x", "evidence_ids": [f"e{i}"]}
                for i in range(5)]
    manifest = build_manifest("co-1", findings, stage="OUTREACH", contact_ref="c1",
                              suppression_check_ref="s1", revalidation_ref="r1", approval_ref="a1")
    assert len(manifest.items) == 2  # outreach_max_total ceiling
    # Without the approval reference the manifest is not ready (computed, not stored).
    unready = build_manifest("co-1", findings, stage="OUTREACH", contact_ref="c1",
                             suppression_check_ref="s1", revalidation_ref="r1")
    assert not unready.is_ready and "missing human approval reference" in unready.blockers


def test_draft_readiness_is_computed_and_fails_closed():
    base = dict(finding_client_safe=True, finding_active=True, contact_draft_ready=True,
                manifest_ready=True, suppression_check_ref="s1", policy_decision="approved",
                revalidation_ref="r1", human_reviewed=True)
    assert compute_draft_readiness(**base)["ready"]
    # A resolved finding cannot enter a draft.
    assert not compute_draft_readiness(**{**base, "finding_active": False})["ready"]
    # Forged approval: without human review it is not ready.
    r = compute_draft_readiness(**{**base, "human_reviewed": False})
    assert not r["ready"] and "human_review_required" in r["blockers"]


def test_draft_generation_is_safe_and_never_sent():
    contact = {"contact_id": "c1"}
    finding = {"title": "Missing alt text on the hero image", "business_impact": "Screen readers "
               "cannot perceive the image."}
    offer = {"offer_type": "Accessibility_Audit"}
    d = generate_draft("co-1", "One Co", contact, finding, offer, evidence_ref="ev-1",
                       source_refs=["src-1"], policy_refs=["pol-1"], generated_at=_NOW,
                       expires_at="2026-08-01T00:00:00+00:00")
    assert d.sent is False and d.review_state == "PENDING_REVIEW"
    assert d.content_hash.startswith("sha256:")
    assert "Hello," in d.body  # generic greeting; no guessed name
    for bad in ("urgent", "act now", "guaranteed", "you will lose"):
        assert bad not in d.body.lower()


def test_draft_rejects_forbidden_terms():
    contact = {"contact_id": "c1"}
    finding = {"title": "URGENT act now or you will lose sales", "business_impact": "x"}
    with pytest.raises(ValueError):
        generate_draft("co-1", "One Co", contact, finding, {"offer_type": "x"}, evidence_ref="e",
                       source_refs=[], policy_refs=[], generated_at=_NOW, expires_at="")

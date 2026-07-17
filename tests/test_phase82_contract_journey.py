"""Phase 8.2 — full synthetic contract integration journey (planning-only).

Ties the whole prospect contract family into one synthetic chain and proves the
cross-cutting safety invariants hold end to end:

Campaign -> CompanyIdentity -> SiteProfile -> BusinessFlowProfile -> CoverageMap
-> LeadScorecard -> ProspectLifecycle -> ContactRecord/ContactCollection
-> ProspectGovernancePlan -> DisclosureManifest

Nothing here executes: no runtime, browser, provider, network, lookup, sending, or
external action is invoked — the test only constructs and serializes dataclasses.
"""
from __future__ import annotations

import pytest

from core.schemas.source_reference import SourceReference
from core.schemas.prospect_campaign import ProspectCampaign
from core.schemas.prospect_interaction import InteractionBoundary, InteractionActionClass
from core.schemas.prospect_identity import CompanyIdentity, DomainIdentity
from core.schemas.prospect_business import BusinessContext, SiteProfile, BusinessFlowProfile
from core.schemas.prospect_coverage import CoverageArea, CoverageMap
from core.schemas.prospect_scoring import LeadScorecard, ScoreDimension
from core.schemas.prospect_lifecycle import ProspectLifecycle
from core.schemas.prospect_governance import ProspectGovernancePlan, SuppressionPolicy, RecheckPolicy
from core.schemas.prospect_contact import ContactProvenance, ContactRecord, ContactCollection
from core.schemas.prospect_disclosure import DisclosureItem, DisclosureManifest

_ISO = "2026-07-17T00:00:00+00:00"


def _verified_provenance():
    return ContactProvenance(
        source=SourceReference(url="https://acme.example/contact"),
        source_category="public_website",
        extraction_method="published_link",
        observed_at=_ISO,
        evidence_ref="EV-CONTACT-1",
        confidence="high",
        publicly_published_for_contact=True,
        terms_review_status="reviewed_ok",
    )


def _verified_contact(**kw):
    base = dict(
        company_ref="acme",
        channel="email",
        value="info@acme.example",
        data_subject_category="role_based",
        status="VERIFIED",
        provenance=[_verified_provenance()],
        last_verified_at=_ISO,
        suppression_check_ref="SUP-CHECK-1",
    )
    base.update(kw)
    return ContactRecord(**base)


def _outreach_item(finding_ref="F-1", role="primary"):
    return DisclosureItem(
        finding_ref=finding_ref, disclosure_level="OUTREACH_ELIGIBLE", role=role,
        storage_class="CLIENT_SAFE", sanitized=True, independently_verified=True,
        reproduction_detail_level="minimal",
        business_impact_summary="A public checkout step fails for real users.",
        evidence_refs=["EV-1"],
    )


def _ready_manifest(**kw):
    base = dict(
        prospect_ref="acme", stage="OUTREACH", items=[_outreach_item()],
        contact_ref="CONTACT-1", suppression_check_ref="SUP-1",
        pre_send_revalidation_ref="REVAL-1", approval_ref="APR-1",
    )
    base.update(kw)
    return DisclosureManifest(**base)


def _build_chain():
    """Construct one coherent, valid contract chain (planning-only)."""
    boundary = InteractionBoundary()  # fail-closed default
    campaign = ProspectCampaign(name="Berlin dental clinics", interaction_boundary=boundary)
    company = CompanyIdentity(
        canonical_name="Acme Clinic",
        domains=[DomainIdentity(hostname="acme.example", relation="primary", is_primary=True)],
    )
    business = BusinessContext(business_type="clinic", business_model="b2c")
    site = SiteProfile(domain_ref="acme.example", resource_type="corporate_site",
                       access_classification="public_open")
    flow = BusinessFlowProfile(flow_id="booking", flow_type="lead_capture", role="primary")
    coverage = CoverageMap(
        subject_ref="acme.example",
        areas=[CoverageArea(area="functional", status="PLANNED")],
    )
    scorecard = LeadScorecard(
        prospect_id="acme", priority="A",
        dimensions=[ScoreDimension(name="business_impact", value=90)],
    )
    lifecycle = ProspectLifecycle(status="DRAFT_READY")
    contacts = ContactCollection(company_ref="acme", contacts=[_verified_contact()])
    governance = ProspectGovernancePlan(
        suppression=SuppressionPolicy(enabled=True, mode="NO_OUTREACH", reason="opt-out"),
        recheck=RecheckPolicy(enabled=True, level="L1"),
    )
    manifest = _ready_manifest(contact_ref=contacts.contacts[0].contact_id)
    return {
        "campaign": campaign, "company": company, "business": business, "site": site,
        "flow": flow, "coverage": coverage, "scorecard": scorecard,
        "lifecycle": lifecycle, "contacts": contacts, "governance": governance,
        "manifest": manifest,
    }


class TestContractJourney:
    def test_full_chain_round_trips_stably(self):
        chain = _build_chain()
        for name, obj in chain.items():
            restored = type(obj).from_dict(obj.to_dict())
            assert restored.to_dict() == obj.to_dict(), f"{name} round trip unstable"

    def test_chain_is_ready_only_with_all_references(self):
        chain = _build_chain()
        assert chain["manifest"].outreach_ready is True
        assert chain["contacts"].contacts[0].is_outreach_candidate is True

    # --- malformed nested data fails closed (regression for the fail-closed hardening) ---
    @pytest.mark.parametrize(
        ("cls", "payload"),
        [
            (ProspectCampaign, {"source": "x"}),
            (ProspectCampaign, {"discovery_sources": ["x"]}),
            (ProspectCampaign, {"interaction_boundary": "x"}),
            (CompanyIdentity, {"domains": ["x"]}),
            (CompanyIdentity, {"sources": ["x"]}),
            (BusinessContext, {"sources": ["x"]}),
            (CoverageMap, {"areas": ["x"]}),
            (LeadScorecard, {"dimensions": ["x"]}),
            (ProspectLifecycle, {"history": ["x"]}),
            (ProspectGovernancePlan, {"suppression": "x"}),
            (ProspectGovernancePlan, {"retention": "x"}),
        ],
    )
    def test_malformed_nested_fails_closed(self, cls, payload):
        with pytest.raises(ValueError):
            cls.from_dict(payload)

    def test_absent_nested_still_defaults(self):
        # Absent keys are additive-safe (conservative defaults), only present-but-wrong-type fails.
        assert ProspectCampaign.from_dict({"name": "x"}).name == "x"
        assert ProspectGovernancePlan.from_dict({}).suppression.mode is not None

    def test_unsafe_action_classes_stay_blocked(self):
        b = InteractionBoundary(
            permitted_action_classes=[
                InteractionActionClass.DESTRUCTIVE.value,
                InteractionActionClass.FINANCIAL.value,
            ],
        )
        assert InteractionActionClass.DESTRUCTIVE.value not in b.permitted_action_classes
        assert InteractionActionClass.FINANCIAL.value not in b.permitted_action_classes
        assert InteractionActionClass.DESTRUCTIVE.value in b.blocked_action_classes
        assert b.captcha_bypass_allowed is False
        assert b.access_control_evasion_allowed is False
        assert b.proxy_or_stealth_evasion_allowed is False

    def test_lifecycle_cannot_skip_human_approval(self):
        lc = ProspectLifecycle(status="DRAFT_READY")
        with pytest.raises(ValueError):
            lc.apply_transition("CONTACTED")  # cannot reach outreach without approval
        lc2 = ProspectLifecycle(status="DRAFT_READY")
        lc2.apply_transition("APPROVED", actor="human", approval_ref="SOW-1")
        lc2.apply_transition("CONTACTED")
        assert lc2.status == "CONTACTED"

    def test_scoring_cannot_grant_outreach_authorization(self):
        # A top-priority, outreach_eligible scorecard does not make a manifest ready
        # nor a contact an outreach candidate — those depend on their own invariants.
        top = LeadScorecard(
            prospect_id="acme", priority="A", outreach_eligible=True,
            outreach_eligibility_ref="DECISION-1",
            dimensions=[ScoreDimension(name="business_impact", value=100)],
        )
        assert top.outreach_eligible is True
        manifest = _ready_manifest(contact_ref="", approval_ref="")  # missing refs
        assert manifest.outreach_ready is False
        unverified_contact = ContactRecord(channel="email", value="info@acme.example",
                                           status="PUBLIC_OBSERVED")
        assert unverified_contact.is_outreach_candidate is False

    def test_inferred_contact_cannot_verify(self):
        with pytest.raises(ValueError):
            ContactRecord(
                channel="email", value="guess@acme.example", status="VERIFIED",
                provenance=[ContactProvenance(source_category="inferred_candidate",
                                              extraction_method="inferred_pattern")],
                last_verified_at=_ISO,
            )

    def test_named_person_review_cannot_be_bypassed(self):
        c = _verified_contact(value="jane.doe@acme.example",
                              data_subject_category="named_person")
        assert c.manual_review_required is True
        assert c.is_outreach_candidate is False   # no completed review reference
        c.manual_review_ref = "REVIEW-1"
        assert c.is_outreach_candidate is True

    def test_suppression_blocks_readiness(self):
        # A suppressed/DNC contact is never an outreach candidate.
        for status in ("SUPPRESSED", "DO_NOT_CONTACT"):
            c = ContactRecord(channel="email", value="info@acme.example", status=status)
            assert c.is_outreach_candidate is False
        # A manifest missing the suppression-check reference is blocked.
        m = _ready_manifest(suppression_check_ref="")
        assert m.outreach_ready is False
        assert any("suppression" in b for b in m.blockers)

    @pytest.mark.parametrize("missing", ["contact_ref", "suppression_check_ref",
                                         "pre_send_revalidation_ref", "approval_ref"])
    def test_missing_reference_blocks_disclosure_readiness(self, missing):
        m = _ready_manifest(**{missing: ""})
        assert m.outreach_ready is False

    def test_unsanitized_evidence_blocks_disclosure(self):
        with pytest.raises(ValueError):
            DisclosureItem(finding_ref="F", disclosure_level="OUTREACH_ELIGIBLE",
                           storage_class="CLIENT_SAFE", sanitized=False,
                           independently_verified=True)

    def test_forged_readiness_cannot_override_computed(self):
        m = _ready_manifest()
        data = m.to_dict()
        data["outreach_ready"] = True   # not a field; ignored
        data["is_ready"] = True         # not a field; ignored
        data["contact_ref"] = ""        # real blocker
        restored = DisclosureManifest.from_dict(data)
        assert restored.outreach_ready is False

    def test_no_runtime_side_effect_methods_exist(self):
        # None of the contract objects expose a send/fetch/execute surface.
        forbidden = {"send", "fetch", "submit", "execute", "crawl", "lookup", "deliver"}
        for obj in _build_chain().values():
            attrs = {a for a in dir(obj) if not a.startswith("_")}
            assert not (attrs & forbidden), f"{type(obj).__name__} exposes runtime surface"

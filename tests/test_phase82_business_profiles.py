"""Phase 8.2 — business & site profile contract tests (slice 2).

Covers BusinessContext, SiteProfile, BusinessFlowProfile, CoverageMap/CoverageArea,
and SiteFingerprint. Planning/contracts only — nothing executes, crawls, or accesses
a site.
"""
from __future__ import annotations

import pytest

from core.schemas.source_reference import SourceReference
from core.schemas.prospect_interaction import PROSPECT_CONTRACT_SCHEMA_VERSION
from core.schemas.prospect_business import (
    BusinessContext,
    BusinessFlowProfile,
    SiteProfile,
)
from core.schemas.prospect_coverage import (
    COVERAGE_PLANNING_SAFE_STATUSES,
    CoverageArea,
    CoverageMap,
    SiteFingerprint,
)

# sha256("") — a valid 64-hex digest used across fingerprint tests.
_SHA256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


class TestBusinessContext:
    def test_unknown_classification_is_explicit_default(self):
        bc = BusinessContext()
        assert bc.business_type == "unknown"
        assert bc.business_model == "unknown"
        assert bc.confidence == "low"
        assert bc.schema_version == PROSPECT_CONTRACT_SCHEMA_VERSION

    def test_confidence_is_bounded(self):
        with pytest.raises(ValueError):
            BusinessContext(confidence="certain")
        with pytest.raises(ValueError):
            BusinessContext(confidence="0.99")
        for level in ("high", "medium", "low"):
            assert BusinessContext(confidence=level).confidence == level

    def test_unknown_business_type_and_model_rejected(self):
        with pytest.raises(ValueError):
            BusinessContext(business_type="mystery")
        with pytest.raises(ValueError):
            BusinessContext(business_model="pyramid")

    def test_signals_are_not_conclusions(self):
        # commercial_capacity_signals are stored as-is; nothing derives ability to pay.
        bc = BusinessContext(commercial_capacity_signals=["paid ads", "多店舗"])
        assert bc.commercial_capacity_signals == ["paid ads", "多店舗"]

    def test_round_trip_with_sources(self):
        bc = BusinessContext(
            business_type="ecommerce",
            business_model="b2c",
            countries=["DE"],
            confidence="medium",
            sources=[SourceReference(url="https://example.com", platform="web")],
        )
        restored = BusinessContext.from_dict(bc.to_dict())
        assert restored.to_dict() == bc.to_dict()
        assert isinstance(restored.sources[0], SourceReference)
        assert restored.sources[0].url == "https://example.com"

    def test_no_shared_default_mutation(self):
        a = BusinessContext()
        b = BusinessContext()
        a.countries.append("US")
        a.sources.append(SourceReference())
        assert b.countries == []
        assert b.sources == []


class TestSiteProfile:
    def test_defaults_explicit_unknown(self):
        sp = SiteProfile()
        assert sp.resource_type == "unknown"
        assert sp.access_classification == "unknown"
        assert sp.mobile_importance == "unknown"
        assert sp.classification_confidence == "low"

    def test_public_and_authenticated_surfaces_are_separate(self):
        sp = SiteProfile(
            public_surfaces=["/", "/products"],
            authenticated_surfaces=["/account"],
            access_classification="partially_protected",
        )
        assert sp.public_surfaces == ["/", "/products"]
        assert sp.authenticated_surfaces == ["/account"]
        # An authenticated surface is never present in the public list.
        assert set(sp.public_surfaces).isdisjoint(sp.authenticated_surfaces)

    def test_unknown_enums_fail_closed(self):
        with pytest.raises(ValueError):
            SiteProfile(resource_type="banana")
        with pytest.raises(ValueError):
            SiteProfile(mobile_importance="critical")
        with pytest.raises(ValueError):
            SiteProfile(access_classification="root")
        with pytest.raises(ValueError):
            SiteProfile(classification_confidence="sure")

    def test_round_trip(self):
        sp = SiteProfile(domain_ref="example.com", resource_type="saas", seo_importance="high")
        assert SiteProfile.from_dict(sp.to_dict()).to_dict() == sp.to_dict()

    def test_no_shared_default_mutation(self):
        a = SiteProfile()
        b = SiteProfile()
        a.technology_indicators.append("react")
        assert b.technology_indicators == []


class TestBusinessFlowProfile:
    def test_defaults(self):
        f = BusinessFlowProfile()
        assert f.flow_type == "unknown"
        assert f.role == "primary"
        assert f.criticality == "medium"
        assert f.planned_interaction_action_class == "READ_ONLY"

    def test_required_capabilities_validated(self):
        # Known atomic capability accepted; unknown fails closed.
        f = BusinessFlowProfile(required_capabilities=["web_navigation", "dom_inspection"])
        assert f.required_capabilities == ["web_navigation", "dom_inspection"]
        with pytest.raises(ValueError):
            BusinessFlowProfile(required_capabilities=["telepathy"])

    def test_unknown_action_class_rejected(self):
        with pytest.raises(ValueError):
            BusinessFlowProfile(planned_interaction_action_class="SUPER_ADMIN")

    def test_unknown_enums_rejected(self):
        with pytest.raises(ValueError):
            BusinessFlowProfile(flow_type="teleport")
        with pytest.raises(ValueError):
            BusinessFlowProfile(role="tertiary")
        with pytest.raises(ValueError):
            BusinessFlowProfile(criticality="apocalyptic")

    def test_round_trip(self):
        f = BusinessFlowProfile(
            flow_id="f1",
            flow_type="checkout",
            criticality="critical",
            affects_revenue=True,
            required_capabilities=["web_navigation"],
            planned_interaction_action_class="POTENTIAL_BUSINESS_SIDE_EFFECT",
        )
        assert BusinessFlowProfile.from_dict(f.to_dict()).to_dict() == f.to_dict()


class TestCoverageArea:
    def test_planning_safe_defaults(self):
        area = CoverageArea(area="accessibility")
        assert area.status == "PLANNED"
        assert "PLANNED" in COVERAGE_PLANNING_SAFE_STATUSES

    @pytest.mark.parametrize("status", ["PLANNED", "BLOCKED", "DEFERRED", "NOT_APPLICABLE"])
    def test_planning_safe_statuses_need_no_evidence(self, status):
        area = CoverageArea(area="perf", status=status)
        assert area.status == status

    def test_covered_requires_evidence(self):
        with pytest.raises(ValueError):
            CoverageArea(area="a11y", status="COVERED")
        # With evidence or a verification reference it is allowed.
        assert CoverageArea(area="a11y", status="COVERED", evidence_refs=["EV-1"]).status == "COVERED"
        assert CoverageArea(area="a11y", status="COVERED", verification_ref="VER-1").status == "COVERED"

    def test_partial_requires_evidence(self):
        with pytest.raises(ValueError):
            CoverageArea(area="seo", status="PARTIAL")
        assert CoverageArea(area="seo", status="PARTIAL", evidence_refs=["EV-2"]).status == "PARTIAL"

    def test_blocked_is_not_complete(self):
        # A blocked area carries no evidence and is never treated as covered.
        area = CoverageArea(area="checkout", status="BLOCKED", reason="auth required")
        assert area.status == "BLOCKED"
        assert area.evidence_refs == []

    def test_authenticated_area_cannot_claim_covered_without_evidence(self):
        with pytest.raises(ValueError):
            CoverageArea(
                area="account_dashboard",
                status="COVERED",
                access_dependency="authenticated_required",
            )

    def test_capability_refs_validated(self):
        with pytest.raises(ValueError):
            CoverageArea(area="x", capability_refs=["mind_reading"])
        assert CoverageArea(area="x", capability_refs=["evidence_collection"]).area == "x"

    def test_unknown_status_fails_closed(self):
        with pytest.raises(ValueError):
            CoverageArea(area="x", status="DONE")


class TestCoverageMap:
    def test_round_trip(self):
        cm = CoverageMap(
            subject_ref="example.com",
            areas=[
                CoverageArea(area="a11y", status="PLANNED"),
                CoverageArea(area="perf", status="DEFERRED", reason="budget"),
            ],
        )
        restored = CoverageMap.from_dict(cm.to_dict())
        assert restored.to_dict() == cm.to_dict()
        assert all(isinstance(a, CoverageArea) for a in restored.areas)

    def test_no_commercial_fields(self):
        # QA coverage and commercial opportunity are separate concepts.
        cm = CoverageMap()
        keys = set(cm.to_dict().keys())
        assert not (keys & {"lead_score", "commercial_value", "priority", "revenue"})

    def test_no_shared_default_mutation(self):
        a = CoverageMap()
        b = CoverageMap()
        a.areas.append(CoverageArea(area="x"))
        assert b.areas == []


class TestSiteFingerprint:
    def test_defaults_and_round_trip(self):
        fp = SiteFingerprint(subject_ref="example.com", content_fingerprint=_SHA256)
        assert fp.comparison_status == "unknown"
        assert fp.fingerprint_algorithm == "sha256"
        assert SiteFingerprint.from_dict(fp.to_dict()).to_dict() == fp.to_dict()

    def test_empty_planning_values_allowed(self):
        # An incomplete planning record may leave fingerprint values empty.
        fp = SiteFingerprint(subject_ref="example.com")
        assert fp.content_fingerprint == ""
        assert SiteFingerprint.from_dict(fp.to_dict()).to_dict() == fp.to_dict()

    def test_valid_sha256_digest_accepted(self):
        fp = SiteFingerprint(
            content_fingerprint=_SHA256,
            structural_fingerprint=_SHA256,
            commercial_flow_fingerprint=_SHA256,
        )
        assert fp.content_fingerprint == _SHA256

    def test_invalid_digest_length_rejected(self):
        with pytest.raises(ValueError):
            SiteFingerprint(content_fingerprint="abc123")

    def test_non_hex_digest_rejected(self):
        with pytest.raises(ValueError):
            SiteFingerprint(content_fingerprint="z" * 64)

    def test_raw_secret_in_fingerprint_value_rejected(self):
        with pytest.raises(ValueError):
            SiteFingerprint(structural_fingerprint="https://user:pass@example.com/path")

    def test_digest_case_normalized_lowercase(self):
        fp = SiteFingerprint(content_fingerprint=_SHA256.upper())
        assert fp.content_fingerprint == _SHA256

    def test_unsupported_algorithm_rejected(self):
        with pytest.raises(ValueError):
            SiteFingerprint(fingerprint_algorithm="md5", content_fingerprint="a" * 32)

    def test_inputs_are_deterministic(self):
        fp = SiteFingerprint(fingerprint_inputs=["b", "a", "b", "c"])
        assert fp.fingerprint_inputs == ["a", "b", "c"]

    @pytest.mark.parametrize("bad", [
        "session_id=xyz",
        "Cookie: sid=1",
        "authorization header",
        "bearer eyJ",
        "user_password",
        "api_key value",
    ])
    def test_forbidden_fingerprint_inputs_rejected(self, bad):
        with pytest.raises(ValueError):
            SiteFingerprint(fingerprint_inputs=[bad])

    def test_unknown_comparison_status_rejected(self):
        with pytest.raises(ValueError):
            SiteFingerprint(comparison_status="maybe")

    def test_round_trip_with_sources(self):
        fp = SiteFingerprint(
            subject_ref="example.com",
            fingerprint_inputs=["dom-structure", "nav-links"],
            source_refs=[SourceReference(url="https://example.com")],
            comparison_status="new",
        )
        restored = SiteFingerprint.from_dict(fp.to_dict())
        assert restored.to_dict() == fp.to_dict()
        assert isinstance(restored.source_refs[0], SourceReference)

    def test_no_shared_default_mutation(self):
        a = SiteFingerprint()
        b = SiteFingerprint()
        a.notes.append("x")
        assert b.notes == []


class TestSlice2Hardening:
    """Slice-2 hardening invariants (A1, A2, A4, A5)."""

    # --- A1: business type vs resource type are independent vocabularies ---
    def test_business_type_and_resource_type_independent(self):
        bc = BusinessContext(business_type="clinic")
        sp = SiteProfile(resource_type="booking_site")
        assert bc.business_type == "clinic"
        assert sp.resource_type == "booking_site"

    def test_business_only_value_rejected_as_resource(self):
        BusinessContext(business_type="clinic")
        with pytest.raises(ValueError):
            SiteProfile(resource_type="clinic")

    def test_resource_only_value_rejected_as_business(self):
        SiteProfile(resource_type="booking_site")
        with pytest.raises(ValueError):
            BusinessContext(business_type="booking_site")

    def test_backward_compatible_shared_values_still_accepted(self):
        assert BusinessContext(business_type="ecommerce").business_type == "ecommerce"
        assert SiteProfile(resource_type="saas").resource_type == "saas"

    # --- A2: site surface consistency ---
    def test_overlapping_surfaces_rejected(self):
        with pytest.raises(ValueError):
            SiteProfile(
                public_surfaces=["/shared"],
                authenticated_surfaces=["/shared"],
                access_classification="partially_protected",
            )

    def test_surfaces_deduplicated(self):
        sp = SiteProfile(
            public_surfaces=["/", "/", "/products"],
            authenticated_surfaces=["/account", "/account"],
            access_classification="partially_protected",
        )
        assert sp.public_surfaces == ["/", "/products"]
        assert sp.authenticated_surfaces == ["/account"]

    def test_public_open_cannot_have_authenticated_surfaces(self):
        with pytest.raises(ValueError):
            SiteProfile(
                access_classification="public_open",
                authenticated_surfaces=["/account"],
            )

    def test_partially_protected_allows_disjoint_both(self):
        sp = SiteProfile(
            public_surfaces=["/"],
            authenticated_surfaces=["/account"],
            access_classification="partially_protected",
        )
        assert sp.public_surfaces == ["/"]
        assert sp.authenticated_surfaces == ["/account"]
        assert SiteProfile.from_dict(sp.to_dict()).to_dict() == sp.to_dict()

    # --- A4: destructive is never a planned interaction class ---
    def test_destructive_planned_class_rejected(self):
        with pytest.raises(ValueError):
            BusinessFlowProfile(planned_interaction_action_class="DESTRUCTIVE")

    def test_non_destructive_planned_classes_allowed(self):
        for cls in (
            "READ_ONLY", "REVERSIBLE_SESSION_WRITE", "POTENTIAL_BUSINESS_SIDE_EFFECT",
            "EXTERNAL_COMMUNICATION", "FINANCIAL",
        ):
            f = BusinessFlowProfile(planned_interaction_action_class=cls)
            assert f.planned_interaction_action_class == cls

    # --- A5: coverage contract hygiene ---
    def test_empty_area_rejected(self):
        with pytest.raises(ValueError):
            CoverageArea(area="   ")

    def test_blank_evidence_ref_rejected(self):
        with pytest.raises(ValueError):
            CoverageArea(area="a11y", status="COVERED", evidence_refs=["  "])

    def test_covered_with_blank_verification_rejected(self):
        with pytest.raises(ValueError):
            CoverageArea(area="a11y", status="COVERED", verification_ref="   ")

    def test_capability_and_evidence_refs_deduped(self):
        area = CoverageArea(
            area="perf",
            status="COVERED",
            evidence_refs=["EV-1", "EV-1", "EV-2"],
            capability_refs=["web_navigation", "web_navigation"],
        )
        assert area.evidence_refs == ["EV-1", "EV-2"]
        assert area.capability_refs == ["web_navigation"]


class TestExistingSchemaCompatibility:
    def test_existing_schemas_still_import(self):
        # Adding slice-2 schemas must not break existing schema imports.
        from core.schemas.prospect_campaign import ProspectCampaign
        from core.schemas.finding import Finding, Confidence  # noqa: F401
        assert ProspectCampaign().schema_version == PROSPECT_CONTRACT_SCHEMA_VERSION

    def test_access_status_and_commercial_context_are_independent(self):
        # A protected site is not a commercial verdict; the two schemas don't couple.
        sp = SiteProfile(access_classification="authenticated_required")
        bc = BusinessContext(business_type="saas")
        assert "business_type" not in sp.to_dict()
        assert "access_classification" not in bc.to_dict()

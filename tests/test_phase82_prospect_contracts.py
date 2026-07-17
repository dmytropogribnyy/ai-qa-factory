"""Phase 8.2 — Prospect planning-contract tests (slice 1).

Covers campaign definition, target criteria, market policy, discovery-source policy,
and the fail-closed interaction boundary + action classes. These are planning/contract
schemas only — no runtime, network, browser, or MCP behavior is exercised.
"""
from __future__ import annotations

import pytest

from core.schemas.prospect_campaign import (
    CAMPAIGN_STATUSES,
    CampaignTargetCriteria,
    DiscoverySourcePolicy,
    MarketPolicy,
    ProspectCampaign,
)
from core.schemas.prospect_interaction import (
    PROSPECT_CONTRACT_SCHEMA_VERSION,
    InteractionActionClass,
    InteractionBoundary,
)


class TestCampaignBasics:
    def test_minimal_valid_campaign(self):
        c = ProspectCampaign(name="Berlin dental clinics")
        assert c.name == "Berlin dental clinics"
        assert c.status == "DRAFT"
        assert c.status in CAMPAIGN_STATUSES
        assert c.schema_version == PROSPECT_CONTRACT_SCHEMA_VERSION
        assert c.id  # uuid generated

    def test_schema_version_present(self):
        assert ProspectCampaign().schema_version == PROSPECT_CONTRACT_SCHEMA_VERSION
        assert InteractionBoundary().schema_version == PROSPECT_CONTRACT_SCHEMA_VERSION

    def test_unknown_status_rejected(self):
        with pytest.raises(ValueError):
            ProspectCampaign(status="EXECUTING")

    def test_full_campaign_round_trip(self):
        c = ProspectCampaign(
            name="EU e-commerce audit radar",
            status="PLANNED",
            owner="growth-team",
            target_criteria=CampaignTargetCriteria(
                countries=["DE", "AT"],
                industries=["ecommerce"],
                required_flows=["checkout"],
                min_commercial_qualification=60,
                exploration_budget_pct=25.0,
                max_targets=100,
                max_pages_per_target=20,
                max_sessions_planned=50,
            ),
            market_policy=MarketPolicy(
                market_id="DE",
                allowed_discovery_source_categories=["search_engine", "business_directory"],
                allowed_contact_source_categories=["public_website"],
                allowed_outreach_channels=["none"],
                legal_review_status="in_review",
            ),
            discovery_sources=[
                DiscoverySourcePolicy(source_category="search_engine", trust_level="medium"),
                DiscoverySourcePolicy(source_category="business_directory"),
            ],
        )
        restored = ProspectCampaign.from_dict(c.to_dict())
        assert restored.to_dict() == c.to_dict()
        assert restored.name == c.name
        assert restored.status == "PLANNED"
        assert len(restored.discovery_sources) == 2
        assert restored.target_criteria.countries == ["DE", "AT"]
        assert restored.market_policy.market_id == "DE"

    def test_safe_defaults(self):
        c = ProspectCampaign()
        # Discovery-source list empty; boundary conservative; no outreach by default.
        assert c.discovery_sources == []
        assert c.market_policy.allowed_outreach_channels == ["none"]
        assert c.market_policy.manual_review_required is True
        assert c.interaction_boundary.permitted_action_classes == [
            InteractionActionClass.READ_ONLY.value
        ]

    def test_no_shared_default_mutation(self):
        a = ProspectCampaign()
        b = ProspectCampaign()
        a.notes.append("x")
        a.discovery_sources.append(DiscoverySourcePolicy())
        assert b.notes == []
        assert b.discovery_sources == []
        # Nested boundary defaults are independent too.
        a.interaction_boundary.notes.append("y")
        assert b.interaction_boundary.notes == []


class TestTargetCriteria:
    def test_invalid_exploration_percentage(self):
        with pytest.raises(ValueError):
            CampaignTargetCriteria(exploration_budget_pct=120.0)
        with pytest.raises(ValueError):
            CampaignTargetCriteria(exploration_budget_pct=-1.0)

    def test_invalid_qualification(self):
        with pytest.raises(ValueError):
            CampaignTargetCriteria(min_commercial_qualification=101)

    @pytest.mark.parametrize("field_kwargs", [
        {"max_targets": -1},
        {"max_pages_per_target": -5},
        {"max_sessions_planned": -2},
    ])
    def test_negative_limits_rejected(self, field_kwargs):
        with pytest.raises(ValueError):
            CampaignTargetCriteria(**field_kwargs)

    def test_round_trip(self):
        tc = CampaignTargetCriteria(countries=["FR"], exploration_budget_pct=10.0)
        assert CampaignTargetCriteria.from_dict(tc.to_dict()).to_dict() == tc.to_dict()


class TestMarketPolicy:
    def test_serialization(self):
        m = MarketPolicy(market_id="US", legal_review_status="reviewed_approved")
        assert MarketPolicy.from_dict(m.to_dict()).to_dict() == m.to_dict()

    def test_unknown_category_fails_closed(self):
        with pytest.raises(ValueError):
            MarketPolicy(allowed_discovery_source_categories=["darkweb_scrape"])
        with pytest.raises(ValueError):
            MarketPolicy(allowed_contact_source_categories=["stolen_db"])
        with pytest.raises(ValueError):
            MarketPolicy(allowed_outreach_channels=["cold_call_robot"])

    def test_unknown_legal_status_rejected(self):
        with pytest.raises(ValueError):
            MarketPolicy(legal_review_status="totally_legal_trust_me")

    def test_policy_cannot_auto_approve_outreach(self):
        # Allowing a real outreach channel must force manual review to stay required.
        m = MarketPolicy(
            allowed_outreach_channels=["email"],
            manual_review_required=False,
        )
        assert m.manual_review_required is True

    def test_respect_robots_cannot_be_disabled(self):
        m = MarketPolicy(respect_robots=False)
        assert m.respect_robots is True

    def test_none_cannot_coexist_with_real_channel(self):
        with pytest.raises(ValueError):
            MarketPolicy(allowed_outreach_channels=["none", "email"])
        # A real channel alone is fine (still approval-gated).
        m = MarketPolicy(allowed_outreach_channels=["email"])
        assert m.manual_review_required is True


class TestDiscoverySourcePolicy:
    def test_disabled_and_read_only_by_default(self):
        d = DiscoverySourcePolicy()
        assert d.enabled is False
        assert d.read_only is True
        assert d.public_only is True

    def test_planning_only_status(self):
        # Even an "enabled" source is only a planning candidate, never verified runtime.
        d = DiscoverySourcePolicy(source_category="search_engine", enabled=True)
        assert d.read_only is True
        assert d.provider_resolution_status in {"unresolved", "candidate", "planned_gap"}

    def test_unknown_status_rejected(self):
        # Hardened: an unknown provider status must fail closed (no silent rewrite,
        # and never an available/verified runtime state).
        with pytest.raises(ValueError):
            DiscoverySourcePolicy(provider_resolution_status="available")
        with pytest.raises(ValueError):
            DiscoverySourcePolicy(provider_resolution_status="verified")

    def test_unknown_category_rejected(self):
        with pytest.raises(ValueError):
            DiscoverySourcePolicy(source_category="mystery")

    def test_negative_budget_rejected(self):
        with pytest.raises(ValueError):
            DiscoverySourcePolicy(source_category="search_engine", max_requests_planned=-1)
        with pytest.raises(ValueError):
            DiscoverySourcePolicy(source_category="search_engine", estimated_cost_usd=-0.5)

    def test_round_trip(self):
        d = DiscoverySourcePolicy(source_category="map_listing", trust_level="high")
        assert DiscoverySourcePolicy.from_dict(d.to_dict()).to_dict() == d.to_dict()


class TestInteractionActionClass:
    def test_expected_classes_present(self):
        values = {c.value for c in InteractionActionClass}
        assert values == {
            "READ_ONLY",
            "REVERSIBLE_SESSION_WRITE",
            "POTENTIAL_BUSINESS_SIDE_EFFECT",
            "EXTERNAL_COMMUNICATION",
            "FINANCIAL",
            "DESTRUCTIVE",
        }

    def test_str_enum_serialization(self):
        assert InteractionActionClass.FINANCIAL == "FINANCIAL"
        assert InteractionActionClass("READ_ONLY") is InteractionActionClass.READ_ONLY


class TestInteractionBoundary:
    def test_default_is_fail_closed(self):
        b = InteractionBoundary()
        assert b.permitted_action_classes == [InteractionActionClass.READ_ONLY.value]
        assert b.public_access_only is True
        assert b.authenticated_access_allowed is False
        assert b.real_submission_allowed is False
        assert b.account_creation_allowed is False
        assert b.order_creation_allowed is False
        assert b.booking_or_hold_allowed is False
        assert b.payment_allowed is False
        assert b.file_upload_allowed is False
        assert b.cleanup_required is True

    def test_destructive_always_blocked(self):
        b = InteractionBoundary(permitted_action_classes=["DESTRUCTIVE", "READ_ONLY"])
        # Destructive is stripped from permitted and guaranteed in blocked.
        assert "DESTRUCTIVE" not in b.permitted_action_classes
        assert "DESTRUCTIVE" in b.blocked_action_classes
        assert b.permitted_action_classes == ["READ_ONLY"]

    def test_approval_classes_cannot_be_permitted(self):
        b = InteractionBoundary(
            permitted_action_classes=[
                "READ_ONLY",
                "EXTERNAL_COMMUNICATION",
                "FINANCIAL",
                "POTENTIAL_BUSINESS_SIDE_EFFECT",
            ]
        )
        assert b.permitted_action_classes == ["READ_ONLY"]

    def test_financial_and_external_comm_require_approval(self):
        b = InteractionBoundary()
        assert "FINANCIAL" in b.approval_required_action_classes
        assert "EXTERNAL_COMMUNICATION" in b.approval_required_action_classes

    def test_captcha_bypass_cannot_be_enabled(self):
        b = InteractionBoundary(captcha_bypass_allowed=True)
        assert b.captcha_bypass_allowed is False

    def test_access_control_and_proxy_evasion_cannot_be_enabled(self):
        b = InteractionBoundary(
            access_control_evasion_allowed=True,
            proxy_or_stealth_evasion_allowed=True,
        )
        assert b.access_control_evasion_allowed is False
        assert b.proxy_or_stealth_evasion_allowed is False

    def test_unknown_action_class_rejected(self):
        with pytest.raises(ValueError):
            InteractionBoundary(permitted_action_classes=["SUPER_ADMIN"])

    def test_round_trip_stable_after_fail_closed_correction(self):
        b = InteractionBoundary(
            permitted_action_classes=["READ_ONLY", "FINANCIAL"],
            captcha_bypass_allowed=True,
        )
        d = b.to_dict()
        restored = InteractionBoundary.from_dict(d)
        # Rehydration re-applies the same fail-closed invariants — stable round trip.
        assert restored.to_dict() == d
        assert restored.permitted_action_classes == ["READ_ONLY"]
        assert restored.captcha_bypass_allowed is False


class TestInteractionBoundaryHardening:
    """Hardening invariants (Part A) for InteractionBoundary."""

    # --- 1. Mandatory approval classes ---
    def test_empty_approval_list_restores_mandatory_classes(self):
        b = InteractionBoundary(approval_required_action_classes=[])
        for cls in (
            "POTENTIAL_BUSINESS_SIDE_EFFECT",
            "EXTERNAL_COMMUNICATION",
            "FINANCIAL",
        ):
            assert cls in b.approval_required_action_classes

    def test_mandatory_restoration_is_deterministic(self):
        a = InteractionBoundary(approval_required_action_classes=[])
        b = InteractionBoundary(approval_required_action_classes=[])
        assert a.approval_required_action_classes == b.approval_required_action_classes

    def test_partial_approval_list_completed(self):
        b = InteractionBoundary(approval_required_action_classes=["FINANCIAL"])
        assert "POTENTIAL_BUSINESS_SIDE_EFFECT" in b.approval_required_action_classes
        assert "EXTERNAL_COMMUNICATION" in b.approval_required_action_classes
        assert "FINANCIAL" in b.approval_required_action_classes

    def test_mandatory_class_may_be_blocked_instead(self):
        # A mandatory approval class can disappear from approval ONLY if it is blocked
        # (which is stricter). It must never vanish from both.
        b = InteractionBoundary(
            approval_required_action_classes=[],
            blocked_action_classes=["FINANCIAL"],
        )
        assert "FINANCIAL" in b.blocked_action_classes
        assert "FINANCIAL" not in b.approval_required_action_classes
        assert "FINANCIAL" not in b.permitted_action_classes

    def test_duplicate_class_values_deduped(self):
        b = InteractionBoundary(
            approval_required_action_classes=["FINANCIAL", "FINANCIAL"],
            blocked_action_classes=["DESTRUCTIVE", "DESTRUCTIVE"],
        )
        assert b.approval_required_action_classes.count("FINANCIAL") == 1
        assert b.blocked_action_classes.count("DESTRUCTIVE") == 1

    def test_conflicting_lists_resolved_blocked_wins(self):
        # A class listed as permitted + approval + blocked ends up only blocked.
        b = InteractionBoundary(
            permitted_action_classes=["READ_ONLY", "FINANCIAL"],
            approval_required_action_classes=["FINANCIAL"],
            blocked_action_classes=["FINANCIAL"],
        )
        assert "FINANCIAL" not in b.permitted_action_classes
        assert "FINANCIAL" not in b.approval_required_action_classes
        assert "FINANCIAL" in b.blocked_action_classes

    def test_no_class_both_permitted_and_restricted(self):
        b = InteractionBoundary(
            permitted_action_classes=[
                "READ_ONLY", "POTENTIAL_BUSINESS_SIDE_EFFECT", "EXTERNAL_COMMUNICATION",
            ],
        )
        restricted = set(b.approval_required_action_classes) | set(b.blocked_action_classes)
        assert not (set(b.permitted_action_classes) & restricted)

    def test_round_trip_stable_after_mandatory_normalization(self):
        b = InteractionBoundary(approval_required_action_classes=[])
        d = b.to_dict()
        assert InteractionBoundary.from_dict(d).to_dict() == d

    # --- 2. Reversible session write requires cleanup ---
    def test_reversible_write_forces_cleanup(self):
        b = InteractionBoundary(
            permitted_action_classes=["READ_ONLY", "REVERSIBLE_SESSION_WRITE"],
            cleanup_required=False,
        )
        assert "REVERSIBLE_SESSION_WRITE" in b.permitted_action_classes
        assert b.cleanup_required is True

    def test_no_reversible_write_leaves_cleanup_choice(self):
        b = InteractionBoundary(cleanup_required=True)
        assert b.cleanup_required is True

    # --- 3. Public vs authenticated ---
    def test_public_only_forces_authenticated_off(self):
        b = InteractionBoundary(
            public_access_only=True,
            authenticated_access_allowed=True,
            written_authorization_ref="AUTH-123",
        )
        assert b.authenticated_access_allowed is False

    def test_public_only_forces_authenticated_off_on_rehydration(self):
        data = InteractionBoundary().to_dict()
        data["public_access_only"] = True
        data["authenticated_access_allowed"] = True
        data["written_authorization_ref"] = "AUTH-123"
        restored = InteractionBoundary.from_dict(data)
        assert restored.authenticated_access_allowed is False

    # --- 5. Side-effect flags require written authorization ---
    @pytest.mark.parametrize("flag", [
        "authenticated_access_allowed",
        "real_submission_allowed",
        "account_creation_allowed",
        "order_creation_allowed",
        "booking_or_hold_allowed",
        "payment_allowed",
        "file_upload_allowed",
    ])
    def test_side_effect_flag_requires_written_authorization(self, flag):
        kwargs = {flag: True, "public_access_only": False}
        with pytest.raises(ValueError):
            InteractionBoundary(**kwargs)

    def test_payment_keeps_financial_approval_required(self):
        b = InteractionBoundary(
            payment_allowed=True,
            public_access_only=False,
            written_authorization_ref="AUTH-9",
        )
        assert "FINANCIAL" in b.approval_required_action_classes
        assert "FINANCIAL" not in b.permitted_action_classes

    def test_submission_keeps_external_comm_approval_required(self):
        b = InteractionBoundary(
            real_submission_allowed=True,
            public_access_only=False,
            written_authorization_ref="AUTH-9",
        )
        assert "EXTERNAL_COMMUNICATION" in b.approval_required_action_classes

    def test_order_keeps_business_side_effect_approval_required(self):
        b = InteractionBoundary(
            order_creation_allowed=True,
            public_access_only=False,
            written_authorization_ref="AUTH-9",
        )
        assert "POTENTIAL_BUSINESS_SIDE_EFFECT" in b.approval_required_action_classes

    def test_evasion_impossible_even_with_authorization(self):
        b = InteractionBoundary(
            payment_allowed=True,
            public_access_only=False,
            written_authorization_ref="AUTH-9",
            captcha_bypass_allowed=True,
            access_control_evasion_allowed=True,
            proxy_or_stealth_evasion_allowed=True,
        )
        assert b.captcha_bypass_allowed is False
        assert b.access_control_evasion_allowed is False
        assert b.proxy_or_stealth_evasion_allowed is False

    def test_valid_authorized_planning_example(self):
        # A coherent, authorized, still-fail-closed planning boundary round-trips.
        b = InteractionBoundary(
            permitted_action_classes=["READ_ONLY", "REVERSIBLE_SESSION_WRITE"],
            public_access_only=False,
            authenticated_access_allowed=True,
            real_submission_allowed=True,
            payment_allowed=True,
            written_authorization_ref="SOW-2026-07-17",
        )
        assert b.cleanup_required is True
        assert b.authenticated_access_allowed is True
        assert "FINANCIAL" in b.approval_required_action_classes
        assert "EXTERNAL_COMMUNICATION" in b.approval_required_action_classes
        assert b.captcha_bypass_allowed is False
        assert InteractionBoundary.from_dict(b.to_dict()).to_dict() == b.to_dict()



    def test_unknown_keys_ignored(self):
        # Additive-safe: an artifact with a future field still rehydrates.
        data = ProspectCampaign(name="x").to_dict()
        data["future_only_field"] = {"anything": 1}
        restored = ProspectCampaign.from_dict(data)
        assert restored.name == "x"

    def test_boundary_unknown_keys_ignored(self):
        data = InteractionBoundary().to_dict()
        data["experimental_flag"] = True
        restored = InteractionBoundary.from_dict(data)
        assert restored.schema_version == PROSPECT_CONTRACT_SCHEMA_VERSION

"""Phase 8.2 — identity, lifecycle, suppression, retention & recheck tests (slice 3).

Planning/contracts only — no DNS, network, scheduler, filesystem, or outreach runtime.
"""
from __future__ import annotations

import pytest

from core.schemas.source_reference import SourceReference
from core.schemas.cleanup import CleanupPolicy
from core.schemas.prospect_interaction import PROSPECT_CONTRACT_SCHEMA_VERSION
from core.schemas.prospect_identity import (
    CompanyIdentity,
    DomainIdentity,
    normalize_hostname,
)
from core.schemas.prospect_lifecycle import (
    ALLOWED_TRANSITIONS,
    PROSPECT_STATE_SET,
    TERMINAL_STATES,
    ProspectLifecycle,
    is_transition_allowed,
)
from core.schemas.prospect_governance import (
    ProspectGovernancePlan,
    ProspectRetentionPolicy,
    RecheckPolicy,
    SuppressionPolicy,
)


class TestDomainIdentity:
    def test_hostname_normalized_lowercase_and_trailing_dot(self):
        d = DomainIdentity(hostname="Example.COM.")
        assert d.hostname == "example.com"

    def test_normalize_hostname_helper(self):
        assert normalize_hostname("  WWW.Example.com  ") == "www.example.com"

    @pytest.mark.parametrize("bad", [
        "https://example.com",
        "example.com/path",
        "example.com?q=1",
        "example.com#frag",
        "user:pass@example.com",
        "example.com:8080",
        "exa mple.com",
        "",
        "   ",
        "localhost",
        "singlelabel",
    ])
    def test_invalid_hostname_rejected(self, bad):
        with pytest.raises(ValueError):
            DomainIdentity(hostname=bad)

    def test_unknown_relation_rejected(self):
        with pytest.raises(ValueError):
            DomainIdentity(hostname="example.com", relation="mirror")

    def test_unknown_confidence_rejected(self):
        with pytest.raises(ValueError):
            DomainIdentity(hostname="example.com", confidence="certain")

    def test_round_trip_with_sources(self):
        d = DomainIdentity(
            hostname="example.com",
            relation="primary",
            is_primary=True,
            sources=[SourceReference(url="https://example.com")],
            confidence="high",
        )
        restored = DomainIdentity.from_dict(d.to_dict())
        assert restored.to_dict() == d.to_dict()
        assert isinstance(restored.sources[0], SourceReference)


class TestCompanyIdentity:
    def test_one_company_many_domains(self):
        c = CompanyIdentity(
            canonical_name="Acme",
            domains=[
                DomainIdentity(hostname="acme.com", relation="primary", is_primary=True),
                DomainIdentity(hostname="acme.io", relation="brand"),
            ],
        )
        assert len(c.domains) == 2

    def test_duplicate_domain_rejected(self):
        with pytest.raises(ValueError):
            CompanyIdentity(domains=[
                DomainIdentity(hostname="acme.com"),
                DomainIdentity(hostname="Acme.com"),  # same canonical hostname
            ])

    def test_multiple_primary_domains_rejected(self):
        with pytest.raises(ValueError):
            CompanyIdentity(domains=[
                DomainIdentity(hostname="acme.com", is_primary=True),
                DomainIdentity(hostname="acme.io", is_primary=True),
            ])

    def test_brand_and_alias_dedup(self):
        c = CompanyIdentity(
            brand_names=["Acme", "Acme"],
            aliases=["ACME Corp", "ACME Corp"],
        )
        assert c.brand_names == ["Acme"]
        assert c.aliases == ["ACME Corp"]

    def test_unknown_confidence_rejected(self):
        with pytest.raises(ValueError):
            CompanyIdentity(confidence="definitely")

    def test_round_trip(self):
        c = CompanyIdentity(
            canonical_name="Acme",
            legal_name="Acme LLC",
            brand_names=["Acme"],
            domains=[DomainIdentity(hostname="acme.com", is_primary=True)],
            sources=[SourceReference(url="https://acme.com")],
            confidence="medium",
        )
        restored = CompanyIdentity.from_dict(c.to_dict())
        assert restored.to_dict() == c.to_dict()
        assert isinstance(restored.domains[0], DomainIdentity)
        assert isinstance(restored.sources[0], SourceReference)

    def test_identity_has_no_contact_or_score_fields(self):
        keys = set(CompanyIdentity().to_dict().keys())
        assert not (keys & {"email", "phone", "contacts", "lead_score", "priority"})

    def test_no_shared_default_mutation(self):
        a = CompanyIdentity()
        b = CompanyIdentity()
        a.brand_names.append("X")
        a.domains.append(DomainIdentity(hostname="x.com"))
        assert b.brand_names == []
        assert b.domains == []


class TestProspectLifecycle:
    def test_default_state(self):
        lc = ProspectLifecycle()
        assert lc.status == "DISCOVERED"
        assert lc.state_version == 0
        assert lc.schema_version == PROSPECT_CONTRACT_SCHEMA_VERSION

    def test_unknown_state_rejected(self):
        with pytest.raises(ValueError):
            ProspectLifecycle(status="LAUNCHED")

    def test_valid_transition(self):
        lc = ProspectLifecycle()
        lc.apply_transition("ELIGIBLE", reason="passed prescreen", actor="cli")
        assert lc.status == "ELIGIBLE"
        assert lc.previous_status == "DISCOVERED"
        assert lc.state_version == 1
        assert lc.history[-1].to_state == "ELIGIBLE"

    def test_invalid_transition_rejected(self):
        lc = ProspectLifecycle()
        with pytest.raises(ValueError):
            lc.apply_transition("PAID_AUDIT")

    def test_contacted_requires_approved_lineage(self):
        # Cannot reach CONTACTED from DRAFT_READY directly.
        lc = ProspectLifecycle(status="DRAFT_READY")
        with pytest.raises(ValueError):
            lc.apply_transition("CONTACTED")
        # APPROVED -> CONTACTED is allowed.
        lc2 = ProspectLifecycle(status="APPROVED")
        lc2.apply_transition("CONTACTED")
        assert lc2.status == "CONTACTED"

    def test_terminal_states_have_no_outgoing(self):
        for state in TERMINAL_STATES:
            assert ALLOWED_TRANSITIONS.get(state, ()) == ()

    def test_transition_map_targets_are_known_states(self):
        for src, targets in ALLOWED_TRANSITIONS.items():
            assert src in PROSPECT_STATE_SET
            for t in targets:
                assert t in PROSPECT_STATE_SET

    def test_suppressed_and_archived_distinct(self):
        assert "SUPPRESSED" in PROSPECT_STATE_SET
        assert "ARCHIVED" in PROSPECT_STATE_SET
        assert is_transition_allowed("SUPPRESSED", "ARCHIVED")
        assert not is_transition_allowed("ARCHIVED", "SUPPRESSED")

    def test_history_round_trip(self):
        lc = ProspectLifecycle()
        lc.apply_transition("ELIGIBLE")
        lc.apply_transition("QUICK_SCANNED")
        restored = ProspectLifecycle.from_dict(lc.to_dict())
        assert restored.to_dict() == lc.to_dict()
        assert len(restored.history) == 2

    def test_stale_evidence_routes_to_recheck(self):
        lc = ProspectLifecycle(status="FINDING_VERIFIED")
        lc.apply_transition("EVIDENCE_EXPIRED")
        lc.apply_transition("NEEDS_RECHECK")
        assert lc.status == "NEEDS_RECHECK"


class TestSuppressionPolicy:
    def test_safe_default_disabled(self):
        s = SuppressionPolicy()
        assert s.enabled is False
        assert s.manual_override_required is True

    def test_enabled_requires_reason(self):
        with pytest.raises(ValueError):
            SuppressionPolicy(enabled=True, reason="  ")
        assert SuppressionPolicy(enabled=True, reason="opt-out").enabled is True

    def test_cooldown_requires_expiry(self):
        with pytest.raises(ValueError):
            SuppressionPolicy(enabled=True, mode="COOLDOWN", reason="rate")
        s = SuppressionPolicy(
            enabled=True, mode="COOLDOWN", reason="rate", expires_at="2026-08-01"
        )
        assert s.mode == "COOLDOWN"

    def test_modes_are_distinct(self):
        assert SuppressionPolicy(enabled=True, mode="NO_OUTREACH", reason="r").mode != \
            SuppressionPolicy(enabled=True, mode="NO_SCAN", reason="r").mode

    def test_unknown_mode_rejected(self):
        with pytest.raises(ValueError):
            SuppressionPolicy(mode="BLOCK_ALL")

    def test_domains_deduped(self):
        s = SuppressionPolicy(applies_to_domains=["a.com", "a.com", "b.com"])
        assert s.applies_to_domains == ["a.com", "b.com"]

    def test_round_trip(self):
        s = SuppressionPolicy(enabled=True, reason="legal", reference="TCK-1")
        assert SuppressionPolicy.from_dict(s.to_dict()).to_dict() == s.to_dict()


class TestProspectRetentionPolicy:
    def test_safe_defaults(self):
        r = ProspectRetentionPolicy()
        assert r.cleanup_policy.dry_run_required is True
        assert r.cleanup_policy.preserve_git_tracked_files is True
        assert r.cleanup_policy.preserve_client_outputs is True
        assert r.preserve_suppression_metadata is True
        assert r.preserve_identity_metadata is True

    def test_dry_run_cannot_be_disabled(self):
        r = ProspectRetentionPolicy(
            cleanup_policy=CleanupPolicy(dry_run_required=False)
        )
        assert r.cleanup_policy.dry_run_required is True

    def test_suppression_metadata_preserved_even_if_set_false(self):
        r = ProspectRetentionPolicy(preserve_suppression_metadata=False)
        assert r.preserve_suppression_metadata is True

    @pytest.mark.parametrize("field_name", [
        "retention_days_failed_eligibility",
        "retention_days_qualified",
        "evidence_retention_days",
    ])
    def test_negative_retention_rejected(self, field_name):
        with pytest.raises(ValueError):
            ProspectRetentionPolicy(**{field_name: -1})

    def test_unknown_archive_state_rejected(self):
        with pytest.raises(ValueError):
            ProspectRetentionPolicy(archive_state="delete_now")

    def test_round_trip(self):
        r = ProspectRetentionPolicy(retention_days_qualified=200)
        restored = ProspectRetentionPolicy.from_dict(r.to_dict())
        assert restored.to_dict() == r.to_dict()
        assert restored.cleanup_policy.dry_run_required is True


class TestRecheckPolicy:
    def test_safe_defaults(self):
        r = RecheckPolicy()
        assert r.pre_send_revalidation_required is True
        assert r.full_reaudit_allowed is False
        assert r.enabled is False

    def test_unknown_level_rejected(self):
        with pytest.raises(ValueError):
            RecheckPolicy(level="L9")

    def test_negative_durations_rejected(self):
        with pytest.raises(ValueError):
            RecheckPolicy(cooldown_days=-1)
        with pytest.raises(ValueError):
            RecheckPolicy(evidence_max_age_days=-5)

    def test_is_active_scan(self):
        assert RecheckPolicy(enabled=True, level="L2").is_active_scan is True
        assert RecheckPolicy(enabled=True, level="L0").is_active_scan is False
        assert RecheckPolicy(enabled=False, level="L4").is_active_scan is False
        assert RecheckPolicy(
            enabled=True, level="L0", change_detection_required=True
        ).is_active_scan is True

    def test_round_trip(self):
        r = RecheckPolicy(level="L3", enabled=True, cooldown_days=14)
        assert RecheckPolicy.from_dict(r.to_dict()).to_dict() == r.to_dict()


class TestProspectGovernancePlan:
    def test_no_scan_conflicts_with_active_recheck(self):
        with pytest.raises(ValueError):
            ProspectGovernancePlan(
                suppression=SuppressionPolicy(
                    enabled=True, mode="NO_SCAN", reason="opt-out"
                ),
                recheck=RecheckPolicy(enabled=True, level="L2"),
            )

    def test_no_scan_allows_history_only_recheck(self):
        plan = ProspectGovernancePlan(
            suppression=SuppressionPolicy(enabled=True, mode="NO_SCAN", reason="opt-out"),
            recheck=RecheckPolicy(enabled=True, level="L0"),
        )
        assert plan.suppression.mode == "NO_SCAN"

    def test_round_trip(self):
        plan = ProspectGovernancePlan()
        restored = ProspectGovernancePlan.from_dict(plan.to_dict())
        assert restored.to_dict() == plan.to_dict()

    def test_no_shared_default_mutation(self):
        a = ProspectGovernancePlan()
        b = ProspectGovernancePlan()
        a.notes.append("x")
        assert b.notes == []


class TestBackwardsCompatibility:
    def test_unknown_keys_ignored(self):
        data = ProspectLifecycle().to_dict()
        data["future_field"] = 1
        assert ProspectLifecycle.from_dict(data).status == "DISCOVERED"

    def test_existing_schemas_unaffected(self):
        from core.schemas.cleanup import CleanupPolicy
        from core.schemas.work_run_state import WorkRunState
        assert CleanupPolicy().dry_run_required is True
        assert WorkRunState().status == "RECEIVED"

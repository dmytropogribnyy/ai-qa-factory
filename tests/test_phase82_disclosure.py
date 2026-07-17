"""Phase 8.2 — controlled disclosure contract tests (child slice).

Planning/contracts only — no evidence capture, sending, submission, or delivery runtime.
"""
from __future__ import annotations

import pytest

from core.schemas.prospect_interaction import PROSPECT_CONTRACT_SCHEMA_VERSION
from core.schemas.prospect_disclosure import (
    DisclosureItem,
    DisclosureLevel,
    DisclosureManifest,
    DisclosureStage,
    FindingDisclosurePolicy,
    StorageClass,
)

_ISO = "2026-07-17T00:00:00+00:00"


def _outreach_item(finding_ref="F-1", role="primary"):
    return DisclosureItem(
        finding_ref=finding_ref,
        disclosure_level="OUTREACH_ELIGIBLE",
        role=role,
        storage_class="CLIENT_SAFE",
        sanitized=True,
        independently_verified=True,
        reproduction_detail_level="minimal",
        evidence_refs=["EV-1"],
    )


def _outreach_manifest(items=None):
    return DisclosureManifest(
        prospect_ref="p1",
        stage="OUTREACH",
        items=items if items is not None else [_outreach_item()],
        contact_ref="CONTACT-1",
        suppression_check_ref="SUP-1",
        pre_send_revalidation_ref="REVAL-1",
        approval_ref="APR-1",
    )


class TestStorageAndLevelSeparation:
    def test_storage_and_level_are_distinct_enums(self):
        assert {s.value for s in StorageClass} == {
            "RAW_INTERNAL", "SANITIZED_INTERNAL", "VERIFIED_INTERNAL", "CLIENT_SAFE",
        }
        assert {x.value for x in DisclosureLevel} == {
            "INTERNAL_ONLY", "OUTREACH_ELIGIBLE", "QUALIFICATION_ELIGIBLE",
            "PAID_DELIVERY_ONLY",
        }
        # No value overlap between storage classes and disclosure levels.
        assert not ({s.value for s in StorageClass} & {x.value for x in DisclosureLevel})


class TestDisclosureItem:
    def test_blank_finding_ref_rejected(self):
        with pytest.raises(ValueError):
            DisclosureItem(finding_ref="  ")

    def test_client_safe_requires_sanitized_no_pii_secrets(self):
        with pytest.raises(ValueError):
            DisclosureItem(finding_ref="F", storage_class="CLIENT_SAFE", sanitized=False)
        with pytest.raises(ValueError):
            DisclosureItem(finding_ref="F", storage_class="CLIENT_SAFE",
                           sanitized=True, contains_pii=True)
        with pytest.raises(ValueError):
            DisclosureItem(finding_ref="F", storage_class="CLIENT_SAFE",
                           sanitized=True, contains_secrets=True)

    def test_outreach_eligible_requires_verified_and_client_safe(self):
        with pytest.raises(ValueError):
            DisclosureItem(finding_ref="F", disclosure_level="OUTREACH_ELIGIBLE",
                           storage_class="CLIENT_SAFE", sanitized=True,
                           independently_verified=False)
        with pytest.raises(ValueError):
            DisclosureItem(finding_ref="F", disclosure_level="OUTREACH_ELIGIBLE",
                           storage_class="SANITIZED_INTERNAL",
                           independently_verified=True)

    def test_outreach_eligible_rejects_root_cause_and_logs(self):
        with pytest.raises(ValueError):
            DisclosureItem(finding_ref="F", disclosure_level="OUTREACH_ELIGIBLE",
                           storage_class="CLIENT_SAFE", sanitized=True,
                           independently_verified=True, root_cause_included=True)
        with pytest.raises(ValueError):
            DisclosureItem(finding_ref="F", disclosure_level="OUTREACH_ELIGIBLE",
                           storage_class="CLIENT_SAFE", sanitized=True,
                           independently_verified=True, full_logs_included=True)

    def test_responsible_disclosure_forced_internal(self):
        with pytest.raises(ValueError):
            DisclosureItem(finding_ref="F", disclosure_level="OUTREACH_ELIGIBLE",
                           storage_class="CLIENT_SAFE", sanitized=True,
                           independently_verified=True,
                           responsible_disclosure_flag=True)
        # INTERNAL_ONLY responsible-disclosure item is fine.
        item = DisclosureItem(finding_ref="F", responsible_disclosure_flag=True)
        assert item.disclosure_level == "INTERNAL_ONLY"

    def test_evidence_refs_deduped_and_nonblank(self):
        item = DisclosureItem(finding_ref="F", evidence_refs=["A", "A", "B"])
        assert item.evidence_refs == ["A", "B"]
        with pytest.raises(ValueError):
            DisclosureItem(finding_ref="F", evidence_refs=["  "])

    def test_round_trip(self):
        item = _outreach_item()
        assert DisclosureItem.from_dict(item.to_dict()).to_dict() == item.to_dict()


class TestFindingDisclosurePolicy:
    def test_default_fail_closed(self):
        p = FindingDisclosurePolicy()
        assert p.default_level == "INTERNAL_ONLY"
        assert p.allow_pii is False
        assert p.allow_secrets is False
        assert p.allow_raw_logs_in_outreach is False
        assert p.allow_root_cause_in_outreach is False

    def test_safety_toggles_cannot_be_enabled(self):
        p = FindingDisclosurePolicy(allow_pii=True, allow_secrets=True,
                                    allow_raw_logs_in_outreach=True,
                                    allow_root_cause_in_outreach=True)
        assert p.allow_pii is False
        assert p.allow_secrets is False
        assert p.allow_raw_logs_in_outreach is False
        assert p.allow_root_cause_in_outreach is False

    def test_negative_limits_rejected(self):
        with pytest.raises(ValueError):
            FindingDisclosurePolicy(outreach_max_total=-1)


class TestDisclosureManifest:
    def test_valid_outreach_manifest_ready(self):
        m = _outreach_manifest()
        assert m.blockers == []
        assert m.outreach_ready is True
        assert m.is_ready is True

    def test_missing_contact_blocks_outreach(self):
        m = _outreach_manifest()
        m.contact_ref = ""
        assert m.outreach_ready is False
        assert any("contact" in b for b in m.blockers)

    def test_missing_suppression_check_blocks(self):
        m = _outreach_manifest()
        m.suppression_check_ref = ""
        assert m.outreach_ready is False

    def test_missing_revalidation_blocks(self):
        m = _outreach_manifest()
        m.pre_send_revalidation_ref = ""
        assert m.outreach_ready is False

    def test_missing_approval_blocks(self):
        m = _outreach_manifest()
        m.approval_ref = ""
        assert m.outreach_ready is False

    def test_too_many_findings_blocks_outreach(self):
        items = [_outreach_item("F-1", "primary"),
                 _outreach_item("F-2", "support"),
                 _outreach_item("F-3", "support")]
        m = _outreach_manifest(items=items)
        assert m.outreach_ready is False
        assert any("too many" in b for b in m.blockers)

    def test_forged_readiness_recomputed_from_dict(self):
        # A caller cannot inject a trusted 'outreach_ready' flag: readiness is computed.
        m = _outreach_manifest()
        data = m.to_dict()
        data["outreach_ready"] = True  # ignored (not a field)
        data["contact_ref"] = ""       # real blocker
        restored = DisclosureManifest.from_dict(data)
        assert restored.outreach_ready is False

    def test_non_client_safe_item_blocks_outreach(self):
        # Build a manifest whose item is only qualification-eligible (allowed to construct)
        # but not outreach-eligible -> outreach blockers appear.
        item = DisclosureItem(
            finding_ref="F", disclosure_level="QUALIFICATION_ELIGIBLE",
            storage_class="SANITIZED_INTERNAL",
        )
        m = _outreach_manifest(items=[item])
        assert m.outreach_ready is False
        assert any("OUTREACH_ELIGIBLE" in b or "CLIENT_SAFE" in b for b in m.blockers)

    def test_qualification_stage_limit(self):
        items = [
            DisclosureItem(finding_ref=f"F-{i}", disclosure_level="QUALIFICATION_ELIGIBLE")
            for i in range(4)
        ]
        m = DisclosureManifest(stage="QUALIFICATION", items=items)
        assert any("too many" in b for b in m.blockers)

    def test_manifest_has_no_send_fields(self):
        keys = set(DisclosureManifest().to_dict().keys())
        assert not (keys & {"sent", "delivered", "email_body", "smtp", "recipient_email"})

    def test_unknown_stage_rejected(self):
        with pytest.raises(ValueError):
            DisclosureManifest(stage="BROADCAST")

    def test_bad_generated_at_rejected(self):
        with pytest.raises(ValueError):
            DisclosureManifest(generated_at="whenever")

    def test_round_trip(self):
        m = _outreach_manifest()
        restored = DisclosureManifest.from_dict(m.to_dict())
        assert restored.to_dict() == m.to_dict()
        assert restored.schema_version == PROSPECT_CONTRACT_SCHEMA_VERSION

    def test_stage_enum_values(self):
        assert {s.value for s in DisclosureStage} == {
            "INTERNAL", "OUTREACH", "QUALIFICATION", "PAID_DELIVERY",
        }

    def test_no_shared_default_mutation(self):
        a = DisclosureManifest()
        b = DisclosureManifest()
        a.items.append(_outreach_item())
        a.notes.append("x")
        assert b.items == []
        assert b.notes == []

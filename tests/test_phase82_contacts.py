"""Phase 8.2 — public business contact contract tests (child slice).

Planning/contracts only — no lookup, scraping, enrichment, sending, or database runtime.
"""
from __future__ import annotations

import pytest

from core.schemas.source_reference import SourceReference
from core.schemas.prospect_interaction import PROSPECT_CONTRACT_SCHEMA_VERSION
from core.schemas.prospect_contact import (
    ContactCollection,
    ContactProvenance,
    ContactRecord,
    ContactStatus,
)

_ISO = "2026-07-17T00:00:00+00:00"


def _public_provenance(**kw):
    base = dict(
        source=SourceReference(url="https://example.com/contact"),
        source_category="public_website",
        extraction_method="published_link",
        observed_at=_ISO,
        evidence_ref="EV-1",
        confidence="high",
        publicly_published_for_contact=True,
    )
    base.update(kw)
    return ContactProvenance(**base)


def _inferred_provenance():
    return ContactProvenance(
        source_category="inferred_candidate",
        extraction_method="inferred_pattern",
        confidence="low",
    )


class TestContactProvenance:
    def test_valid(self):
        p = _public_provenance()
        assert p.is_public_verified_source is True
        assert p.is_inferred is False
        assert p.counts_for_verification is True

    def test_inferred_marked(self):
        p = _inferred_provenance()
        assert p.is_inferred is True
        assert p.is_public_verified_source is False

    def test_unknown_category_rejected(self):
        with pytest.raises(ValueError):
            ContactProvenance(source_category="stolen_db")

    def test_unknown_extraction_rejected(self):
        with pytest.raises(ValueError):
            ContactProvenance(extraction_method="magic")

    def test_bad_observed_at_rejected(self):
        with pytest.raises(ValueError):
            ContactProvenance(observed_at="yesterday")

    @pytest.mark.parametrize(
        "override",
        [
            {"publicly_published_for_contact": False},
            {"observed_at": ""},
            {"evidence_ref": ""},
            {"terms_review_status": "reviewed_blocked"},
            {"extraction_method": "inferred_pattern"},
        ],
    )
    def test_incomplete_or_blocked_provenance_cannot_verify(self, override):
        assert _public_provenance(**override).counts_for_verification is False

    def test_malformed_nested_source_fails_closed(self):
        data = _public_provenance().to_dict()
        data["source"] = "not-an-object"
        with pytest.raises(ValueError, match="source"):
            ContactProvenance.from_dict(data)

    def test_round_trip(self):
        p = _public_provenance()
        restored = ContactProvenance.from_dict(p.to_dict())
        assert restored.to_dict() == p.to_dict()
        assert isinstance(restored.source, SourceReference)


class TestContactStatus:
    def test_values(self):
        assert {s.value for s in ContactStatus} == {
            "UNVERIFIED", "PUBLIC_OBSERVED", "MANUAL_REVIEW_REQUIRED", "VERIFIED",
            "STALE", "INVALID", "SUPPRESSED", "DO_NOT_CONTACT",
        }


class TestContactRecord:
    def test_email_normalized(self):
        c = ContactRecord(channel="email", value="  Info@Example.COM ")
        assert c.normalized_value == "info@example.com"

    def test_invalid_email_rejected(self):
        with pytest.raises(ValueError):
            ContactRecord(channel="email", value="not-an-email")

    def test_blank_value_rejected(self):
        with pytest.raises(ValueError):
            ContactRecord(channel="email", value="   ")

    def test_secret_value_rejected(self):
        with pytest.raises(ValueError):
            ContactRecord(channel="email", value="api_key@example.com")

    def test_phone_conservative_no_country_code(self):
        c = ContactRecord(channel="phone", value="(030) 123-45 67")
        assert c.normalized_value == "0301234567"  # digits only, no invented country code
        # Leading + preserved when present, never invented.
        c2 = ContactRecord(channel="phone", value="+49 30 1234567")
        assert c2.normalized_value.startswith("+49")

    @pytest.mark.parametrize("value", ["---", "1234", "1" * 16])
    def test_phone_rejects_meaningless_or_implausible_values(self, value):
        with pytest.raises(ValueError):
            ContactRecord(channel="phone", value=value)

    def test_contact_form_must_be_reference(self):
        assert ContactRecord(channel="contact_form", value="/contact").normalized_value == "/contact"
        with pytest.raises(ValueError):
            ContactRecord(channel="contact_form", value="call us maybe")

    @pytest.mark.parametrize(
        "value",
        [
            "//evil.example/contact",
            "https://user:pass@example.com/contact",
            "https://localhost/contact",
            "https://127.0.0.1/contact",
            "https://10.0.0.1/contact",
            "https://example.com:8443/contact",
            "https://example.com/contact#section",
            "/contact#section",
            "/contact?access_token=secret",
            "/contact\\unsafe",
        ],
    )
    def test_contact_form_rejects_unsafe_targets(self, value):
        with pytest.raises(ValueError):
            ContactRecord(channel="contact_form", value=value)

    def test_contact_form_normalization_is_deterministic(self):
        assert (
            ContactRecord(
                channel="contact_form",
                value="HTTPS://EXAMPLE.COM/contact?topic=sales",
            ).normalized_value
            == "https://example.com/contact?topic=sales"
        )

    def test_inferred_email_cannot_be_verified(self):
        with pytest.raises(ValueError):
            ContactRecord(
                channel="email",
                value="guess@example.com",
                status="VERIFIED",
                provenance=[_inferred_provenance()],
                last_verified_at=_ISO,
            )

    def test_verified_requires_public_provenance_and_time(self):
        # Missing last_verified_at.
        with pytest.raises(ValueError):
            ContactRecord(
                channel="email",
                value="info@example.com",
                status="VERIFIED",
                provenance=[_public_provenance()],
            )
        # Valid VERIFIED.
        c = ContactRecord(
            channel="email",
            value="info@example.com",
            status="VERIFIED",
            provenance=[_public_provenance()],
            last_verified_at=_ISO,
        )
        # VERIFIED alone is not an outreach candidate — a suppression-check ref is needed.
        assert c.is_outreach_candidate is False
        c.suppression_check_ref = "SUP-1"
        assert c.is_outreach_candidate is True

    def test_named_person_requires_manual_review(self):
        c = ContactRecord(
            channel="email",
            value="jane.doe@example.com",
            data_subject_category="named_person",
            manual_review_required=False,
        )
        assert c.manual_review_required is True

    def test_named_person_review_reference_required_for_outreach_candidate(self):
        c = ContactRecord(
            channel="email",
            value="jane.doe@example.com",
            data_subject_category="named_person",
            status="VERIFIED",
            provenance=[_public_provenance()],
            last_verified_at=_ISO,
            suppression_check_ref="SUP-1",
        )
        assert c.is_outreach_candidate is False
        c.manual_review_ref = "REVIEW-1"
        assert c.is_outreach_candidate is True

    def test_role_based_distinct_from_named(self):
        role = ContactRecord(channel="email", value="info@example.com",
                             data_subject_category="role_based")
        assert role.manual_review_required is False

    @pytest.mark.parametrize("status", ["SUPPRESSED", "DO_NOT_CONTACT", "UNVERIFIED", "STALE"])
    def test_non_verified_is_not_outreach_candidate(self, status):
        c = ContactRecord(channel="email", value="info@example.com", status=status)
        assert c.is_outreach_candidate is False

    def test_inferred_only_flag(self):
        c = ContactRecord(
            channel="email", value="guess@example.com",
            provenance=[_inferred_provenance()],
        )
        assert c.is_inferred_only is True
        assert c.is_outreach_candidate is False

    def test_round_trip(self):
        c = ContactRecord(
            channel="email",
            value="info@example.com",
            status="VERIFIED",
            provenance=[_public_provenance()],
            last_verified_at=_ISO,
        )
        restored = ContactRecord.from_dict(c.to_dict())
        assert restored.to_dict() == c.to_dict()
        assert isinstance(restored.provenance[0], ContactProvenance)

    def test_malformed_provenance_entry_fails_closed(self):
        data = ContactRecord(
            channel="email", value="info@example.com"
        ).to_dict()
        data["provenance"] = ["not-an-object"]
        with pytest.raises(ValueError, match="provenance"):
            ContactRecord.from_dict(data)

    def test_no_shared_default_mutation(self):
        a = ContactRecord(channel="email", value="a@example.com")
        b = ContactRecord(channel="email", value="b@example.com")
        a.provenance.append(_public_provenance())
        a.notes.append("x")
        assert b.provenance == []
        assert b.notes == []


class TestContactCollection:
    def test_dedup_merges_by_channel_and_normalized_value(self):
        col = ContactCollection(contacts=[
            ContactRecord(channel="email", value="Info@example.com"),
            ContactRecord(channel="email", value="info@EXAMPLE.com"),
        ])
        assert len(col.contacts) == 1

    def test_merge_keeps_stricter_status(self):
        col = ContactCollection(contacts=[
            ContactRecord(
                channel="email", value="info@example.com", status="VERIFIED",
                provenance=[_public_provenance()], last_verified_at=_ISO,
            ),
            ContactRecord(channel="email", value="info@example.com", status="DO_NOT_CONTACT"),
        ])
        assert len(col.contacts) == 1
        assert col.contacts[0].status == "DO_NOT_CONTACT"
        assert col.contacts[0].is_outreach_candidate is False

    def test_merge_unions_provenance(self):
        col = ContactCollection(contacts=[
            ContactRecord(channel="email", value="info@example.com",
                          provenance=[_public_provenance()]),
            ContactRecord(channel="email", value="info@example.com",
                          provenance=[_inferred_provenance()]),
        ])
        assert len(col.contacts) == 1
        assert len(col.contacts[0].provenance) == 2

    def test_merge_does_not_mutate_or_alias_original_contacts(self):
        first = ContactRecord(
            channel="email",
            value="info@example.com",
            provenance=[_public_provenance()],
            manual_review_required=False,
        )
        second = ContactRecord(
            channel="email",
            value="INFO@example.com",
            status="DO_NOT_CONTACT",
            provenance=[_inferred_provenance()],
            manual_review_required=True,
            manual_review_ref="REVIEW-1",
        )
        first_before = first.to_dict()
        second_before = second.to_dict()

        collection = ContactCollection(contacts=[first, second])

        assert first.to_dict() == first_before
        assert second.to_dict() == second_before
        assert collection.contacts[0] is not first
        assert collection.contacts[0] is not second
        assert collection.contacts[0].status == "DO_NOT_CONTACT"
        assert collection.contacts[0].manual_review_required is True
        assert collection.contacts[0].manual_review_ref == "REVIEW-1"

    def test_malformed_contact_entry_fails_closed(self):
        with pytest.raises(ValueError, match="contacts"):
            ContactCollection.from_dict({"contacts": ["not-an-object"]})

    def test_distinct_channels_not_merged(self):
        col = ContactCollection(contacts=[
            ContactRecord(channel="email", value="info@example.com"),
            ContactRecord(channel="phone", value="+49301234567"),
        ])
        assert len(col.contacts) == 2

    def test_round_trip(self):
        col = ContactCollection(
            company_ref="acme",
            contacts=[ContactRecord(channel="email", value="info@example.com")],
        )
        restored = ContactCollection.from_dict(col.to_dict())
        assert restored.to_dict() == col.to_dict()
        assert restored.schema_version == PROSPECT_CONTRACT_SCHEMA_VERSION

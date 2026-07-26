"""Truthfulness regression for the Scout campaign exclusion control."""
from __future__ import annotations

from core.scout.backends import PageObservation
from core.scout.discovery.candidate import CandidateRecord, TECH_OK, TECH_REJECT
from core.scout.discovery.triage import TriageContext, assess_technical


def _record() -> CandidateRecord:
    return CandidateRecord(normalized_url="https://example.com", eligibility_status="pending")


def _observation(*, title: str = "Acme software", links: list[str] | None = None) -> PageObservation:
    return PageObservation(
        url="https://example.com",
        final_url="https://example.com",
        status=200,
        ok=True,
        title=title,
        headings=[{"level": 1, "text": "Business automation"}],
        links=links or ["https://example.com/pricing"],
    )


def test_excluded_word_rejects_matching_site_before_commercial_triage():
    rec = _record()
    assess_technical(
        rec,
        _observation(title="Acme investor relations"),
        TriageContext(
            languages=[],
            countries=[],
            min_commercial_threshold=40,
            exclude_keywords=["Investor Relations"],
        ),
    )

    assert rec.eligibility_status == TECH_REJECT
    assert "excluded_keyword:investor relations" in rec.technical_reasons
    assert "excluded_keyword" in rec.reason_codes


def test_nonmatching_exclusion_keeps_technically_valid_site():
    rec = _record()
    assess_technical(
        rec,
        _observation(),
        TriageContext(
            languages=[],
            countries=[],
            min_commercial_threshold=40,
            exclude_keywords=["careers"],
        ),
    )

    assert rec.eligibility_status == TECH_OK
    assert not any(reason.startswith("excluded_keyword:") for reason in rec.technical_reasons)

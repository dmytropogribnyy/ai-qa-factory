"""Phase 8.2 — prospect scoring contract tests (slice 4 foundation).

Planning/contracts only — no scoring runtime, contact lookup, or outreach.
"""
from __future__ import annotations

import pytest

from core.schemas.prospect_interaction import PROSPECT_CONTRACT_SCHEMA_VERSION
from core.schemas.prospect_scoring import (
    LeadScorecard,
    ProspectPriority,
    ScoreDimension,
)


class TestScoreDimension:
    def test_valid(self):
        d = ScoreDimension(name="technical_confidence", value=80, reasons=["fast LCP"])
        assert d.value == 80

    def test_unknown_dimension_rejected(self):
        with pytest.raises(ValueError):
            ScoreDimension(name="vibes", value=50)

    @pytest.mark.parametrize("bad", [-1, 101, 1000])
    def test_out_of_bounds_rejected(self, bad):
        with pytest.raises(ValueError):
            ScoreDimension(name="business_impact", value=bad)

    def test_bool_value_rejected(self):
        with pytest.raises(ValueError):
            ScoreDimension(name="business_impact", value=True)

    def test_round_trip(self):
        d = ScoreDimension(name="evidence_quality", value=60, risk_notes=["thin evidence"])
        assert ScoreDimension.from_dict(d.to_dict()).to_dict() == d.to_dict()


class TestLeadScorecard:
    def test_defaults(self):
        s = LeadScorecard()
        assert s.priority == "D"
        assert s.outreach_eligible is False
        assert s.weighted_total is None
        assert s.schema_version == PROSPECT_CONTRACT_SCHEMA_VERSION

    def test_priority_grades(self):
        for p in ("A", "B", "C", "D", "REJECTED"):
            assert LeadScorecard(priority=p).priority == p
        assert set(x.value for x in ProspectPriority) == {"A", "B", "C", "D", "REJECTED"}

    def test_unknown_priority_rejected(self):
        with pytest.raises(ValueError):
            LeadScorecard(priority="S_TIER")

    def test_dimensions_stay_independently_visible(self):
        s = LeadScorecard(dimensions=[
            ScoreDimension(name="access_complexity", value=90),
            ScoreDimension(name="commercial_capacity", value=20),
            ScoreDimension(name="public_coverage", value=10),
        ])
        by_name = {d.name: d.value for d in s.dimensions}
        # Independent axes: access complexity does not invert commercial opportunity,
        # and public coverage is not tied to commercial capacity.
        assert by_name["access_complexity"] == 90
        assert by_name["commercial_capacity"] == 20
        assert by_name["public_coverage"] == 10

    def test_remediation_fit_does_not_change_audit_opportunity(self):
        s = LeadScorecard(dimensions=[
            ScoreDimension(name="audit_opportunity", value=75),
            ScoreDimension(name="remediation_fit", value=5),
        ])
        by_name = {d.name: d.value for d in s.dimensions}
        assert by_name["audit_opportunity"] == 75  # not lowered by remediation_fit

    def test_duplicate_dimension_rejected(self):
        with pytest.raises(ValueError):
            LeadScorecard(dimensions=[
                ScoreDimension(name="market_fit", value=50),
                ScoreDimension(name="market_fit", value=60),
            ])

    def test_no_weights_means_no_hidden_total(self):
        s = LeadScorecard(dimensions=[ScoreDimension(name="market_fit", value=50)])
        assert s.weighted_total is None

    def test_weighted_total_from_valid_weights(self):
        s = LeadScorecard(
            dimensions=[
                ScoreDimension(name="business_impact", value=100),
                ScoreDimension(name="market_fit", value=0),
            ],
            weights={"business_impact": 3.0, "market_fit": 1.0},
        )
        # Normalized weights 0.75/0.25 → 75.0
        assert s.weighted_total == 75.0
        assert round(sum(s.weights.values()), 6) == 1.0

    def test_weight_for_absent_dimension_rejected(self):
        with pytest.raises(ValueError):
            LeadScorecard(
                dimensions=[ScoreDimension(name="market_fit", value=50)],
                weights={"business_impact": 1.0},
            )

    def test_weight_for_unknown_dimension_rejected(self):
        with pytest.raises(ValueError):
            LeadScorecard(
                dimensions=[ScoreDimension(name="market_fit", value=50)],
                weights={"charisma": 1.0},
            )

    def test_negative_weight_rejected(self):
        with pytest.raises(ValueError):
            LeadScorecard(
                dimensions=[ScoreDimension(name="market_fit", value=50)],
                weights={"market_fit": -1.0},
            )

    def test_zero_sum_weights_rejected(self):
        with pytest.raises(ValueError):
            LeadScorecard(
                dimensions=[ScoreDimension(name="market_fit", value=50)],
                weights={"market_fit": 0.0},
            )

    def test_outreach_not_eligible_by_default(self):
        s = LeadScorecard(
            priority="A",
            dimensions=[ScoreDimension(name="outreach_value", value=100)],
        )
        assert s.outreach_eligible is False

    def test_round_trip_stable(self):
        s = LeadScorecard(
            prospect_id="p1",
            priority="B",
            dimensions=[
                ScoreDimension(name="business_impact", value=80),
                ScoreDimension(name="evidence_quality", value=40),
            ],
            weights={"business_impact": 1.0, "evidence_quality": 1.0},
            rationale=["strong impact"],
        )
        restored = LeadScorecard.from_dict(s.to_dict())
        assert restored.to_dict() == s.to_dict()
        assert restored.weighted_total == 60.0

    def test_no_shared_default_mutation(self):
        a = LeadScorecard()
        b = LeadScorecard()
        a.dimensions.append(ScoreDimension(name="market_fit", value=1))
        a.notes.append("x")
        assert b.dimensions == []
        assert b.notes == []

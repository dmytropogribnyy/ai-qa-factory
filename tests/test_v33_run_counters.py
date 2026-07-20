"""v3.3 operator workflow — the seven required run counters + actionable-target stop helper.

Deterministic: the counters are a pure function of candidate records plus the run-time tallies
(QA-analyzed / actionable / already-analyzed / failed) the engine tracks. Discovered URLs are
NOT all counted as useful results — eligibility, rejection and actionability are separate.
"""
from __future__ import annotations

from core.scout.discovery.candidate import (
    COMM_ELIGIBLE,
    COMM_REJECT,
    TECH_OK,
    TECH_REJECT,
    CandidateRecord,
)
from core.scout.run_counters import RunCounters, actionable_target_reached, counters_from_records


def _rec(cid, *, comm=COMM_ELIGIBLE, tech=TECH_OK, supp="none") -> CandidateRecord:
    r = CandidateRecord(candidate_id=cid)
    r.commercial_status = comm
    r.eligibility_status = tech
    r.suppression_status = supp
    return r


def test_seven_counters_are_all_present():
    c = RunCounters().to_dict()
    assert set(c) == {"discovered", "eligible", "qa_analyzed", "actionable",
                      "already_analyzed", "rejected", "failed"}


def test_discovered_is_not_the_same_as_eligible_or_actionable():
    records = [
        _rec("a", comm=COMM_ELIGIBLE, tech=TECH_OK),
        _rec("b", comm=COMM_ELIGIBLE, tech=TECH_OK),
        _rec("c", comm=COMM_REJECT, tech=TECH_OK),
        _rec("d", comm=COMM_ELIGIBLE, tech=TECH_REJECT),   # tech-rejected
        _rec("e", comm=COMM_ELIGIBLE, tech=TECH_OK, supp="NO_SCAN"),   # suppressed
    ]
    c = counters_from_records(records, qa_analyzed=2, actionable=1,
                              already_analyzed=1, failed=1)
    assert c.discovered == 5
    assert c.eligible == 2                 # only a, b are eligible AND technically ok, not suppressed
    assert c.qa_analyzed == 2
    assert c.actionable == 1
    assert c.already_analyzed == 1
    assert c.rejected == 3                 # c (comm reject), d (tech reject), e (suppressed)
    assert c.failed == 1


def test_actionable_never_exceeds_qa_analyzed_in_a_healthy_run():
    c = counters_from_records([_rec("a")], qa_analyzed=5, actionable=2)
    assert c.actionable <= c.qa_analyzed


def test_actionable_target_stop_predicate():
    assert actionable_target_reached(found=2, target=2) is True
    assert actionable_target_reached(found=3, target=2) is True
    assert actionable_target_reached(found=1, target=2) is False
    # target 0 means "disabled" — never stops on actionable count
    assert actionable_target_reached(found=99, target=0) is False

"""The seven operator-facing run counters + the actionable-target stop predicate (v3.3).

Discovered URLs are NOT all "results". The Dashboard shows seven separate counters so the
operator sees the honest funnel: Discovered -> Eligible -> QA analyzed -> Actionable, with
Already-analyzed / Rejected / Failed accounted for separately. This module is a pure function
of the candidate records plus the run-time tallies the engine tracks, so it is deterministic
and reused by both the engine state and the Dashboard progress view.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable

from core.scout.discovery.candidate import (
    COMM_ELIGIBLE,
    COMM_REJECT,
    TECH_OK,
    TECH_REJECT,
    CandidateRecord,
)


@dataclass
class RunCounters:
    discovered: int = 0
    eligible: int = 0
    qa_analyzed: int = 0
    actionable: int = 0
    already_analyzed: int = 0
    rejected: int = 0
    failed: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def counters_from_records(records: Iterable[CandidateRecord], *, qa_analyzed: int = 0,
                          actionable: int = 0, already_analyzed: int = 0,
                          failed: int = 0) -> RunCounters:
    """Compute the seven counters. Eligible = commercially eligible AND technically ok AND not
    suppressed; Rejected = commercially rejected OR technically rejected OR suppressed."""
    records = list(records)
    eligible = sum(1 for r in records
                   if r.commercial_status == COMM_ELIGIBLE
                   and r.eligibility_status == TECH_OK
                   and r.suppression_status == "none")
    rejected = sum(1 for r in records
                   if r.commercial_status == COMM_REJECT
                   or r.eligibility_status == TECH_REJECT
                   or r.suppression_status != "none")
    return RunCounters(
        discovered=len(records),
        eligible=eligible,
        qa_analyzed=qa_analyzed,
        actionable=actionable,
        already_analyzed=already_analyzed,
        rejected=rejected,
        failed=failed,
    )


def actionable_target_reached(*, found: int, target: int) -> bool:
    """True once enough actionable (Priority-A) prospects are found. A target of 0 disables the
    stop (the run then finishes on the other finite budgets, never indefinitely)."""
    if target <= 0:
        return False
    return found >= target

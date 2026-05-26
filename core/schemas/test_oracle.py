"""Phase 5K — Test Oracle schemas.

Models the structured output of the heuristic test scenario generator.
Scenarios are derived from intake classification — raw input is never re-stored.

Safety invariants (hardcoded in __post_init__ + from_dict):
- raw_input_stored=False
- executable_without_approval=False
- safe_to_deliver=False
- human_review_required=True
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.schemas.base import SchemaMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TEST_COVERAGE_AREAS = (
    "auth",
    "api",
    "mobile",
    "database",
    "visual",
    "performance",
    "security",
    "functional",
    "general",
)

TEST_SCENARIO_PRIORITIES = (1, 2, 3)  # 1=critical, 2=high, 3=medium

TEST_ORACLE_MODES = ("heuristic", "llm_enhanced")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TestScenario(SchemaMixin):
    """A single test scenario with priority and risk score."""
    name: str = ""
    coverage_area: str = "general"
    priority: int = 2
    risk_score: float = 0.5
    tags: List[str] = field(default_factory=list)
    deferred: bool = False
    defer_reason: str = ""


@dataclass
class TestOracleReport(SchemaMixin):
    """Full test oracle report — generated scenarios and coverage summary."""
    project_id: str = ""
    oracle_mode: str = "heuristic"
    source_classification: str = "unknown"
    scenarios: List[TestScenario] = field(default_factory=list)
    deferred_scenarios: List[TestScenario] = field(default_factory=list)
    total_scenarios: int = 0
    coverage_areas: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # Safety invariants
    raw_input_stored: bool = False
    llm_calls_made: bool = False
    executable_without_approval: bool = False
    safe_to_deliver: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_input_stored", False)
        object.__setattr__(self, "executable_without_approval", False)
        object.__setattr__(self, "safe_to_deliver", False)
        object.__setattr__(self, "human_review_required", True)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["scenarios"] = [s.to_dict() for s in self.scenarios]
        d["deferred_scenarios"] = [s.to_dict() for s in self.deferred_scenarios]
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "TestOracleReport":
        scenarios = [
            TestScenario(**s) if isinstance(s, dict) else s
            for s in data.get("scenarios", [])
        ]
        deferred = [
            TestScenario(**s) if isinstance(s, dict) else s
            for s in data.get("deferred_scenarios", [])
        ]
        obj = cls(
            project_id=str(data.get("project_id", "")),
            oracle_mode=str(data.get("oracle_mode", "heuristic")),
            source_classification=str(data.get("source_classification", "unknown")),
            scenarios=scenarios,
            deferred_scenarios=deferred,
            total_scenarios=int(data.get("total_scenarios", 0)),
            coverage_areas=list(data.get("coverage_areas", [])),
            blockers=list(data.get("blockers", [])),
            notes=list(data.get("notes", [])),
            llm_calls_made=bool(data.get("llm_calls_made", False)),
        )
        object.__setattr__(obj, "raw_input_stored", False)
        object.__setattr__(obj, "executable_without_approval", False)
        object.__setattr__(obj, "safe_to_deliver", False)
        object.__setattr__(obj, "human_review_required", True)
        return obj

"""Scenario batch evaluation schemas — Phase 4ABC.

SAFETY DEFAULTS:
- evaluation_performed_without_execution = True
- external_calls_performed = False
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin

EVALUATION_STATUSES = {"pass", "warning", "blocked", "error"}
SCENARIO_CATEGORIES = {
    "synthetic", "public_demo_targets", "real_public_readonly", "high_risk_marketplace_readonly",
}


@dataclass
class ScenarioEvaluationResult(SchemaMixin):
    """Evaluation result for a single scenario fixture."""
    id: str = ""
    scenario_path: str = ""
    category: str = ""
    title: str = ""
    status: str = "pass"
    expected_project_type: str = ""
    expected_environment_type: str = ""
    expected_blocked_actions: List[str] = field(default_factory=list)
    expected_required_approvals: List[str] = field(default_factory=list)
    safety_expectations_present: bool = False
    linear_task_source_rule_present: bool = False
    high_risk_marketplace_rule_present: bool = False
    no_execution_confirmed: bool = False
    warnings: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@dataclass
class ScenarioBatchEvaluationReport(SchemaMixin):
    """Aggregated batch evaluation report for all scenario fixtures."""
    project_id: str = ""
    fixtures_root: str = ""
    total_scenarios: int = 0
    passed_scenarios: int = 0
    warning_scenarios: int = 0
    blocked_scenarios: int = 0
    results: List[ScenarioEvaluationResult] = field(default_factory=list)
    evaluation_performed_without_execution: bool = True
    external_calls_performed: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "fixtures_root": self.fixtures_root,
            "total_scenarios": self.total_scenarios,
            "passed_scenarios": self.passed_scenarios,
            "warning_scenarios": self.warning_scenarios,
            "blocked_scenarios": self.blocked_scenarios,
            "results": [r.to_dict() for r in self.results],
            "evaluation_performed_without_execution": self.evaluation_performed_without_execution,
            "external_calls_performed": self.external_calls_performed,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScenarioBatchEvaluationReport:
        known = {
            "project_id", "fixtures_root",
            "total_scenarios", "passed_scenarios", "warning_scenarios", "blocked_scenarios",
            "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["results"] = [
            ScenarioEvaluationResult.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("results", [])
        ]
        # Safety: these invariants are always True/False regardless of stored data.
        kwargs["evaluation_performed_without_execution"] = True
        kwargs["external_calls_performed"] = False
        return cls(**kwargs)

"""qa_strategy.py — QA Strategy schemas for Phase 2C.

Schema-only: no runtime execution, no URL fetching, no credential use.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.schemas.base import SchemaMixin


@dataclass
class QAStrategyArea(SchemaMixin):
    """One focused area within the overall QA strategy."""

    id: str = ""
    name: str = ""
    description: str = ""
    priority: str = "medium"          # low / medium / high / critical
    risk_level: str = "medium"        # low / medium / high / critical
    recommended_approach: str = ""
    related_surfaces: List[str] = field(default_factory=list)
    blocked: bool = False
    blocked_reason: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> QAStrategyArea:
        return super().from_dict(data)


@dataclass
class RiskMatrixItem(SchemaMixin):
    """One risk item in the project risk matrix."""

    id: str = ""
    risk_area: str = ""
    likelihood: str = "medium"        # low / medium / high
    impact: str = "medium"            # low / medium / high / critical
    severity: str = "medium"          # low / medium / high / critical
    mitigation: str = ""
    blocked: bool = False
    approval_required: bool = False
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> RiskMatrixItem:
        return super().from_dict(data)


@dataclass
class TestLayerRecommendation(SchemaMixin):
    """Recommendation for one testing layer."""

    id: str = ""
    layer: str = "unknown"            # smoke / ui / api / auth / ... (see layer constants)
    purpose: str = ""
    recommended: bool = True
    priority: str = "medium"          # low / medium / high
    examples: List[str] = field(default_factory=list)
    blocked: bool = False
    blocked_reason: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TestLayerRecommendation:
        return super().from_dict(data)


@dataclass
class TacticalPlanningItem(SchemaMixin):
    """One item in the tactical planning foundation for future phases."""

    id: str = ""
    title: str = ""
    description: str = ""
    phase: str = ""                   # e.g. "Phase 2D", "Phase 3A"
    priority: str = "medium"
    requires_approval: bool = False
    blocked: bool = False
    blocked_reason: Optional[str] = None
    future_artifact: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> TacticalPlanningItem:
        return super().from_dict(data)


@dataclass
class StrategyDecision(SchemaMixin):
    """One recorded strategy decision with rationale."""

    id: str = ""
    decision: str = ""
    rationale: str = ""
    alternatives_considered: List[str] = field(default_factory=list)
    impact: str = ""
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> StrategyDecision:
        return super().from_dict(data)


@dataclass
class QAStrategy(SchemaMixin):
    """Complete QA strategy for a project — produced by Phase 2C.

    client_ready is always False until an explicit approval phase marks it ready.
    No execution occurs during strategy generation.
    """

    project_id: str

    # --- Summary ---
    strategy_summary: str = ""
    project_type: str = "unknown"
    environment_type: str = "unknown"
    primary_goal: str = ""

    # --- Core strategy content ---
    strategy_areas: List[QAStrategyArea] = field(default_factory=list)
    risk_matrix: List[RiskMatrixItem] = field(default_factory=list)
    test_layers: List[TestLayerRecommendation] = field(default_factory=list)
    tactical_plan_outline: List[TacticalPlanningItem] = field(default_factory=list)
    strategy_decisions: List[StrategyDecision] = field(default_factory=list)

    # --- Blockers and approvals (carried forward from blueprint) ---
    blocked_actions: List[str] = field(default_factory=list)
    required_approvals: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)

    # --- Meta ---
    confidence_level: str = "medium"  # low / medium / high
    client_ready: bool = False         # always False until explicit approval phase
    notes: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "strategy_summary": self.strategy_summary,
            "project_type": self.project_type,
            "environment_type": self.environment_type,
            "primary_goal": self.primary_goal,
            "strategy_areas": [a.to_dict() for a in self.strategy_areas],
            "risk_matrix": [r.to_dict() for r in self.risk_matrix],
            "test_layers": [t.to_dict() for t in self.test_layers],
            "tactical_plan_outline": [i.to_dict() for i in self.tactical_plan_outline],
            "strategy_decisions": [d.to_dict() for d in self.strategy_decisions],
            "blocked_actions": self.blocked_actions,
            "required_approvals": self.required_approvals,
            "missing_information": self.missing_information,
            "confidence_level": self.confidence_level,
            "client_ready": self.client_ready,
            "notes": self.notes,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> QAStrategy:
        strategy_areas = [
            QAStrategyArea.from_dict(a) if isinstance(a, dict) else a
            for a in data.get("strategy_areas", [])
        ]
        risk_matrix = [
            RiskMatrixItem.from_dict(r) if isinstance(r, dict) else r
            for r in data.get("risk_matrix", [])
        ]
        test_layers = [
            TestLayerRecommendation.from_dict(t) if isinstance(t, dict) else t
            for t in data.get("test_layers", [])
        ]
        tactical_plan_outline = [
            TacticalPlanningItem.from_dict(i) if isinstance(i, dict) else i
            for i in data.get("tactical_plan_outline", [])
        ]
        strategy_decisions = [
            StrategyDecision.from_dict(d) if isinstance(d, dict) else d
            for d in data.get("strategy_decisions", [])
        ]
        return cls(
            project_id=data["project_id"],
            strategy_summary=data.get("strategy_summary", ""),
            project_type=data.get("project_type", "unknown"),
            environment_type=data.get("environment_type", "unknown"),
            primary_goal=data.get("primary_goal", ""),
            strategy_areas=strategy_areas,
            risk_matrix=risk_matrix,
            test_layers=test_layers,
            tactical_plan_outline=tactical_plan_outline,
            strategy_decisions=strategy_decisions,
            blocked_actions=data.get("blocked_actions", []),
            required_approvals=data.get("required_approvals", []),
            missing_information=data.get("missing_information", []),
            confidence_level=data.get("confidence_level", "medium"),
            client_ready=data.get("client_ready", False),
            notes=data.get("notes", []),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
        )

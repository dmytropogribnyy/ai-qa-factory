"""Feasibility decision schema (v3.0.0 Milestone 2).

A human-readable go/no-go decision for a potential client (Upwork/direct) assignment, derived
deterministically from the existing planning artifacts (WORK_PACKET / CAPABILITY_PLAN /
TOOLCHAIN_PLAN / INTAKE_REPORT). No LLM, no network. Analysis never starts implementation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# Operator-facing verdicts.
RECOMMENDED_TO_TAKE = "RECOMMENDED_TO_TAKE"
TAKE_AFTER_CLARIFICATION = "TAKE_AFTER_CLARIFICATION"
TAKE_AFTER_ACCESS_OR_TOOL_SETUP = "TAKE_AFTER_ACCESS_OR_TOOL_SETUP"
NOT_RECOMMENDED = "NOT_RECOMMENDED"
VERDICTS = frozenset({RECOMMENDED_TO_TAKE, TAKE_AFTER_CLARIFICATION,
                      TAKE_AFTER_ACCESS_OR_TOOL_SETUP, NOT_RECOMMENDED})


@dataclass
class FeasibilityReport:
    project_id: str = ""
    verdict: str = NOT_RECOMMENDED
    confidence: float = 0.0
    profile: str = ""
    client_intent: str = ""
    extracted_requirements: List[str] = field(default_factory=list)
    expected_deliverables: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    missing_information: List[str] = field(default_factory=list)
    client_questions: List[str] = field(default_factory=list)
    technical_fit: str = ""
    required_access: List[str] = field(default_factory=list)
    estimated_effort: str = ""
    estimated_duration: str = ""
    risk_level: str = "unknown"
    scope_creep_risks: List[str] = field(default_factory=list)
    validation_strategy: List[str] = field(default_factory=list)
    recommended_proposal: List[str] = field(default_factory=list)
    recommended_milestones: List[str] = field(default_factory=list)
    pricing_guidance: str = ""
    selected_capabilities: List[str] = field(default_factory=list)
    selected_tools: List[str] = field(default_factory=list)
    optional_tools: List[str] = field(default_factory=list)
    unavailable_blockers: List[str] = field(default_factory=list)
    reasons_to_reject: List[str] = field(default_factory=list)
    confidence_explanation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

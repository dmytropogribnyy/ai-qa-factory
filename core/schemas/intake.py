"""Phase 5K — Intake Agent schemas.

Models the structured output of the heuristic intake classifier.
Raw input text is NEVER stored in any artifact — only derived metadata
(length, classification, confidence) appears in outputs.

Safety invariants (hardcoded in __post_init__ + from_dict):
- raw_input_stored=False
- credentials_in_output=False
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

INTAKE_CLASSIFICATIONS = (
    "auth_testing",
    "api_testing",
    "mobile_testing",
    "database_testing",
    "visual_testing",
    "performance_testing",
    "security_testing",
    "functional_testing",
    "unknown",
)

INTAKE_RISK_LEVELS = ("low", "medium", "high", "critical")

INTAKE_MODES = ("heuristic", "llm_enhanced")


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class IntakeClassification(SchemaMixin):
    """Structured result of classifying a work request."""
    classification: str = "unknown"
    confidence: float = 0.0
    evidence_keywords: List[str] = field(default_factory=list)
    risk_level: str = "medium"
    recommended_modules: List[str] = field(default_factory=list)
    secondary_classifications: List[str] = field(default_factory=list)


@dataclass
class IntakeReport(SchemaMixin):
    """Full intake analysis report.

    Raw input text is NEVER stored — only derived metadata.
    """
    project_id: str = ""
    raw_input_length: int = 0
    intake_mode: str = "heuristic"
    classification: IntakeClassification = field(default_factory=IntakeClassification)
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # Safety invariants
    raw_input_stored: bool = False
    llm_calls_made: bool = False
    credentials_in_output: bool = False
    safe_to_deliver: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_input_stored", False)
        object.__setattr__(self, "credentials_in_output", False)
        object.__setattr__(self, "safe_to_deliver", False)
        object.__setattr__(self, "human_review_required", True)

    def to_dict(self) -> dict:
        d = super().to_dict()
        d["classification"] = self.classification.to_dict()
        return d

    @classmethod
    def from_dict(cls, data: dict) -> "IntakeReport":
        cls_data = data.get("classification", {})
        classification = (
            IntakeClassification(**cls_data) if isinstance(cls_data, dict)
            else cls_data
        )
        obj = cls(
            project_id=str(data.get("project_id", "")),
            raw_input_length=int(data.get("raw_input_length", 0)),
            intake_mode=str(data.get("intake_mode", "heuristic")),
            classification=classification,
            blockers=list(data.get("blockers", [])),
            notes=list(data.get("notes", [])),
            llm_calls_made=bool(data.get("llm_calls_made", False)),
        )
        object.__setattr__(obj, "raw_input_stored", False)
        object.__setattr__(obj, "credentials_in_output", False)
        object.__setattr__(obj, "safe_to_deliver", False)
        object.__setattr__(obj, "human_review_required", True)
        return obj

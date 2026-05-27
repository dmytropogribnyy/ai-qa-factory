"""Phase 5O — Flaky test analysis + self-healing schema.

Safety invariants (hardcoded in __post_init__):
- read_only=True
- auto_apply_changes=False
- code_modification_allowed=False
- human_review_required=True
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

from core.schemas.base import SchemaMixin

RISK_CATEGORIES = (
    "hard_wait",
    "fragile_selector",
    "race_prone",
    "non_web_first_assertion",
    "network_dependent",
    "dynamic_selector",
    "missing_evidence_hook",
)

SEVERITY_LEVELS = ("critical", "high", "medium", "low")
SELECTOR_STABILITY_LEVELS = ("strong", "medium", "weak", "unknown")
HEALING_STATUS_VALUES = ("analysis_only", "proposal_generated", "patch_applied", "partial")


@dataclass
class FlakinessRisk(SchemaMixin):
    """A single detected flakiness risk in a spec file."""
    risk_category: str = ""
    severity: str = ""
    affected_file: str = ""
    test_name: str = ""
    line_number: int = 0
    matched_pattern: str = ""
    description: str = ""
    recommendation: str = ""
    confidence_level: str = "medium"


@dataclass
class FlakyTestAnalysisReport(SchemaMixin):
    """Flaky test static analysis report — read-only, no code changes."""
    project_id: str = ""
    generated_at: str = ""
    files_analyzed: List[str] = field(default_factory=list)
    risks: List[FlakinessRisk] = field(default_factory=list)
    total_risks: int = 0
    risks_by_severity: Dict[str, int] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    status: str = "analysis_only"  # analysis_only | complete
    # Safety invariants
    read_only: bool = True
    auto_apply_changes: bool = False
    code_modification_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.read_only = True
        self.auto_apply_changes = False
        self.code_modification_allowed = False
        self.human_review_required = True


@dataclass
class SelectorFinding(SchemaMixin):
    """Stability classification for a single selector."""
    selector_text: str = ""
    stability_level: str = "unknown"  # strong | medium | weak | unknown
    locator_type: str = ""
    affected_file: str = ""
    line_number: int = 0
    recommendation: str = ""


@dataclass
class SelectorStabilityReport(SchemaMixin):
    """Selector stability analysis report — read-only, no code changes."""
    project_id: str = ""
    generated_at: str = ""
    files_analyzed: List[str] = field(default_factory=list)
    findings: List[SelectorFinding] = field(default_factory=list)
    strong_count: int = 0
    medium_count: int = 0
    weak_count: int = 0
    stability_score: float = 0.0  # 0–100, higher is better
    notes: List[str] = field(default_factory=list)
    # Safety invariants
    read_only: bool = True
    auto_fix_selectors: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.read_only = True
        self.auto_fix_selectors = False
        self.human_review_required = True


@dataclass
class SelfHealingProposal(SchemaMixin):
    """A single proposed selector replacement — not yet applied."""
    proposal_id: str = ""
    original_selector: str = ""
    proposed_selector: str = ""
    rationale: str = ""
    affected_file: str = ""
    line_number: int = 0
    confidence: str = "medium"  # high | medium | low
    applied: bool = False


@dataclass
class SelfHealingReport(SchemaMixin):
    """Self-healing proposal report — proposals only by default."""
    project_id: str = ""
    generated_at: str = ""
    proposals: List[SelfHealingProposal] = field(default_factory=list)
    total_proposals: int = 0
    applied_proposals: int = 0
    notes: List[str] = field(default_factory=list)
    status: str = "proposal_generated"  # analysis_only | proposal_generated | patch_applied | partial
    # Safety invariants
    read_only: bool = True
    auto_apply_changes: bool = False
    code_modification_allowed: bool = False
    production_write_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.read_only = True
        self.auto_apply_changes = False
        self.code_modification_allowed = False
        self.production_write_allowed = False
        self.human_review_required = True

"""Phase 5N — Accessibility schema.

Safety invariants (hardcoded in __post_init__):
- read_only=True
- active_scan_allowed=False
- exploit_attempts_allowed=False
- human_review_required=True
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.schemas.base import SchemaMixin

WCAG_LEVELS = ("A", "AA", "AAA")
VIOLATION_IMPACTS = ("critical", "serious", "moderate", "minor")

ACCESSIBILITY_CHECKS = (
    "heading-order",
    "image-alt",
    "color-contrast",
    "keyboard-navigation",
    "form-labels",
    "link-name",
    "html-lang",
    "skip-link",
    "aria-roles",
    "focus-visible",
)


@dataclass
class AccessibilityViolation(SchemaMixin):
    """A single accessibility violation (template — populated after execution)."""
    rule_id: str = ""
    impact: str = ""
    description: str = ""
    wcag_criteria: List[str] = field(default_factory=list)
    element: str = ""
    url: str = ""


@dataclass
class AccessibilityReport(SchemaMixin):
    """Accessibility smoke plan — planning artifact only."""
    project_id: str = ""
    generated_at: str = ""
    target_url: str = ""
    wcag_level: str = "AA"
    checks_planned: List[str] = field(default_factory=list)
    violations: List[AccessibilityViolation] = field(default_factory=list)
    total_violations: int = 0
    generated_test_file: str = ""
    notes: List[str] = field(default_factory=list)
    # Execution status tracking
    status: str = "planning_only"  # planning_only | executed | partial
    checks_executed: List[str] = field(default_factory=list)
    checks_skipped: List[str] = field(default_factory=list)
    checks_blocked: List[str] = field(default_factory=list)
    # Safety invariants
    read_only: bool = True
    active_scan_allowed: bool = False
    exploit_attempts_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.read_only = True
        self.active_scan_allowed = False
        self.exploit_attempts_allowed = False
        self.human_review_required = True

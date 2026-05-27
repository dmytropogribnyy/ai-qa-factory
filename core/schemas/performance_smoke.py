"""Phase 5N — Performance smoke schema.

Safety invariants (hardcoded in __post_init__):
- read_only=True
- load_testing_allowed=False
- active_scan_allowed=False
- production_write_allowed=False
- human_review_required=True
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.schemas.base import SchemaMixin

PERFORMANCE_METRICS = ("LCP", "FCP", "TTFB", "TBT", "CLS")

DEFAULT_THRESHOLDS = {
    "LCP": 2500,
    "FCP": 1800,
    "TTFB": 800,
    "TBT": 300,
    "CLS": 100,
}


@dataclass
class PerformanceThreshold(SchemaMixin):
    """A single Core Web Vitals / timing threshold (template — populated after execution)."""
    metric: str = ""
    threshold_ms: int = 0
    guidance: str = ""


@dataclass
class PerformanceSmokeReport(SchemaMixin):
    """Performance smoke plan — planning artifact only."""
    project_id: str = ""
    generated_at: str = ""
    target_url: str = ""
    thresholds: List[PerformanceThreshold] = field(default_factory=list)
    endpoints_to_measure: List[str] = field(default_factory=list)
    generated_test_file: str = ""
    notes: List[str] = field(default_factory=list)
    # Execution status tracking
    status: str = "planning_only"  # planning_only | executed | partial
    endpoints_measured: List[str] = field(default_factory=list)
    endpoints_skipped: List[str] = field(default_factory=list)
    # Safety invariants
    read_only: bool = True
    load_testing_allowed: bool = False
    active_scan_allowed: bool = False
    production_write_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.read_only = True
        self.load_testing_allowed = False
        self.active_scan_allowed = False
        self.production_write_allowed = False
        self.human_review_required = True

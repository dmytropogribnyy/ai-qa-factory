"""
Phase 5I — Visual Regression Runner schemas.

Playwright toHaveScreenshot()-based visual regression:
- capture mode: take baseline screenshots
- compare mode: diff against baseline, report failures
- update mode: update baselines with current screenshots

Safety invariants (hardcoded in __post_init__ + from_dict):
- credentials_used=False
- auth_performed=False
- safe_to_deliver=False
- approved_for_client_delivery=False
- human_review_required=True
- baselines_committed=False (baselines stay in outputs/, gitignored by default)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.schemas.base import SchemaMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VISUAL_REGRESSION_MODES = (
    "capture",   # capture baseline screenshots (first run or after intentional change)
    "compare",   # compare current against baseline, report pixel diffs
    "update",    # update existing baselines to match current (after approved change)
)

VISUAL_DIFF_VERDICTS = (
    "pass",      # no visual difference detected
    "fail",      # visual difference exceeds threshold
    "new",       # no baseline exists yet; treated as capture
    "error",     # could not compare (missing file, Playwright error)
)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

@dataclass
class VisualBaselineRecord(SchemaMixin):
    """Metadata about a captured baseline screenshot."""
    test_name: str = ""
    screenshot_filename: str = ""
    device_name: str = ""
    viewport: str = ""
    target_url: str = ""
    captured_at: str = ""
    file_size_bytes: int = 0

    @classmethod
    def from_dict(cls, data: dict) -> "VisualBaselineRecord":
        return cls(
            test_name=str(data.get("test_name", "")),
            screenshot_filename=str(data.get("screenshot_filename", "")),
            device_name=str(data.get("device_name", "")),
            viewport=str(data.get("viewport", "")),
            target_url=str(data.get("target_url", "")),
            captured_at=str(data.get("captured_at", "")),
            file_size_bytes=int(data.get("file_size_bytes", 0)),
        )


@dataclass
class VisualDiffResult(SchemaMixin):
    """Result of comparing a single test screenshot against its baseline."""
    test_name: str = ""
    verdict: str = "error"    # pass | fail | new | error
    baseline_path: str = ""
    actual_path: str = ""
    diff_path: str = ""
    pixel_diff_count: int = 0
    diff_ratio: float = 0.0   # fraction of pixels that differ
    threshold_ratio: float = 0.01  # configured tolerance (1% default)
    device_name: str = ""
    viewport: str = ""
    error_message: str = ""

    @classmethod
    def from_dict(cls, data: dict) -> "VisualDiffResult":
        return cls(
            test_name=str(data.get("test_name", "")),
            verdict=str(data.get("verdict", "error")),
            baseline_path=str(data.get("baseline_path", "")),
            actual_path=str(data.get("actual_path", "")),
            diff_path=str(data.get("diff_path", "")),
            pixel_diff_count=int(data.get("pixel_diff_count", 0)),
            diff_ratio=float(data.get("diff_ratio", 0.0)),
            threshold_ratio=float(data.get("threshold_ratio", 0.01)),
            device_name=str(data.get("device_name", "")),
            viewport=str(data.get("viewport", "")),
            error_message=str(data.get("error_message", "")),
        )


@dataclass
class VisualRegressionReport(SchemaMixin):
    """Consolidated visual regression report for one run."""
    project_id: str = ""
    mode: str = ""
    device_name: str = ""
    target_url: str = ""
    total_tests: int = 0
    passed: int = 0
    failed: int = 0
    new_baselines: int = 0
    errors: int = 0
    results: List[VisualDiffResult] = field(default_factory=list)
    baselines: List[VisualBaselineRecord] = field(default_factory=list)
    execution_status: str = "pending"
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    # Hardcoded safety fields
    credentials_used: bool = False
    auth_performed: bool = False
    safe_to_deliver: bool = False
    approved_for_client_delivery: bool = False
    human_review_required: bool = True
    baselines_committed: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "credentials_used", False)
        object.__setattr__(self, "auth_performed", False)
        object.__setattr__(self, "safe_to_deliver", False)
        object.__setattr__(self, "approved_for_client_delivery", False)
        object.__setattr__(self, "human_review_required", True)
        object.__setattr__(self, "baselines_committed", False)

    @classmethod
    def from_dict(cls, data: dict) -> "VisualRegressionReport":
        results = [VisualDiffResult.from_dict(r) for r in data.get("results", [])]
        baselines = [VisualBaselineRecord.from_dict(b) for b in data.get("baselines", [])]
        obj = cls(
            project_id=str(data.get("project_id", "")),
            mode=str(data.get("mode", "")),
            device_name=str(data.get("device_name", "")),
            target_url=str(data.get("target_url", "")),
            total_tests=int(data.get("total_tests", 0)),
            passed=int(data.get("passed", 0)),
            failed=int(data.get("failed", 0)),
            new_baselines=int(data.get("new_baselines", 0)),
            errors=int(data.get("errors", 0)),
            results=results,
            baselines=baselines,
            execution_status=str(data.get("execution_status", "pending")),
            blockers=list(data.get("blockers", [])),
            notes=list(data.get("notes", [])),
        )
        object.__setattr__(obj, "credentials_used", False)
        object.__setattr__(obj, "auth_performed", False)
        object.__setattr__(obj, "safe_to_deliver", False)
        object.__setattr__(obj, "approved_for_client_delivery", False)
        object.__setattr__(obj, "human_review_required", True)
        object.__setattr__(obj, "baselines_committed", False)
        return obj

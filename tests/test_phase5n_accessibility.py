"""Phase 5N tests — Accessibility smoke runner and schema."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.accessibility_runner import AccessibilityRunner
from core.schemas.accessibility import (
    ACCESSIBILITY_CHECKS,
    WCAG_LEVELS,
    AccessibilityReport,
    AccessibilityViolation,
)


# ---------------------------------------------------------------------------
# TestAccessibilitySchemas — dataclass safety invariants
# ---------------------------------------------------------------------------

class TestAccessibilitySchemas:
    def test_report_read_only_hardcoded(self):
        r = AccessibilityReport(read_only=False)
        assert r.read_only is True

    def test_report_active_scan_blocked(self):
        r = AccessibilityReport(active_scan_allowed=True)
        assert r.active_scan_allowed is False

    def test_report_exploit_blocked(self):
        r = AccessibilityReport(exploit_attempts_allowed=True)
        assert r.exploit_attempts_allowed is False

    def test_report_human_review_required(self):
        r = AccessibilityReport(human_review_required=False)
        assert r.human_review_required is True

    def test_report_defaults_planning_only(self):
        assert AccessibilityReport().status == "planning_only"

    def test_report_checks_planned_empty_by_default(self):
        assert AccessibilityReport().checks_planned == []

    def test_report_checks_executed_empty_by_default(self):
        assert AccessibilityReport().checks_executed == []

    def test_report_checks_skipped_empty_by_default(self):
        assert AccessibilityReport().checks_skipped == []

    def test_report_checks_blocked_empty_by_default(self):
        assert AccessibilityReport().checks_blocked == []

    def test_report_to_dict_contains_safety_flags(self):
        d = AccessibilityReport().to_dict()
        assert d["read_only"] is True
        assert d["active_scan_allowed"] is False
        assert d["exploit_attempts_allowed"] is False
        assert d["human_review_required"] is True

    def test_report_from_dict_injection_blocked(self):
        d = AccessibilityReport().to_dict()
        d["read_only"] = False
        d["active_scan_allowed"] = True
        d["exploit_attempts_allowed"] = True
        d["human_review_required"] = False
        r = AccessibilityReport.from_dict(d)
        assert r.read_only is True
        assert r.active_scan_allowed is False
        assert r.exploit_attempts_allowed is False
        assert r.human_review_required is True

    def test_wcag_levels_tuple(self):
        assert "AA" in WCAG_LEVELS
        assert "A" in WCAG_LEVELS
        assert "AAA" in WCAG_LEVELS

    def test_accessibility_checks_nonempty(self):
        assert len(ACCESSIBILITY_CHECKS) >= 5

    def test_violation_dataclass_defaults(self):
        v = AccessibilityViolation()
        assert v.rule_id == ""
        assert v.impact == ""
        assert v.wcag_criteria == []

    def test_violation_to_dict(self):
        v = AccessibilityViolation(rule_id="heading-order", impact="moderate")
        d = v.to_dict()
        assert d["rule_id"] == "heading-order"
        assert d["impact"] == "moderate"

    def test_report_wcag_level_default_aa(self):
        assert AccessibilityReport().wcag_level == "AA"

    def test_report_violations_list_default(self):
        assert AccessibilityReport().violations == []

    def test_report_total_violations_default_zero(self):
        assert AccessibilityReport().total_violations == 0

    def test_report_to_dict_status_present(self):
        assert "status" in AccessibilityReport().to_dict()


# ---------------------------------------------------------------------------
# TestAccessibilityRunner — generate_plan behaviour
# ---------------------------------------------------------------------------

class TestAccessibilityRunner:
    def test_generate_plan_returns_report(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        report = r.generate_plan()
        assert isinstance(report, AccessibilityReport)

    def test_generate_plan_status_planning_only(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        assert r.generate_plan().status == "planning_only"

    def test_generate_plan_project_id_set(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        assert r.generate_plan().project_id == "proj-a11y"

    def test_generate_plan_target_url_set(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        assert r.generate_plan().target_url == "https://example.com"

    def test_generate_plan_wcag_level_aa(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        assert r.generate_plan().wcag_level == "AA"

    def test_generate_plan_wcag_level_a(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path), wcag_level="A")
        assert r.generate_plan().wcag_level == "A"

    def test_generate_plan_invalid_wcag_falls_back(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path), wcag_level="X")
        assert r.generate_plan().wcag_level == "AA"

    def test_generate_plan_checks_planned_nonempty(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        assert len(r.generate_plan().checks_planned) > 0

    def test_generate_plan_safety_invariants(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        report = r.generate_plan()
        assert report.read_only is True
        assert report.active_scan_allowed is False
        assert report.exploit_attempts_allowed is False
        assert report.human_review_required is True

    def test_generate_plan_creates_spec_file(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        r.generate_plan()
        out_dir = tmp_path / "proj-a11y" / "29_accessibility"
        assert (out_dir / "accessibility_smoke.generated.spec.ts").exists()

    def test_generate_plan_creates_report_json(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        r.generate_plan()
        out_dir = tmp_path / "proj-a11y" / "29_accessibility"
        assert (out_dir / "accessibility_report.json").exists()

    def test_generate_plan_creates_summary_md(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        r.generate_plan()
        out_dir = tmp_path / "proj-a11y" / "29_accessibility"
        assert (out_dir / "accessibility_summary.md").exists()

    def test_generate_plan_creates_violations_csv(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        r.generate_plan()
        out_dir = tmp_path / "proj-a11y" / "29_accessibility"
        assert (out_dir / "accessibility_violations.csv").exists()

    def test_generate_plan_no_write_no_files(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        r.generate_plan(write_files=False)
        out_dir = tmp_path / "proj-a11y" / "29_accessibility"
        assert not out_dir.exists()

    def test_report_json_parseable(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        r.generate_plan()
        out_dir = tmp_path / "proj-a11y" / "29_accessibility"
        d = json.loads((out_dir / "accessibility_report.json").read_text(encoding="utf-8"))
        assert d["project_id"] == "proj-a11y"

    def test_report_json_safety_flags(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        r.generate_plan()
        out_dir = tmp_path / "proj-a11y" / "29_accessibility"
        d = json.loads((out_dir / "accessibility_report.json").read_text(encoding="utf-8"))
        assert d["read_only"] is True
        assert d["active_scan_allowed"] is False


# ---------------------------------------------------------------------------
# TestAccessibilitySpecContent — generated spec quality
# ---------------------------------------------------------------------------

class TestAccessibilitySpecContent:
    def _spec(self, tmp_path) -> str:
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        r.generate_plan()
        return (tmp_path / "proj-a11y" / "29_accessibility" / "accessibility_smoke.generated.spec.ts").read_text(
            encoding="utf-8"
        )

    def test_spec_imports_axe_builder(self, tmp_path):
        assert "AxeBuilder" in self._spec(tmp_path)

    def test_spec_imports_playwright(self, tmp_path):
        assert "@playwright/test" in self._spec(tmp_path)

    def test_spec_contains_target_url(self, tmp_path):
        assert "https://example.com" in self._spec(tmp_path)

    def test_spec_has_accessibility_tag(self, tmp_path):
        assert "@accessibility" in self._spec(tmp_path)

    def test_spec_has_smoke_tag(self, tmp_path):
        assert "@smoke" in self._spec(tmp_path)

    def test_spec_contains_wcag_level(self, tmp_path):
        assert "AA" in self._spec(tmp_path)

    def test_spec_has_test_describe(self, tmp_path):
        assert "test.describe(" in self._spec(tmp_path)

    def test_spec_has_planning_notice(self, tmp_path):
        assert "planning_only" in self._spec(tmp_path)

    def test_spec_has_human_review_notice(self, tmp_path):
        assert "human review" in self._spec(tmp_path).lower()

    def test_summary_has_draft_notice(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        r.generate_plan()
        content = (
            tmp_path / "proj-a11y" / "29_accessibility" / "accessibility_summary.md"
        ).read_text(encoding="utf-8")
        assert "DRAFT" in content or "planning_only" in content

    def test_violations_csv_has_header(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        r.generate_plan()
        content = (
            tmp_path / "proj-a11y" / "29_accessibility" / "accessibility_violations.csv"
        ).read_text(encoding="utf-8")
        assert "rule_id" in content


# ---------------------------------------------------------------------------
# TestAccessibilityExecution — approved path
# ---------------------------------------------------------------------------

class TestAccessibilityExecution:
    def test_execute_without_approvals_raises(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        with pytest.raises(ValueError, match="approve-public-readonly"):
            r.execute(approve_public_readonly=False, approve_browser_execution=False)

    def test_execute_without_browser_approval_raises(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        with pytest.raises(ValueError, match="approve-browser-execution"):
            r.execute(approve_public_readonly=True, approve_browser_execution=False)

    def test_execute_approved_returns_report(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        report = r.execute(approve_public_readonly=True, approve_browser_execution=True)
        assert isinstance(report, AccessibilityReport)

    def test_execute_approved_still_planning_only(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        report = r.execute(approve_public_readonly=True, approve_browser_execution=True)
        assert report.status == "planning_only"

    def test_execute_approved_adds_run_note(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        report = r.execute(approve_public_readonly=True, approve_browser_execution=True)
        notes_text = " ".join(report.notes).lower()
        assert "npx playwright test" in notes_text or "execution approved" in notes_text

    def test_execute_approved_safety_invariants_intact(self, tmp_path):
        r = AccessibilityRunner("proj-a11y", "https://example.com", str(tmp_path))
        report = r.execute(approve_public_readonly=True, approve_browser_execution=True)
        assert report.read_only is True
        assert report.active_scan_allowed is False
        assert report.human_review_required is True


# ---------------------------------------------------------------------------
# TestCLIAccessibility — CLI tool
# ---------------------------------------------------------------------------

_CLI = [sys.executable, "tools/run_accessibility_smoke.py"]
_CWD = str(Path(__file__).parent.parent)


class TestCLIAccessibility:
    def test_no_args_exits_2(self):
        r = subprocess.run(_CLI, capture_output=True, cwd=_CWD)
        assert r.returncode == 2

    def test_help_exits_0(self):
        r = subprocess.run([*_CLI, "--help"], capture_output=True, cwd=_CWD)
        assert r.returncode == 0

    def test_blocked_flag_active_scan_exits_1(self):
        r = subprocess.run(
            [*_CLI, "--project-id", "x", "--target-url", "http://x.com", "--allow-active-scan"],
            capture_output=True, cwd=_CWD,
        )
        assert r.returncode == 1

    def test_blocked_flag_bypass_auth_exits_1(self):
        r = subprocess.run(
            [*_CLI, "--project-id", "x", "--target-url", "http://x.com", "--bypass-auth"],
            capture_output=True, cwd=_CWD,
        )
        assert r.returncode == 1

    def test_execute_without_approval_exits_1(self):
        r = subprocess.run(
            [*_CLI, "--project-id", "x", "--target-url", "http://x.com", "--execute", "--no-write"],
            capture_output=True, cwd=_CWD,
        )
        assert r.returncode == 1

    def test_plan_mode_exits_0(self, tmp_path):
        r = subprocess.run(
            [
                *_CLI, "--project-id", "x", "--target-url", "http://x.com",
                "--no-write", "--outputs-root", str(tmp_path),
            ],
            capture_output=True, cwd=_CWD,
        )
        assert r.returncode == 0

    def test_plan_mode_output_contains_status(self, tmp_path):
        r = subprocess.run(
            [
                *_CLI, "--project-id", "x", "--target-url", "http://x.com",
                "--no-write", "--outputs-root", str(tmp_path),
            ],
            capture_output=True, text=True, cwd=_CWD,
        )
        assert "planning_only" in r.stdout

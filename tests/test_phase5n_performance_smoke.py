"""Phase 5N tests — Performance smoke runner and schema."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.performance_smoke_runner import PerformanceSmokeRunner
from core.schemas.performance_smoke import (
    DEFAULT_THRESHOLDS,
    PERFORMANCE_METRICS,
    PerformanceSmokeReport,
    PerformanceThreshold,
)


# ---------------------------------------------------------------------------
# TestPerformanceSmokeSchemas — dataclass safety invariants
# ---------------------------------------------------------------------------

class TestPerformanceSmokeSchemas:
    def test_report_read_only_hardcoded(self):
        r = PerformanceSmokeReport(read_only=False)
        assert r.read_only is True

    def test_report_load_testing_blocked(self):
        r = PerformanceSmokeReport(load_testing_allowed=True)
        assert r.load_testing_allowed is False

    def test_report_active_scan_blocked(self):
        r = PerformanceSmokeReport(active_scan_allowed=True)
        assert r.active_scan_allowed is False

    def test_report_production_write_blocked(self):
        r = PerformanceSmokeReport(production_write_allowed=True)
        assert r.production_write_allowed is False

    def test_report_human_review_required(self):
        r = PerformanceSmokeReport(human_review_required=False)
        assert r.human_review_required is True

    def test_report_defaults_planning_only(self):
        assert PerformanceSmokeReport().status == "planning_only"

    def test_report_endpoints_measured_empty_by_default(self):
        assert PerformanceSmokeReport().endpoints_measured == []

    def test_report_endpoints_skipped_empty_by_default(self):
        assert PerformanceSmokeReport().endpoints_skipped == []

    def test_report_to_dict_contains_safety_flags(self):
        d = PerformanceSmokeReport().to_dict()
        assert d["read_only"] is True
        assert d["load_testing_allowed"] is False
        assert d["active_scan_allowed"] is False
        assert d["human_review_required"] is True

    def test_report_from_dict_injection_blocked(self):
        d = PerformanceSmokeReport().to_dict()
        d["read_only"] = False
        d["load_testing_allowed"] = True
        d["production_write_allowed"] = True
        d["human_review_required"] = False
        r = PerformanceSmokeReport.from_dict(d)
        assert r.read_only is True
        assert r.load_testing_allowed is False
        assert r.production_write_allowed is False
        assert r.human_review_required is True

    def test_performance_metrics_tuple(self):
        assert "LCP" in PERFORMANCE_METRICS
        assert "FCP" in PERFORMANCE_METRICS
        assert "TTFB" in PERFORMANCE_METRICS

    def test_default_thresholds_lcp(self):
        assert DEFAULT_THRESHOLDS["LCP"] == 2500

    def test_default_thresholds_fcp(self):
        assert DEFAULT_THRESHOLDS["FCP"] == 1800

    def test_default_thresholds_ttfb(self):
        assert DEFAULT_THRESHOLDS["TTFB"] == 800

    def test_threshold_dataclass_defaults(self):
        t = PerformanceThreshold()
        assert t.metric == ""
        assert t.threshold_ms == 0

    def test_threshold_to_dict(self):
        t = PerformanceThreshold(metric="LCP", threshold_ms=2500)
        d = t.to_dict()
        assert d["metric"] == "LCP"
        assert d["threshold_ms"] == 2500

    def test_report_to_dict_status_present(self):
        assert "status" in PerformanceSmokeReport().to_dict()


# ---------------------------------------------------------------------------
# TestPerformanceSmokeRunner — generate_plan behaviour
# ---------------------------------------------------------------------------

class TestPerformanceSmokeRunner:
    def test_generate_plan_returns_report(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        assert isinstance(r.generate_plan(), PerformanceSmokeReport)

    def test_generate_plan_status_planning_only(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        assert r.generate_plan().status == "planning_only"

    def test_generate_plan_project_id_set(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        assert r.generate_plan().project_id == "proj-perf"

    def test_generate_plan_target_url_set(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        assert r.generate_plan().target_url == "https://example.com"

    def test_generate_plan_thresholds_nonempty(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        assert len(r.generate_plan().thresholds) > 0

    def test_generate_plan_thresholds_include_lcp(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        metrics = [t.metric for t in r.generate_plan().thresholds]
        assert "LCP" in metrics

    def test_generate_plan_safety_invariants(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        report = r.generate_plan()
        assert report.read_only is True
        assert report.load_testing_allowed is False
        assert report.active_scan_allowed is False
        assert report.human_review_required is True

    def test_generate_plan_creates_spec_file(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        r.generate_plan()
        assert (tmp_path / "proj-perf" / "30_performance" / "performance_smoke.generated.spec.ts").exists()

    def test_generate_plan_creates_report_json(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        r.generate_plan()
        assert (tmp_path / "proj-perf" / "30_performance" / "performance_report.json").exists()

    def test_generate_plan_creates_summary_md(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        r.generate_plan()
        assert (tmp_path / "proj-perf" / "30_performance" / "performance_summary.md").exists()

    def test_generate_plan_creates_slow_resources_json(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        r.generate_plan()
        assert (tmp_path / "proj-perf" / "30_performance" / "slow_resources.json").exists()

    def test_generate_plan_no_write_no_files(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        r.generate_plan(write_files=False)
        assert not (tmp_path / "proj-perf").exists()

    def test_report_json_parseable(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        r.generate_plan()
        d = json.loads(
            (tmp_path / "proj-perf" / "30_performance" / "performance_report.json").read_text(
                encoding="utf-8"
            )
        )
        assert d["project_id"] == "proj-perf"

    def test_report_json_safety_flags(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        r.generate_plan()
        d = json.loads(
            (tmp_path / "proj-perf" / "30_performance" / "performance_report.json").read_text(
                encoding="utf-8"
            )
        )
        assert d["load_testing_allowed"] is False

    def test_endpoints_to_measure_default(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        report = r.generate_plan()
        assert "/" in report.endpoints_to_measure

    def test_custom_endpoints_included(self, tmp_path):
        r = PerformanceSmokeRunner(
            "proj-perf", "https://example.com", str(tmp_path),
            endpoints_to_measure=["/", "/about", "/products"],
        )
        report = r.generate_plan()
        assert "/about" in report.endpoints_to_measure


# ---------------------------------------------------------------------------
# TestPerformanceSpecContent — generated spec quality
# ---------------------------------------------------------------------------

class TestPerformanceSpecContent:
    def _spec(self, tmp_path) -> str:
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        r.generate_plan()
        return (
            tmp_path / "proj-perf" / "30_performance" / "performance_smoke.generated.spec.ts"
        ).read_text(encoding="utf-8")

    def test_spec_imports_playwright(self, tmp_path):
        assert "@playwright/test" in self._spec(tmp_path)

    def test_spec_contains_target_url(self, tmp_path):
        assert "https://example.com" in self._spec(tmp_path)

    def test_spec_has_performance_tag(self, tmp_path):
        assert "@performance" in self._spec(tmp_path)

    def test_spec_has_smoke_tag(self, tmp_path):
        assert "@smoke" in self._spec(tmp_path)

    def test_spec_contains_lcp_threshold(self, tmp_path):
        assert "LCP_THRESHOLD_MS" in self._spec(tmp_path)

    def test_spec_contains_fcp_threshold(self, tmp_path):
        assert "FCP_THRESHOLD_MS" in self._spec(tmp_path)

    def test_spec_has_test_describe(self, tmp_path):
        assert "test.describe(" in self._spec(tmp_path)

    def test_spec_has_planning_notice(self, tmp_path):
        assert "planning_only" in self._spec(tmp_path)

    def test_summary_contains_thresholds_table(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        r.generate_plan()
        content = (
            tmp_path / "proj-perf" / "30_performance" / "performance_summary.md"
        ).read_text(encoding="utf-8")
        assert "LCP" in content and "2500" in content

    def test_summary_has_draft_notice(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        r.generate_plan()
        content = (
            tmp_path / "proj-perf" / "30_performance" / "performance_summary.md"
        ).read_text(encoding="utf-8")
        assert "DRAFT" in content or "planning_only" in content


# ---------------------------------------------------------------------------
# TestPerformanceExecution — approved path
# ---------------------------------------------------------------------------

class TestPerformanceExecution:
    def test_execute_without_approvals_raises(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        with pytest.raises(ValueError, match="approve-public-readonly"):
            r.execute(approve_public_readonly=False, approve_browser_execution=False)

    def test_execute_without_browser_approval_raises(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        with pytest.raises(ValueError, match="approve-browser-execution"):
            r.execute(approve_public_readonly=True, approve_browser_execution=False)

    def test_execute_approved_returns_report(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        report = r.execute(approve_public_readonly=True, approve_browser_execution=True)
        assert isinstance(report, PerformanceSmokeReport)

    def test_execute_approved_safety_invariants_intact(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        report = r.execute(approve_public_readonly=True, approve_browser_execution=True)
        assert report.read_only is True
        assert report.load_testing_allowed is False
        assert report.human_review_required is True

    def test_execute_approved_adds_run_note(self, tmp_path):
        r = PerformanceSmokeRunner("proj-perf", "https://example.com", str(tmp_path))
        report = r.execute(approve_public_readonly=True, approve_browser_execution=True)
        notes_text = " ".join(report.notes).lower()
        assert "npx playwright test" in notes_text or "execution approved" in notes_text


# ---------------------------------------------------------------------------
# TestCLIPerformance — CLI tool
# ---------------------------------------------------------------------------

_CLI = [sys.executable, "tools/run_performance_smoke.py"]
_CWD = str(Path(__file__).parent.parent)


class TestCLIPerformance:
    def test_no_args_exits_2(self):
        r = subprocess.run(_CLI, capture_output=True, cwd=_CWD)
        assert r.returncode == 2

    def test_help_exits_0(self):
        r = subprocess.run([*_CLI, "--help"], capture_output=True, cwd=_CWD)
        assert r.returncode == 0

    def test_blocked_flag_load_test_exits_1(self):
        r = subprocess.run(
            [*_CLI, "--project-id", "x", "--target-url", "http://x.com", "--load-test"],
            capture_output=True, cwd=_CWD,
        )
        assert r.returncode == 1

    def test_blocked_flag_allow_writes_exits_1(self):
        r = subprocess.run(
            [*_CLI, "--project-id", "x", "--target-url", "http://x.com", "--allow-writes"],
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

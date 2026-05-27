"""Phase 5O tests — Flaky test analyzer, selector stability, and self-healing proposals."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from core.flaky_test_analyzer import FlakyTestAnalyzer
from core.schemas.flaky_test_analysis import (
    RISK_CATEGORIES,
    SELECTOR_STABILITY_LEVELS,
    SEVERITY_LEVELS,
    FlakinessRisk,
    FlakyTestAnalysisReport,
    SelfHealingProposal,
    SelfHealingReport,
    SelectorFinding,
    SelectorStabilityReport,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "demo_quality_audit" / "playwright_specs"
_STABLE_SPEC = _FIXTURES / "stable_test.spec.ts"
_FLAKY_SPEC = _FIXTURES / "flaky_test.spec.ts"
_CLI = Path(__file__).parent.parent / "tools" / "run_flaky_test_analyzer.py"


# ===========================================================================
# Schema — safety invariants
# ===========================================================================

class TestFlakyTestAnalysisSchemaInvariants:
    def test_report_read_only_always_true(self):
        r = FlakyTestAnalysisReport(project_id="p", read_only=False)
        assert r.read_only is True

    def test_report_auto_apply_always_false(self):
        r = FlakyTestAnalysisReport(project_id="p", auto_apply_changes=True)
        assert r.auto_apply_changes is False

    def test_report_code_modification_always_false(self):
        r = FlakyTestAnalysisReport(project_id="p", code_modification_allowed=True)
        assert r.code_modification_allowed is False

    def test_report_human_review_always_true(self):
        r = FlakyTestAnalysisReport(project_id="p", human_review_required=False)
        assert r.human_review_required is True

    def test_report_from_dict_injection_blocked(self):
        d = FlakyTestAnalysisReport(project_id="p").to_dict()
        d["code_modification_allowed"] = True
        d["auto_apply_changes"] = True
        d["read_only"] = False
        d["human_review_required"] = False
        r = FlakyTestAnalysisReport.from_dict(d)
        assert r.code_modification_allowed is False
        assert r.auto_apply_changes is False
        assert r.read_only is True
        assert r.human_review_required is True


class TestSelectorStabilitySchemaInvariants:
    def test_read_only_always_true(self):
        r = SelectorStabilityReport(project_id="p", read_only=False)
        assert r.read_only is True

    def test_auto_fix_always_false(self):
        r = SelectorStabilityReport(project_id="p", auto_fix_selectors=True)
        assert r.auto_fix_selectors is False

    def test_human_review_always_true(self):
        r = SelectorStabilityReport(project_id="p", human_review_required=False)
        assert r.human_review_required is True

    def test_from_dict_injection_blocked(self):
        d = SelectorStabilityReport(project_id="p").to_dict()
        d["auto_fix_selectors"] = True
        d["read_only"] = False
        r = SelectorStabilityReport.from_dict(d)
        assert r.auto_fix_selectors is False
        assert r.read_only is True


class TestSelfHealingSchemaInvariants:
    def test_read_only_always_true(self):
        r = SelfHealingReport(project_id="p", read_only=False)
        assert r.read_only is True

    def test_auto_apply_always_false(self):
        r = SelfHealingReport(project_id="p", auto_apply_changes=True)
        assert r.auto_apply_changes is False

    def test_code_modification_always_false(self):
        r = SelfHealingReport(project_id="p", code_modification_allowed=True)
        assert r.code_modification_allowed is False

    def test_production_write_always_false(self):
        r = SelfHealingReport(project_id="p", production_write_allowed=True)
        assert r.production_write_allowed is False

    def test_human_review_always_true(self):
        r = SelfHealingReport(project_id="p", human_review_required=False)
        assert r.human_review_required is True

    def test_from_dict_injection_blocked(self):
        d = SelfHealingReport(project_id="p").to_dict()
        d["auto_apply_changes"] = True
        d["code_modification_allowed"] = True
        d["production_write_allowed"] = True
        d["read_only"] = False
        r = SelfHealingReport.from_dict(d)
        assert r.auto_apply_changes is False
        assert r.code_modification_allowed is False
        assert r.production_write_allowed is False
        assert r.read_only is True


# ===========================================================================
# Schema — constants and fields
# ===========================================================================

class TestSchemaConstants:
    def test_risk_categories_defined(self):
        assert "hard_wait" in RISK_CATEGORIES
        assert "fragile_selector" in RISK_CATEGORIES
        assert "race_prone" in RISK_CATEGORIES
        assert "non_web_first_assertion" in RISK_CATEGORIES
        assert "dynamic_selector" in RISK_CATEGORIES

    def test_severity_levels_defined(self):
        for level in ("critical", "high", "medium", "low"):
            assert level in SEVERITY_LEVELS

    def test_selector_stability_levels_defined(self):
        for level in ("strong", "medium", "weak", "unknown"):
            assert level in SELECTOR_STABILITY_LEVELS

    def test_flakiness_risk_defaults(self):
        r = FlakinessRisk()
        assert r.confidence_level == "medium"
        assert r.line_number == 0

    def test_selector_finding_defaults(self):
        f = SelectorFinding()
        assert f.stability_level == "unknown"

    def test_self_healing_proposal_defaults(self):
        p = SelfHealingProposal()
        assert p.applied is False
        assert p.confidence == "medium"


# ===========================================================================
# Fixture files — existence check
# ===========================================================================

class TestFixtureFiles:
    def test_stable_spec_exists(self):
        assert _STABLE_SPEC.exists(), f"Missing: {_STABLE_SPEC}"

    def test_flaky_spec_exists(self):
        assert _FLAKY_SPEC.exists(), f"Missing: {_FLAKY_SPEC}"

    def test_stable_spec_has_getbyrole(self):
        content = _STABLE_SPEC.read_text(encoding="utf-8")
        assert "getByRole" in content

    def test_stable_spec_has_domcontentloaded(self):
        content = _STABLE_SPEC.read_text(encoding="utf-8")
        assert "domcontentloaded" in content

    def test_flaky_spec_has_wait_for_timeout(self):
        content = _FLAKY_SPEC.read_text(encoding="utf-8")
        assert "waitForTimeout" in content

    def test_flaky_spec_has_nth(self):
        content = _FLAKY_SPEC.read_text(encoding="utf-8")
        assert ".nth(" in content

    def test_flaky_spec_has_xpath(self):
        content = _FLAKY_SPEC.read_text(encoding="utf-8")
        assert "xpath=" in content


# ===========================================================================
# FlakyTestAnalyzer.analyze()
# ===========================================================================

class TestAnalyzeFlakiness:
    def test_analyze_detects_risks_in_flaky_spec(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.analyze(write_files=False)
        assert report.total_risks > 0

    def test_analyze_detects_hard_wait(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.analyze(write_files=False)
        categories = [r.risk_category for r in report.risks]
        assert "hard_wait" in categories

    def test_analyze_detects_fragile_selector(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.analyze(write_files=False)
        categories = [r.risk_category for r in report.risks]
        assert "fragile_selector" in categories

    def test_analyze_low_risk_in_stable_spec(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_STABLE_SPEC)],
        )
        report = analyzer.analyze(write_files=False)
        high_risks = [r for r in report.risks if r.severity == "high"]
        assert len(high_risks) == 0, f"Stable spec should have no high risks, found: {high_risks}"

    def test_analyze_files_analyzed_populated(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.analyze(write_files=False)
        assert len(report.files_analyzed) == 1
        assert "flaky_test.spec.ts" in report.files_analyzed[0]

    def test_analyze_report_has_project_id(self):
        analyzer = FlakyTestAnalyzer(
            project_id="my-project",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.analyze(write_files=False)
        assert report.project_id == "my-project"

    def test_analyze_risks_by_severity_populated(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.analyze(write_files=False)
        assert isinstance(report.risks_by_severity, dict)
        assert sum(report.risks_by_severity.values()) == report.total_risks

    def test_analyze_status_complete_when_files_analyzed(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.analyze(write_files=False)
        assert report.status == "complete"

    def test_analyze_status_analysis_only_when_no_files(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=["nonexistent.spec.ts"],
        )
        report = analyzer.analyze(write_files=False)
        assert report.status == "analysis_only"

    def test_analyze_skips_comment_lines(self):
        with tempfile.NamedTemporaryFile(suffix=".spec.ts", mode="w", encoding="utf-8", delete=False) as f:
            f.write("// await page.waitForTimeout(999)\n")
            fname = f.name
        try:
            analyzer = FlakyTestAnalyzer(project_id="p", spec_files=[fname])
            report = analyzer.analyze(write_files=False)
            assert report.total_risks == 0
        finally:
            Path(fname).unlink(missing_ok=True)

    def test_analyze_both_specs(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_STABLE_SPEC), str(_FLAKY_SPEC)],
        )
        report = analyzer.analyze(write_files=False)
        assert len(report.files_analyzed) == 2

    def test_analyze_write_files_creates_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = FlakyTestAnalyzer(
                project_id="write-test",
                outputs_root=tmpdir,
                spec_files=[str(_FLAKY_SPEC)],
            )
            analyzer.analyze(write_files=True)
            out = Path(tmpdir) / "write-test" / "32_flaky_test_analyzer"
            assert (out / "flaky_test_analysis.json").exists()
            assert (out / "Flaky_Test_Analysis_Report.md").exists()

    def test_analyze_json_is_parseable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = FlakyTestAnalyzer(
                project_id="json-test",
                outputs_root=tmpdir,
                spec_files=[str(_FLAKY_SPEC)],
            )
            analyzer.analyze(write_files=True)
            data = json.loads(
                (Path(tmpdir) / "json-test" / "32_flaky_test_analyzer" / "flaky_test_analysis.json").read_text()
            )
            assert data["project_id"] == "json-test"
            assert "risks" in data
            assert data["code_modification_allowed"] is False

    def test_analyze_no_write_produces_no_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = FlakyTestAnalyzer(
                project_id="nw-test",
                outputs_root=tmpdir,
                spec_files=[str(_FLAKY_SPEC)],
            )
            analyzer.analyze(write_files=False)
            out = Path(tmpdir) / "nw-test" / "32_flaky_test_analyzer"
            assert not out.exists()


# ===========================================================================
# FlakyTestAnalyzer.analyze_selectors()
# ===========================================================================

class TestAnalyzeSelectors:
    def test_strong_selectors_in_stable_spec(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_STABLE_SPEC)],
        )
        report = analyzer.analyze_selectors(write_files=False)
        assert report.strong_count > 0

    def test_weak_selectors_in_flaky_spec(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.analyze_selectors(write_files=False)
        assert report.weak_count > 0

    def test_stability_score_high_for_stable_spec(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_STABLE_SPEC)],
        )
        report = analyzer.analyze_selectors(write_files=False)
        assert report.stability_score >= 70.0, f"Expected >=70, got {report.stability_score}"

    def test_stability_score_low_for_flaky_spec(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.analyze_selectors(write_files=False)
        assert report.stability_score < 70.0, f"Expected <70 for flaky spec, got {report.stability_score}"

    def test_stability_score_range(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.analyze_selectors(write_files=False)
        assert 0.0 <= report.stability_score <= 100.0

    def test_selector_report_write_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = FlakyTestAnalyzer(
                project_id="sel-test",
                outputs_root=tmpdir,
                spec_files=[str(_FLAKY_SPEC)],
            )
            analyzer.analyze_selectors(write_files=True)
            out = Path(tmpdir) / "sel-test" / "32_flaky_test_analyzer"
            assert (out / "selector_stability.json").exists()
            assert (out / "Selector_Stability_Report.md").exists()

    def test_selector_report_json_parseable(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = FlakyTestAnalyzer(
                project_id="sel-json",
                outputs_root=tmpdir,
                spec_files=[str(_FLAKY_SPEC)],
            )
            analyzer.analyze_selectors(write_files=True)
            data = json.loads(
                (Path(tmpdir) / "sel-json" / "32_flaky_test_analyzer" / "selector_stability.json").read_text()
            )
            assert "stability_score" in data
            assert data["auto_fix_selectors"] is False

    def test_findings_have_file_names(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.analyze_selectors(write_files=False)
        for finding in report.findings:
            assert finding.affected_file != ""

    def test_findings_stability_levels_valid(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC), str(_STABLE_SPEC)],
        )
        report = analyzer.analyze_selectors(write_files=False)
        for finding in report.findings:
            assert finding.stability_level in SELECTOR_STABILITY_LEVELS


# ===========================================================================
# FlakyTestAnalyzer.generate_healing_proposals()
# ===========================================================================

class TestGenerateHealingProposals:
    def test_proposals_generated_for_flaky_spec(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.generate_healing_proposals(write_files=False)
        assert report.total_proposals > 0

    def test_proposals_status_is_proposal_generated(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.generate_healing_proposals(write_files=False)
        assert report.status == "proposal_generated"

    def test_proposals_not_applied_by_default(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.generate_healing_proposals(write_files=False)
        assert report.applied_proposals == 0
        for p in report.proposals:
            assert p.applied is False

    def test_proposals_have_proposal_ids(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.generate_healing_proposals(write_files=False)
        for p in report.proposals:
            assert p.proposal_id.startswith("HEAL-")

    def test_proposals_have_affected_file(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.generate_healing_proposals(write_files=False)
        for p in report.proposals:
            assert p.affected_file != ""

    def test_proposals_minimal_for_stable_spec(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_STABLE_SPEC)],
        )
        report = analyzer.generate_healing_proposals(write_files=False)
        assert report.total_proposals == 0

    def test_proposals_write_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = FlakyTestAnalyzer(
                project_id="heal-test",
                outputs_root=tmpdir,
                spec_files=[str(_FLAKY_SPEC)],
            )
            analyzer.generate_healing_proposals(write_files=True)
            out = Path(tmpdir) / "heal-test" / "32_flaky_test_analyzer"
            assert (out / "self_healing_proposals.json").exists()
            assert (out / "Self_Healing_Proposals.md").exists()

    def test_proposals_json_has_safety_flags(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            analyzer = FlakyTestAnalyzer(
                project_id="heal-json",
                outputs_root=tmpdir,
                spec_files=[str(_FLAKY_SPEC)],
            )
            analyzer.generate_healing_proposals(write_files=True)
            data = json.loads(
                (Path(tmpdir) / "heal-json" / "32_flaky_test_analyzer" / "self_healing_proposals.json").read_text()
            )
            assert data["code_modification_allowed"] is False
            assert data["auto_apply_changes"] is False
            assert data["production_write_allowed"] is False
            assert data["human_review_required"] is True


# ===========================================================================
# FlakyTestAnalyzer.apply_proposals()
# ===========================================================================

class TestApplyProposals:
    def test_apply_blocked_without_approval(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_FLAKY_SPEC)],
        )
        report = analyzer.generate_healing_proposals(write_files=False)
        with pytest.raises(ValueError, match="approve-code-modification"):
            analyzer.apply_proposals(report, approve_code_modification=False)

    def test_apply_returns_report_with_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Copy flaky spec to tmpdir so apply_proposals can modify it safely
            spec_copy = Path(tmpdir) / "flaky_test.spec.ts"
            spec_copy.write_text(_FLAKY_SPEC.read_text(encoding="utf-8"), encoding="utf-8")
            analyzer = FlakyTestAnalyzer(
                project_id="apply-test",
                outputs_root=tmpdir,
                spec_files=[str(spec_copy)],
            )
            report = analyzer.generate_healing_proposals(write_files=False)
            result = analyzer.apply_proposals(report, approve_code_modification=True, write_files=False)
            assert isinstance(result, SelfHealingReport)

    def test_apply_status_is_patch_applied_or_partial(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_copy = Path(tmpdir) / "flaky_test.spec.ts"
            spec_copy.write_text(_FLAKY_SPEC.read_text(encoding="utf-8"), encoding="utf-8")
            analyzer = FlakyTestAnalyzer(
                project_id="apply-test",
                outputs_root=tmpdir,
                spec_files=[str(spec_copy)],
            )
            report = analyzer.generate_healing_proposals(write_files=False)
            result = analyzer.apply_proposals(report, approve_code_modification=True, write_files=False)
            assert result.status in ("patch_applied", "partial")

    def test_apply_write_false_no_file_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_copy = Path(tmpdir) / "flaky_test.spec.ts"
            original = _FLAKY_SPEC.read_text(encoding="utf-8")
            spec_copy.write_text(original, encoding="utf-8")
            analyzer = FlakyTestAnalyzer(
                project_id="apply-nw",
                outputs_root=tmpdir,
                spec_files=[str(spec_copy)],
            )
            report = analyzer.generate_healing_proposals(write_files=False)
            analyzer.apply_proposals(report, approve_code_modification=True, write_files=False)
            # File should not be modified when write_files=False
            assert spec_copy.read_text(encoding="utf-8") == original

    def test_empty_proposals_returns_analysis_only_status(self):
        analyzer = FlakyTestAnalyzer(
            project_id="test-p",
            spec_files=[str(_STABLE_SPEC)],
        )
        report = analyzer.generate_healing_proposals(write_files=False)
        assert report.status in ("analysis_only", "proposal_generated")


# ===========================================================================
# CLI tool — run_flaky_test_analyzer.py
# ===========================================================================

class TestCLIFlakyAnalyzer:
    def test_no_args_exits_nonzero(self):
        result = subprocess.run(
            [sys.executable, str(_CLI)],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--project-id" in result.stdout

    def test_blocked_auto_fix_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--project-id", "x", "--auto-fix"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_blocked_skip_human_review_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--project-id", "x", "--skip-human-review"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_blocked_approve_delivery_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--project-id", "x", "--approve-delivery"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_blocked_force_apply_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--project-id", "x", "--force-apply"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_run_with_spec_files_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable, str(_CLI),
                    "--project-id", "cli-test",
                    "--spec-files", str(_FLAKY_SPEC), str(_STABLE_SPEC),
                    "--outputs-root", tmpdir,
                    "--no-write",
                ],
                capture_output=True, text=True,
            )
            assert result.returncode == 0, result.stderr
            assert "[OK]" in result.stdout

    def test_run_output_shows_project_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable, str(_CLI),
                    "--project-id", "my-cli-proj",
                    "--spec-files", str(_FLAKY_SPEC),
                    "--outputs-root", tmpdir,
                    "--no-write",
                ],
                capture_output=True, text=True,
            )
            assert "my-cli-proj" in result.stdout

    def test_apply_without_approve_exits_1(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable, str(_CLI),
                    "--project-id", "cli-apply-block",
                    "--spec-files", str(_FLAKY_SPEC),
                    "--outputs-root", tmpdir,
                    "--no-write",
                    "--apply-proposals",
                ],
                capture_output=True, text=True,
            )
            assert result.returncode == 1
            assert "BLOCKED" in result.stderr

    def test_apply_with_approve_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_copy = Path(tmpdir) / "flaky_test.spec.ts"
            spec_copy.write_text(_FLAKY_SPEC.read_text(encoding="utf-8"), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable, str(_CLI),
                    "--project-id", "cli-apply-ok",
                    "--spec-files", str(spec_copy),
                    "--outputs-root", tmpdir,
                    "--no-write",
                    "--apply-proposals",
                    "--approve-code-modification",
                ],
                capture_output=True, text=True,
            )
            assert result.returncode == 0, result.stderr

    def test_run_no_write_produces_no_files(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = subprocess.run(
                [
                    sys.executable, str(_CLI),
                    "--project-id", "nw-cli",
                    "--spec-files", str(_FLAKY_SPEC),
                    "--outputs-root", tmpdir,
                    "--no-write",
                ],
                capture_output=True, text=True,
            )
            assert result.returncode == 0
            out = Path(tmpdir) / "nw-cli" / "32_flaky_test_analyzer"
            assert not out.exists()

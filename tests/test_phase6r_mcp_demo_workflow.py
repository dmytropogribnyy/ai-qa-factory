"""Phase 6-R tests — MCP demo workflow end-to-end validation."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

from tools.run_mcp_demo_workflow import run_demo

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "demo_quality_audit" / "playwright_specs"
_FLAKY_SPEC = str(_FIXTURES / "flaky_test.spec.ts")
_STABLE_SPEC = str(_FIXTURES / "stable_test.spec.ts")
_CLI = Path(__file__).parent.parent / "tools" / "run_mcp_demo_workflow.py"

_ALL_TOOLS = [
    "qa_factory_health",
    "analyze_project",
    "run_quality_audit",
    "run_flaky_test_analysis",
    "propose_self_healing_fixes",
    "generate_delivery_pack",
    "apply_self_healing_fixes",
]


def _run_workflow(tmpdir: str, write: bool = False) -> dict[str, dict]:
    return run_demo(
        project_id="test-6r",
        outputs_root=tmpdir,
        spec_files=[_FLAKY_SPEC, _STABLE_SPEC],
        write_files=write,
    )


# ===========================================================================
# Workflow — all 7 tools run
# ===========================================================================

class TestWorkflowCompleteness:
    def test_all_seven_tools_in_results(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            for tool in _ALL_TOOLS:
                assert tool in results, f"Missing tool: {tool}"

    def test_all_results_are_dicts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            for tool, result in results.items():
                assert isinstance(result, dict), f"{tool} did not return dict"

    def test_all_results_have_status_field(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            for tool, result in results.items():
                assert "status" in result, f"{tool} missing status"

    def test_all_results_have_human_review_required(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            for tool, result in results.items():
                assert result.get("human_review_required") is True, f"{tool} missing human_review_required=True"

    def test_no_credentials_in_any_response(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            full_json = json.dumps(results).lower()
            for word in ("password=", "api_key=", "bearer tok", "secret="):
                assert word not in full_json


# ===========================================================================
# Step 1: qa_factory_health
# ===========================================================================

class TestWorkflowHealth:
    def test_health_status_healthy(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["qa_factory_health"]["status"] == "healthy"

    def test_health_network_by_default_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["qa_factory_health"]["network_by_default"] is False

    def test_health_browser_by_default_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["qa_factory_health"]["browser_by_default"] is False


# ===========================================================================
# Step 3: run_quality_audit — safe default
# ===========================================================================

class TestWorkflowQualityAudit:
    def test_quality_audit_status_planning_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["run_quality_audit"]["status"] == "planning_only"

    def test_quality_audit_no_network(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["run_quality_audit"]["network_used"] is False

    def test_quality_audit_no_browser(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["run_quality_audit"]["browser_used"] is False

    def test_quality_audit_module_statuses_all_planning_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            statuses = results["run_quality_audit"]["module_statuses"]
            for mod, st in statuses.items():
                assert st in ("planning_only", "failed"), f"{mod} unexpected status: {st}"

    def test_quality_audit_has_artifact_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert len(results["run_quality_audit"]["artifact_paths"]) > 0

    def test_quality_audit_write_creates_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_workflow(tmpdir, write=True)
            proj = Path(tmpdir) / "test-6r"
            assert (proj / "29_accessibility").exists()
            assert (proj / "30_performance").exists()
            assert (proj / "31_passive_security").exists()


# ===========================================================================
# Step 4: run_flaky_test_analysis
# ===========================================================================

class TestWorkflowFlakyAnalysis:
    def test_flaky_status_analysis_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["run_flaky_test_analysis"]["status"] == "analysis_only"

    def test_flaky_detects_risks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["run_flaky_test_analysis"]["total_risks"] > 0

    def test_flaky_returns_stability_score(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            score = results["run_flaky_test_analysis"]["stability_score"]
            assert 0.0 <= score <= 100.0

    def test_flaky_applied_proposals_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["run_flaky_test_analysis"]["applied_proposals"] == 0

    def test_flaky_code_modification_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["run_flaky_test_analysis"]["code_modification_allowed"] is False

    def test_flaky_write_creates_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_workflow(tmpdir, write=True)
            out = Path(tmpdir) / "test-6r" / "32_flaky_test_analyzer"
            assert (out / "flaky_test_analysis.json").exists()
            assert (out / "Flaky_Test_Analysis_Report.md").exists()
            assert (out / "selector_stability.json").exists()
            assert (out / "self_healing_proposals.json").exists()


# ===========================================================================
# Step 5: propose_self_healing_fixes
# ===========================================================================

class TestWorkflowProposals:
    def test_proposals_not_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["propose_self_healing_fixes"]["applied_proposals"] == 0

    def test_proposals_code_modification_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["propose_self_healing_fixes"]["code_modification_allowed"] is False

    def test_proposals_status_not_patch_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            status = results["propose_self_healing_fixes"]["status"]
            assert status != "patch_applied", "Delivery pack must not claim patches applied"


# ===========================================================================
# Step 6: generate_delivery_pack
# ===========================================================================

class TestWorkflowDeliveryPack:
    def test_delivery_pack_status_draft(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir, write=True)
            assert results["generate_delivery_pack"]["status"] == "draft"

    def test_delivery_approved_always_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir, write=True)
            assert results["generate_delivery_pack"]["approved_for_client_delivery"] is False

    def test_auto_send_always_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir, write=True)
            assert results["generate_delivery_pack"]["auto_send_to_client"] is False

    def test_zip_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_workflow(tmpdir, write=True)
            zip_path = Path(tmpdir) / "test-6r" / "28_client_delivery" / "client_delivery.zip"
            assert zip_path.exists()

    def test_zip_excludes_storagestate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_workflow(tmpdir, write=True)
            zip_path = Path(tmpdir) / "test-6r" / "28_client_delivery" / "client_delivery.zip"
            if zip_path.exists():
                with zipfile.ZipFile(zip_path) as zf:
                    names = [n.lower() for n in zf.namelist()]
                    for blocked in ("storagestate", ".env", "credential", "token"):
                        assert not any(blocked in n for n in names), f"ZIP contains blocked file with '{blocked}'"

    def test_zip_excludes_itself(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_workflow(tmpdir, write=True)
            zip_path = Path(tmpdir) / "test-6r" / "28_client_delivery" / "client_delivery.zip"
            if zip_path.exists():
                with zipfile.ZipFile(zip_path) as zf:
                    assert "client_delivery.zip" not in zf.namelist()

    def test_zip_contains_qa_report(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_workflow(tmpdir, write=True)
            zip_path = Path(tmpdir) / "test-6r" / "28_client_delivery" / "client_delivery.zip"
            if zip_path.exists():
                with zipfile.ZipFile(zip_path) as zf:
                    assert "QA_Report.md" in zf.namelist()

    def test_zip_contains_evidence_index(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_workflow(tmpdir, write=True)
            zip_path = Path(tmpdir) / "test-6r" / "28_client_delivery" / "client_delivery.zip"
            if zip_path.exists():
                with zipfile.ZipFile(zip_path) as zf:
                    assert "Evidence_Index.md" in zf.namelist()

    def test_qa_report_has_no_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_workflow(tmpdir, write=True)
            report = Path(tmpdir) / "test-6r" / "28_client_delivery" / "QA_Report.md"
            if report.exists():
                content = report.read_text(encoding="utf-8").lower()
                for word in ("password", "api_key", "storagestate", "bearer"):
                    assert word not in content

    def test_qa_report_mentions_flaky_analysis(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_workflow(tmpdir, write=True)
            report = Path(tmpdir) / "test-6r" / "28_client_delivery" / "QA_Report.md"
            if report.exists():
                content = report.read_text(encoding="utf-8").lower()
                assert "flaky" in content or "selector" in content or "stability" in content


# ===========================================================================
# Step 7: apply_self_healing_fixes — blocked
# ===========================================================================

class TestWorkflowApplyBlocked:
    def test_apply_blocked_without_approval(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["apply_self_healing_fixes"]["status"] == "blocked"

    def test_apply_blocked_has_reason(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert "reason" in results["apply_self_healing_fixes"]

    def test_apply_blocked_code_modification_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            results = _run_workflow(tmpdir)
            assert results["apply_self_healing_fixes"]["code_modification_allowed"] is False

    def test_apply_blocked_spec_files_not_modified(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_workflow(tmpdir, write=True)
            # Confirm no HEAL- comments were inserted in the fixture specs
            flaky_content = Path(_FLAKY_SPEC).read_text(encoding="utf-8")
            assert "// HEAL-" not in flaky_content


# ===========================================================================
# Honest status representation
# ===========================================================================

class TestHonestStatusRepresentation:
    def test_planning_only_not_reported_as_executed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_workflow(tmpdir, write=True)
            qa_dir = Path(tmpdir) / "test-6r" / "28_client_delivery"
            report_path = qa_dir / "QA_Report.md"
            if report_path.exists():
                content = report_path.read_text(encoding="utf-8")
                # planning_only modules must show the correct label
                assert "Generated checks only" in content or "planning" in content.lower()

    def test_delivery_pack_does_not_claim_patches_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_workflow(tmpdir, write=True)
            qa_dir = Path(tmpdir) / "test-6r" / "28_client_delivery"
            report_path = qa_dir / "QA_Report.md"
            if report_path.exists():
                content = report_path.read_text(encoding="utf-8")
                assert "patch_applied" not in content

    def test_delivery_manifest_not_approved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _run_workflow(tmpdir, write=True)
            manifest = Path(tmpdir) / "test-6r" / "28_client_delivery" / "client_delivery_manifest.json"
            if manifest.exists():
                data = json.loads(manifest.read_text(encoding="utf-8"))
                assert data.get("approved_for_client_delivery") is False


# ===========================================================================
# CLI tool
# ===========================================================================

class TestCLIDemoWorkflow:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--project-id" in result.stdout

    def test_no_write_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "[OK]" in result.stdout

    def test_output_shows_all_steps(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write"],
            capture_output=True, text=True,
        )
        for i in range(1, 8):
            assert f"Step {i}" in result.stdout

    def test_summary_shown(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write"],
            capture_output=True, text=True,
        )
        assert "Summary" in result.stdout

    def test_apply_blocked_shown_in_output(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write"],
            capture_output=True, text=True,
        )
        assert "blocked" in result.stdout

    def test_blocked_approve_delivery_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--approve-delivery"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_blocked_skip_review_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--skip-review"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_blocked_force_apply_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--force-apply"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_json_output_flag(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write", "--json-output"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--- JSON Output ---" in result.stdout

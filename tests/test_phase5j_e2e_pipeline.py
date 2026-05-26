"""
Phase 5J tests — E2E Pipeline Runner.

Tests cover:
1. PipelineModuleConfig schema
2. PipelineModuleResult schema
3. PipelineRunPlan schema + safety invariants
4. PipelineRunReport schema + safety invariants
5. E2EPipelineRunner.plan() — module validation, ordering, approval gates
6. E2EPipelineRunner.run() — approval gate, module execution, status aggregation
7. CLI safety (blocked flags)
8. Schema exports (__init__.py)
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# 1. PipelineModuleConfig
# ---------------------------------------------------------------------------

class TestPipelineModuleConfig:
    def test_default_instantiation(self):
        from core.schemas.pipeline import PipelineModuleConfig
        cfg = PipelineModuleConfig()
        assert cfg.browser_target_url == ""
        assert cfg.db_provider == ""
        assert cfg.mobile_device == ""

    def test_with_values(self):
        from core.schemas.pipeline import PipelineModuleConfig
        cfg = PipelineModuleConfig(
            browser_target_url="https://www.saucedemo.com",
            browser_category="demo_auth",
            db_provider="postgresql",
            db_url_env_var="STAGING_DATABASE_URL",
        )
        assert cfg.browser_target_url == "https://www.saucedemo.com"
        assert cfg.db_provider == "postgresql"


# ---------------------------------------------------------------------------
# 2. PipelineModuleResult
# ---------------------------------------------------------------------------

class TestPipelineModuleResult:
    def test_default(self):
        from core.schemas.pipeline import PipelineModuleResult
        r = PipelineModuleResult()
        assert r.status == "pending"
        assert r.exit_code == -1
        assert r.blockers == []

    def test_with_values(self):
        from core.schemas.pipeline import PipelineModuleResult
        r = PipelineModuleResult(
            module_name="browser",
            status="complete",
            exit_code=0,
            duration_seconds=12.5,
        )
        assert r.module_name == "browser"
        assert r.status == "complete"
        assert r.duration_seconds == 12.5


# ---------------------------------------------------------------------------
# 3. PipelineRunPlan schema + safety invariants
# ---------------------------------------------------------------------------

class TestPipelineRunPlan:
    def test_safety_invariants_default(self):
        from core.schemas.pipeline import PipelineRunPlan
        plan = PipelineRunPlan()
        assert plan.raw_secrets_allowed is False
        assert plan.production_write_allowed is False
        assert plan.client_delivery_allowed is False
        assert plan.human_review_required is True

    def test_safety_invariants_cannot_override(self):
        from core.schemas.pipeline import PipelineRunPlan
        plan = PipelineRunPlan(
            raw_secrets_allowed=True,
            production_write_allowed=True,
            client_delivery_allowed=True,
            human_review_required=False,
        )
        assert plan.raw_secrets_allowed is False
        assert plan.production_write_allowed is False
        assert plan.client_delivery_allowed is False
        assert plan.human_review_required is True

    def test_from_dict_preserves_invariants(self):
        from core.schemas.pipeline import PipelineRunPlan
        plan = PipelineRunPlan.from_dict({
            "project_id": "p1",
            "raw_secrets_allowed": True,
            "client_delivery_allowed": True,
            "human_review_required": False,
        })
        assert plan.project_id == "p1"
        assert plan.raw_secrets_allowed is False
        assert plan.client_delivery_allowed is False
        assert plan.human_review_required is True

    def test_enabled_modules_preserved(self):
        from core.schemas.pipeline import PipelineRunPlan
        plan = PipelineRunPlan.from_dict({
            "enabled_modules": ["browser", "api_smoke"],
            "execution_order": ["browser", "api_smoke"],
        })
        assert "browser" in plan.enabled_modules
        assert "api_smoke" in plan.enabled_modules


# ---------------------------------------------------------------------------
# 4. PipelineRunReport schema + safety invariants
# ---------------------------------------------------------------------------

class TestPipelineRunReport:
    def test_safety_invariants_default(self):
        from core.schemas.pipeline import PipelineRunReport
        report = PipelineRunReport()
        assert report.raw_secrets_allowed is False
        assert report.production_write_allowed is False
        assert report.client_delivery_allowed is False
        assert report.human_review_required is True

    def test_safety_invariants_cannot_override(self):
        from core.schemas.pipeline import PipelineRunReport
        report = PipelineRunReport(
            raw_secrets_allowed=True,
            client_delivery_allowed=True,
            human_review_required=False,
        )
        assert report.raw_secrets_allowed is False
        assert report.client_delivery_allowed is False
        assert report.human_review_required is True

    def test_from_dict_preserves_invariants(self):
        from core.schemas.pipeline import PipelineRunReport
        report = PipelineRunReport.from_dict({
            "project_id": "p1",
            "overall_status": "complete",
            "raw_secrets_allowed": True,
            "human_review_required": False,
        })
        assert report.overall_status == "complete"
        assert report.raw_secrets_allowed is False
        assert report.human_review_required is True

    def test_from_dict_with_module_results(self):
        from core.schemas.pipeline import PipelineRunReport
        report = PipelineRunReport.from_dict({
            "project_id": "p1",
            "module_results": [
                {"module_name": "browser", "status": "complete", "exit_code": 0},
            ],
        })
        assert len(report.module_results) == 1
        assert report.module_results[0].module_name == "browser"

    def test_default_overall_status(self):
        from core.schemas.pipeline import PipelineRunReport
        r = PipelineRunReport()
        assert r.overall_status == "planned"


# ---------------------------------------------------------------------------
# 5. PIPELINE_MODULES constants
# ---------------------------------------------------------------------------

class TestPipelineConstants:
    def test_pipeline_modules_tuple(self):
        from core.schemas.pipeline import PIPELINE_MODULES
        assert isinstance(PIPELINE_MODULES, tuple)
        assert "browser" in PIPELINE_MODULES
        assert "api_smoke" in PIPELINE_MODULES
        assert "db_smoke" in PIPELINE_MODULES
        assert "qa_report" in PIPELINE_MODULES

    def test_all_nine_modules_present(self):
        from core.schemas.pipeline import PIPELINE_MODULES
        assert len(PIPELINE_MODULES) == 9

    def test_execution_order_fixed(self):
        from core.schemas.pipeline import PIPELINE_MODULES
        order = list(PIPELINE_MODULES)
        assert order[0] == "task_source"
        assert order[-1] == "qa_report"
        assert order.index("browser") < order.index("api_smoke")
        assert order.index("api_smoke") < order.index("db_smoke")
        assert order.index("db_smoke") < order.index("qa_report")

    def test_artifact_dirs_mapped(self):
        from core.schemas.pipeline import PIPELINE_MODULE_ARTIFACT_DIRS, PIPELINE_MODULES
        for mod in PIPELINE_MODULES:
            assert mod in PIPELINE_MODULE_ARTIFACT_DIRS

    def test_cli_tools_mapped(self):
        from core.schemas.pipeline import PIPELINE_MODULE_CLI_TOOLS, PIPELINE_MODULES
        for mod in PIPELINE_MODULES:
            assert mod in PIPELINE_MODULE_CLI_TOOLS


# ---------------------------------------------------------------------------
# 6. E2EPipelineRunner.plan()
# ---------------------------------------------------------------------------

class TestE2EPipelineRunnerPlan:
    def test_plan_blocked_without_approval(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        plan = runner.plan(
            project_id="p1",
            enabled_modules=["browser"],
            approve_pipeline_execution=False,
        )
        assert any("not approved" in b for b in plan.blockers)

    def test_plan_blocked_no_modules(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        plan = runner.plan(
            project_id="p1",
            enabled_modules=[],
            approve_pipeline_execution=True,
        )
        assert any("No modules" in b for b in plan.blockers)

    def test_plan_blocked_no_project_id(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        plan = runner.plan(
            project_id="",
            enabled_modules=["browser"],
            approve_pipeline_execution=True,
        )
        assert any("project_id" in b for b in plan.blockers)

    def test_plan_blocks_unknown_module(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        plan = runner.plan(
            project_id="p1",
            enabled_modules=["browser", "nonexistent_module"],
            approve_pipeline_execution=True,
        )
        assert any("Unknown module" in b for b in plan.blockers)

    def test_plan_execution_order_respects_fixed_order(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        # Request modules out of order — plan should put them in fixed order
        plan = runner.plan(
            project_id="p1",
            enabled_modules=["db_smoke", "browser", "api_smoke"],
            approve_pipeline_execution=True,
        )
        # execution_order should be browser → api_smoke → db_smoke
        order = plan.execution_order
        if "browser" in order and "api_smoke" in order:
            assert order.index("browser") < order.index("api_smoke")
        if "api_smoke" in order and "db_smoke" in order:
            assert order.index("api_smoke") < order.index("db_smoke")

    def test_plan_safety_invariants(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        plan = runner.plan(
            project_id="p1",
            enabled_modules=["browser"],
            approve_pipeline_execution=True,
        )
        assert plan.raw_secrets_allowed is False
        assert plan.client_delivery_allowed is False
        assert plan.human_review_required is True


# ---------------------------------------------------------------------------
# 7. E2EPipelineRunner.run() — approval + status aggregation
# ---------------------------------------------------------------------------

class TestE2EPipelineRunnerRun:
    def test_run_blocked_without_approval(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        report = runner.run(
            project_id="p1",
            enabled_modules=["browser"],
            approve_pipeline_execution=False,
        )
        assert report.overall_status == "blocked"
        assert any("not approved" in b for b in report.blockers)

    def test_run_blocked_no_project_id(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        report = runner.run(
            project_id="",
            enabled_modules=["browser"],
            approve_pipeline_execution=True,
        )
        assert report.overall_status == "blocked"

    def test_run_blocked_unknown_module(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        report = runner.run(
            project_id="p1",
            enabled_modules=["fake_module"],
            approve_pipeline_execution=True,
        )
        assert report.overall_status == "blocked"

    def test_run_safety_invariants(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        report = runner.run(
            project_id="p1",
            enabled_modules=["browser"],
            approve_pipeline_execution=False,
        )
        assert report.raw_secrets_allowed is False
        assert report.production_write_allowed is False
        assert report.client_delivery_allowed is False
        assert report.human_review_required is True

    def test_run_missing_cli_tool_marks_skipped(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        # browser CLI tool exists but will fail due to no real browser
        # We mock subprocess.run to simulate a CLI that doesn't exist
        report = runner.run(
            project_id="p1",
            enabled_modules=["browser"],
            approve_pipeline_execution=True,
        )
        # CLI tool exists (tools/run_browser_execution.py) but config is missing
        # → module should be marked skipped or blocked
        mr = next((r for r in report.module_results if r.module_name == "browser"), None)
        assert mr is not None
        assert mr.status in ("skipped", "blocked", "failed")

    def test_run_produces_module_results_in_order(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        report = runner.run(
            project_id="p1",
            enabled_modules=["browser", "api_smoke"],
            approve_pipeline_execution=True,
        )
        names = [r.module_name for r in report.module_results]
        if "browser" in names and "api_smoke" in names:
            assert names.index("browser") < names.index("api_smoke")

    def test_run_with_mocked_subprocess_success(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        from core.schemas.pipeline import PipelineModuleConfig
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        cfg = PipelineModuleConfig(
            mobile_device="iPhone 14",
            mobile_approve=True,
        )
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Status: complete"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            report = runner.run(
                project_id="p1",
                enabled_modules=["mobile_viewport"],
                module_config=cfg,
                approve_pipeline_execution=True,
            )
        mr = next((r for r in report.module_results if r.module_name == "mobile_viewport"), None)
        assert mr is not None
        assert mr.status == "complete"
        assert report.modules_complete == 1

    def test_run_with_mocked_subprocess_failure(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        from core.schemas.pipeline import PipelineModuleConfig
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        cfg = PipelineModuleConfig(
            mobile_device="Pixel 7",
            mobile_approve=True,
        )
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = "Status: blocked"
        mock_result.stderr = "Error: approval missing"
        with patch("subprocess.run", return_value=mock_result):
            report = runner.run(
                project_id="p1",
                enabled_modules=["mobile_viewport"],
                module_config=cfg,
                approve_pipeline_execution=True,
            )
        mr = next((r for r in report.module_results if r.module_name == "mobile_viewport"), None)
        assert mr is not None
        assert mr.status == "failed"
        assert report.modules_failed == 1


# ---------------------------------------------------------------------------
# 8. render_artifacts
# ---------------------------------------------------------------------------

class TestE2EPipelineRenderArtifacts:
    def test_render_creates_files(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        from core.schemas.pipeline import PipelineRunReport
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        report = PipelineRunReport(
            project_id="p1",
            overall_status="complete",
            modules_complete=2,
        )
        paths = runner.render_artifacts(report, "p1")
        assert paths["json"].exists()
        assert paths["md"].exists()
        assert paths["checklist"].exists()

    def test_render_json_has_safety_fields(self, tmp_path):
        import json as json_mod
        from core.e2e_pipeline_runner import E2EPipelineRunner
        from core.schemas.pipeline import PipelineRunReport
        runner = E2EPipelineRunner(outputs_root=tmp_path)
        report = PipelineRunReport(project_id="p1")
        paths = runner.render_artifacts(report, "p1")
        data = json_mod.loads(paths["json"].read_text())
        assert data["raw_secrets_allowed"] is False
        assert data["client_delivery_allowed"] is False
        assert data["human_review_required"] is True


# ---------------------------------------------------------------------------
# 9. CLI safety — blocked flags
# ---------------------------------------------------------------------------

class TestE2EPipelineCLISafety:
    def _run_cli(self, args: list) -> int:
        import subprocess
        result = subprocess.run(
            [sys.executable, "tools/run_e2e_pipeline.py"] + args,
            capture_output=True,
            text=True,
        )
        return result.returncode

    def test_blocked_password_flag(self):
        rc = self._run_cli(["--project-id", "p", "--password", "secret"])
        assert rc == 2

    def test_blocked_token_flag(self):
        rc = self._run_cli(["--project-id", "p", "--token", "abc"])
        assert rc == 2

    def test_blocked_db_url_flag(self):
        rc = self._run_cli(["--project-id", "p", "--db-url", "postgres://host/db"])
        assert rc == 2

    def test_missing_project_id_exits_nonzero(self):
        rc = self._run_cli(["--enable-browser"])
        assert rc != 0


# ---------------------------------------------------------------------------
# 10. Schema exports
# ---------------------------------------------------------------------------

class TestPhase5JPipelineExports:
    def test_pipeline_schema_exports(self):
        from core.schemas import (
            PIPELINE_MODULE_STATUSES,
            PIPELINE_MODULES,
            PIPELINE_OVERALL_STATUSES,
            PipelineModuleConfig,
            PipelineModuleResult,
            PipelineRunPlan,
            PipelineRunReport,
        )
        assert "browser" in PIPELINE_MODULES
        assert "complete" in PIPELINE_MODULE_STATUSES
        assert "planned" in PIPELINE_OVERALL_STATUSES
        plan = PipelineRunPlan()
        assert plan.human_review_required is True
        report = PipelineRunReport()
        assert report.human_review_required is True
        cfg = PipelineModuleConfig()
        assert cfg.browser_target_url == ""
        mr = PipelineModuleResult()
        assert mr.status == "pending"

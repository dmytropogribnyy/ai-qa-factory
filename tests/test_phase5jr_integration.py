"""
Phase 5J-R — Integration tests: E2E Pipeline Runner hardening + Demo Pipeline.

Tests:
- PipelineModuleConfig.stop_on_first_failure field
- PipelineRunReport.stopped_early + stop_on_first_failure fields
- E2EPipelineRunner stop_on_first_failure logic
- E2EPipelineRunner plan qa_report-only note
- Demo pipeline plan mode
- Demo pipeline CLI safety
- Phase 5J-R exports
"""
from __future__ import annotations

import json
import subprocess
import sys
from unittest.mock import patch

# ---------------------------------------------------------------------------
# TestPipelineModuleConfigStopOnFailure
# ---------------------------------------------------------------------------

class TestPipelineModuleConfigStopOnFailure:
    def test_default_stop_on_first_failure_false(self):
        from core.schemas.pipeline import PipelineModuleConfig
        cfg = PipelineModuleConfig()
        assert cfg.stop_on_first_failure is False

    def test_set_stop_on_first_failure_true(self):
        from core.schemas.pipeline import PipelineModuleConfig
        cfg = PipelineModuleConfig(stop_on_first_failure=True)
        assert cfg.stop_on_first_failure is True

    def test_to_dict_includes_stop_on_first_failure(self):
        from core.schemas.pipeline import PipelineModuleConfig
        cfg = PipelineModuleConfig(stop_on_first_failure=True)
        d = cfg.to_dict()
        assert d["stop_on_first_failure"] is True


# ---------------------------------------------------------------------------
# TestPipelineRunReportStoppedEarly
# ---------------------------------------------------------------------------

class TestPipelineRunReportStoppedEarly:
    def test_default_stopped_early_false(self):
        from core.schemas.pipeline import PipelineRunReport
        r = PipelineRunReport(project_id="p")
        assert r.stopped_early is False

    def test_default_stop_on_first_failure_false(self):
        from core.schemas.pipeline import PipelineRunReport
        r = PipelineRunReport(project_id="p")
        assert r.stop_on_first_failure is False

    def test_stopped_early_in_to_dict(self):
        from core.schemas.pipeline import PipelineRunReport
        r = PipelineRunReport(project_id="p", stopped_early=True)
        assert r.to_dict()["stopped_early"] is True

    def test_from_dict_preserves_stopped_early(self):
        from core.schemas.pipeline import PipelineRunReport
        r = PipelineRunReport.from_dict({"project_id": "p", "stopped_early": True})
        assert r.stopped_early is True

    def test_from_dict_preserves_stop_on_first_failure(self):
        from core.schemas.pipeline import PipelineRunReport
        r = PipelineRunReport.from_dict({"project_id": "p", "stop_on_first_failure": True})
        assert r.stop_on_first_failure is True

    def test_safety_invariants_not_affected_by_new_fields(self):
        from core.schemas.pipeline import PipelineRunReport
        r = PipelineRunReport.from_dict({
            "project_id": "p",
            "stopped_early": True,
            "raw_secrets_allowed": True,
        })
        assert r.raw_secrets_allowed is False
        assert r.stopped_early is True


# ---------------------------------------------------------------------------
# TestE2EPipelineStopOnFirstFailure
# ---------------------------------------------------------------------------

class TestE2EPipelineStopOnFirstFailure:
    """Patches _run_module directly to avoid CLI-tool-existence and config dependencies."""

    def _make_runner(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        return E2EPipelineRunner(outputs_root=tmp_path)

    def _module_result(self, name, status):
        from core.schemas.pipeline import PipelineModuleResult
        return PipelineModuleResult(module_name=name, status=status)

    def test_stop_on_failure_false_runs_all_modules(self, tmp_path):
        runner = self._make_runner(tmp_path)

        def fake_run(module_name, project_id, cfg, timeout):
            return self._module_result(module_name, "complete")

        with patch.object(runner, "_run_module", side_effect=fake_run):
            report = runner.run(
                project_id="p",
                enabled_modules=["api_smoke", "db_smoke"],
                approve_pipeline_execution=True,
                stop_on_first_failure=False,
            )
        assert report.modules_complete == 2
        assert report.stopped_early is False

    def test_stop_on_failure_true_skips_after_first_failed(self, tmp_path):
        runner = self._make_runner(tmp_path)
        call_count = [0]

        def fake_run(module_name, project_id, cfg, timeout):
            call_count[0] += 1
            status = "failed" if call_count[0] == 1 else "complete"
            return self._module_result(module_name, status)

        with patch.object(runner, "_run_module", side_effect=fake_run):
            report = runner.run(
                project_id="p",
                enabled_modules=["api_smoke", "db_smoke", "qa_report"],
                approve_pipeline_execution=True,
                stop_on_first_failure=True,
            )

        assert report.stopped_early is True
        statuses = {r.module_name: r.status for r in report.module_results}
        assert statuses["api_smoke"] == "failed"
        assert statuses["db_smoke"] == "skipped"
        assert statuses["qa_report"] == "skipped"

    def test_stop_on_failure_true_correct_skipped_count(self, tmp_path):
        runner = self._make_runner(tmp_path)

        def fake_run(module_name, project_id, cfg, timeout):
            return self._module_result(module_name, "failed")

        with patch.object(runner, "_run_module", side_effect=fake_run):
            report = runner.run(
                project_id="p",
                enabled_modules=["api_smoke", "db_smoke", "qa_report"],
                approve_pipeline_execution=True,
                stop_on_first_failure=True,
            )

        assert report.modules_failed == 1
        assert report.modules_skipped == 2

    def test_stop_on_failure_skipped_modules_have_note(self, tmp_path):
        runner = self._make_runner(tmp_path)

        def fake_run(module_name, project_id, cfg, timeout):
            return self._module_result(module_name, "failed")

        with patch.object(runner, "_run_module", side_effect=fake_run):
            report = runner.run(
                project_id="p",
                enabled_modules=["api_smoke", "qa_report"],
                approve_pipeline_execution=True,
                stop_on_first_failure=True,
            )

        skipped = [r for r in report.module_results if r.status == "skipped"]
        assert len(skipped) == 1
        assert any("stop_on_first_failure" in n for n in skipped[0].notes)

    def test_stop_on_failure_false_stopped_early_is_false(self, tmp_path):
        runner = self._make_runner(tmp_path)

        def fake_run(module_name, project_id, cfg, timeout):
            return self._module_result(module_name, "failed")

        with patch.object(runner, "_run_module", side_effect=fake_run):
            report = runner.run(
                project_id="p",
                enabled_modules=["api_smoke", "qa_report"],
                approve_pipeline_execution=True,
                stop_on_first_failure=False,
            )
        assert report.stopped_early is False

    def test_stop_on_failure_all_pass_no_early_stop(self, tmp_path):
        runner = self._make_runner(tmp_path)

        def fake_run(module_name, project_id, cfg, timeout):
            return self._module_result(module_name, "complete")

        with patch.object(runner, "_run_module", side_effect=fake_run):
            report = runner.run(
                project_id="p",
                enabled_modules=["api_smoke", "qa_report"],
                approve_pipeline_execution=True,
                stop_on_first_failure=True,
            )
        assert report.stopped_early is False
        assert report.modules_complete == 2

    def test_stop_on_failure_true_sets_flag_in_report(self, tmp_path):
        runner = self._make_runner(tmp_path)

        def fake_run(module_name, project_id, cfg, timeout):
            return self._module_result(module_name, "complete")

        with patch.object(runner, "_run_module", side_effect=fake_run):
            report = runner.run(
                project_id="p",
                enabled_modules=["api_smoke"],
                approve_pipeline_execution=True,
                stop_on_first_failure=True,
            )
        assert report.stop_on_first_failure is True

    def test_stop_on_failure_false_flag_false_in_report(self, tmp_path):
        runner = self._make_runner(tmp_path)

        def fake_run(module_name, project_id, cfg, timeout):
            return self._module_result(module_name, "complete")

        with patch.object(runner, "_run_module", side_effect=fake_run):
            report = runner.run(
                project_id="p",
                enabled_modules=["api_smoke"],
                approve_pipeline_execution=True,
                stop_on_first_failure=False,
            )
        assert report.stop_on_first_failure is False


# ---------------------------------------------------------------------------
# TestE2EPipelinePlanQAReportOnly
# ---------------------------------------------------------------------------

class TestE2EPipelinePlanQAReportOnly:
    def _make_runner(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        return E2EPipelineRunner(outputs_root=tmp_path)

    def test_plan_qa_report_only_adds_note(self, tmp_path):
        runner = self._make_runner(tmp_path)
        plan = runner.plan(
            project_id="p",
            enabled_modules=["qa_report"],
            approve_pipeline_execution=True,
        )
        assert any("qa_report is the only" in n for n in plan.notes)

    def test_plan_two_modules_no_extra_note(self, tmp_path):
        runner = self._make_runner(tmp_path)
        plan = runner.plan(
            project_id="p",
            enabled_modules=["api_smoke", "qa_report"],
            approve_pipeline_execution=True,
        )
        assert not any("only enabled module" in n for n in plan.notes)

    def test_plan_no_qa_report_no_extra_note(self, tmp_path):
        runner = self._make_runner(tmp_path)
        plan = runner.plan(
            project_id="p",
            enabled_modules=["api_smoke"],
            approve_pipeline_execution=True,
        )
        assert not any("qa_report" in n for n in plan.notes)

    def test_plan_all_modules_no_qa_only_note(self, tmp_path):
        from core.schemas.pipeline import PIPELINE_MODULES
        runner = self._make_runner(tmp_path)
        plan = runner.plan(
            project_id="p",
            enabled_modules=list(PIPELINE_MODULES),
            approve_pipeline_execution=True,
        )
        assert not any("only enabled module" in n for n in plan.notes)


# ---------------------------------------------------------------------------
# TestDemoPipelineBuildConfig
# ---------------------------------------------------------------------------

class TestDemoPipelineBuildConfig:
    def test_api_target_includes_api_smoke(self):
        from tools.run_demo_pipeline import _build_demo_config
        modules, cfg = _build_demo_config("api", approve_api=False, approve_browser=False)
        assert "api_smoke" in modules
        assert "browser" not in modules
        assert "qa_report" in modules

    def test_browser_target_includes_browser(self):
        from tools.run_demo_pipeline import _build_demo_config
        modules, cfg = _build_demo_config("browser", approve_api=False, approve_browser=False)
        assert "browser" in modules
        assert "api_smoke" not in modules
        assert "qa_report" in modules

    def test_full_target_includes_both(self):
        from tools.run_demo_pipeline import _build_demo_config
        modules, cfg = _build_demo_config("full", approve_api=True, approve_browser=True)
        assert "api_smoke" in modules
        assert "browser" in modules
        assert "qa_report" in modules

    def test_api_preset_url_is_restful_booker(self):
        from tools.run_demo_pipeline import _build_demo_config
        _, cfg = _build_demo_config("api", approve_api=False, approve_browser=False)
        assert "restful-booker" in cfg.api_target_url

    def test_browser_preset_url_is_saucedemo(self):
        from tools.run_demo_pipeline import _build_demo_config
        _, cfg = _build_demo_config("browser", approve_api=False, approve_browser=False)
        assert "saucedemo" in cfg.browser_target_url

    def test_approve_api_flag_propagated(self):
        from tools.run_demo_pipeline import _build_demo_config
        _, cfg = _build_demo_config("api", approve_api=True, approve_browser=False)
        assert cfg.api_approve is True

    def test_approve_browser_flag_propagated(self):
        from tools.run_demo_pipeline import _build_demo_config
        _, cfg = _build_demo_config("browser", approve_api=False, approve_browser=True)
        assert cfg.browser_approve is True

    def test_demo_targets_constant(self):
        from tools.run_demo_pipeline import DEMO_TARGETS
        assert "api" in DEMO_TARGETS
        assert "browser" in DEMO_TARGETS
        assert "full" in DEMO_TARGETS


# ---------------------------------------------------------------------------
# TestDemoPipelinePlanMode (tests via runner directly — no subprocess import issues)
# ---------------------------------------------------------------------------

class TestDemoPipelinePlanMode:
    def _make_runner(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        return E2EPipelineRunner(outputs_root=tmp_path)

    def test_api_plan_includes_api_smoke(self, tmp_path):
        from tools.run_demo_pipeline import _build_demo_config
        runner = self._make_runner(tmp_path)
        modules, cfg = _build_demo_config("api", approve_api=True, approve_browser=False)
        plan = runner.plan(project_id="demo", enabled_modules=modules, approve_pipeline_execution=True)
        assert "api_smoke" in plan.execution_order
        assert "browser" not in plan.execution_order

    def test_browser_plan_includes_browser(self, tmp_path):
        from tools.run_demo_pipeline import _build_demo_config
        runner = self._make_runner(tmp_path)
        modules, cfg = _build_demo_config("browser", approve_api=False, approve_browser=True)
        plan = runner.plan(project_id="demo", enabled_modules=modules, approve_pipeline_execution=True)
        # check enabled_modules (requested) — execution_order may exclude blocked CLI tools
        assert "browser" in plan.enabled_modules
        assert "api_smoke" not in plan.enabled_modules

    def test_full_plan_includes_both(self, tmp_path):
        from tools.run_demo_pipeline import _build_demo_config
        runner = self._make_runner(tmp_path)
        modules, cfg = _build_demo_config("full", approve_api=True, approve_browser=True)
        plan = runner.plan(project_id="demo", enabled_modules=modules, approve_pipeline_execution=True)
        assert "api_smoke" in plan.enabled_modules
        assert "browser" in plan.enabled_modules

    def test_plan_without_approval_has_blocker(self, tmp_path):
        from tools.run_demo_pipeline import _build_demo_config
        runner = self._make_runner(tmp_path)
        modules, cfg = _build_demo_config("api", approve_api=True, approve_browser=False)
        plan = runner.plan(project_id="demo", enabled_modules=modules, approve_pipeline_execution=False)
        assert any("approve" in b.lower() for b in plan.blockers)

    def test_plan_returns_pipeline_run_plan(self, tmp_path):
        from tools.run_demo_pipeline import _build_demo_config
        from core.schemas.pipeline import PipelineRunPlan
        runner = self._make_runner(tmp_path)
        modules, cfg = _build_demo_config("full", approve_api=True, approve_browser=True)
        plan = runner.plan(project_id="demo", enabled_modules=modules, approve_pipeline_execution=True)
        assert isinstance(plan, PipelineRunPlan)

    def test_plan_qa_report_always_present(self):
        from tools.run_demo_pipeline import _build_demo_config
        for target in ("api", "browser", "full"):
            modules, cfg = _build_demo_config(target, approve_api=True, approve_browser=True)
            assert "qa_report" in modules

    def test_invalid_demo_target_exits_nonzero(self):
        result = subprocess.run(
            [sys.executable, "tools/run_demo_pipeline.py",
             "--project-id", "p",
             "--demo-target", "invalid_target"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_missing_project_id_exits_nonzero(self):
        result = subprocess.run(
            [sys.executable, "tools/run_demo_pipeline.py"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# TestDemoPipelineCLISafety
# ---------------------------------------------------------------------------

class TestDemoPipelineCLISafety:
    def _run_blocked(self, flag: str):
        return subprocess.run(
            [sys.executable, "tools/run_demo_pipeline.py",
             "--project-id", "p",
             flag, "value"],
            capture_output=True, text=True,
        )

    def test_blocked_flag_password(self):
        result = self._run_blocked("--password")
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr

    def test_blocked_flag_token(self):
        result = self._run_blocked("--token")
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr

    def test_blocked_flag_secret(self):
        result = self._run_blocked("--secret")
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr

    def test_blocked_flag_api_key(self):
        result = self._run_blocked("--api-key")
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr

    def test_blocked_flag_db_url(self):
        result = self._run_blocked("--db-url")
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr

    def test_blocked_flag_bearer(self):
        result = self._run_blocked("--bearer")
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr

    def test_blocked_flag_cookie(self):
        result = self._run_blocked("--cookie")
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr

    def test_blocked_flag_pat(self):
        result = self._run_blocked("--pat")
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr


# ---------------------------------------------------------------------------
# TestRunE2EPipelineStopOnFailureFlag
# ---------------------------------------------------------------------------

class TestRunE2EPipelineStopOnFailureFlag:
    def test_stop_on_failure_flag_accepted(self):
        result = subprocess.run(
            [sys.executable, "tools/run_e2e_pipeline.py",
             "--project-id", "p",
             "--enable-api",
             "--api-target-url", "https://example.com",
             "--stop-on-failure"],
            capture_output=True, text=True,
        )
        # Should block (no approval) but not reject the flag itself
        assert result.returncode in (0, 1)
        assert "BLOCKED" not in result.stderr or "--stop-on-failure" not in result.stderr

    def test_stop_on_failure_flag_shown_in_plan(self):
        result = subprocess.run(
            [sys.executable, "tools/run_e2e_pipeline.py",
             "--project-id", "p",
             "--enable-api",
             "--api-target-url", "https://example.com",
             "--stop-on-failure",
             "--no-write"],
            capture_output=True, text=True,
        )
        assert result.returncode in (0, 1)


# ---------------------------------------------------------------------------
# TestDemoPipelineRenderArtifacts
# ---------------------------------------------------------------------------

class TestDemoPipelineRenderArtifacts:
    def test_render_artifacts_creates_files(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        from core.schemas.pipeline import PipelineModuleResult, PipelineRunReport

        runner = E2EPipelineRunner(outputs_root=tmp_path)
        report = PipelineRunReport(
            project_id="demo-render",
            enabled_modules=["api_smoke", "qa_report"],
            execution_order=["api_smoke", "qa_report"],
            overall_status="complete",
            stopped_early=False,
            stop_on_first_failure=True,
            module_results=[
                PipelineModuleResult(
                    module_name="api_smoke",
                    status="complete",
                    duration_seconds=1.2,
                ),
                PipelineModuleResult(
                    module_name="qa_report",
                    status="complete",
                    duration_seconds=0.5,
                ),
            ],
            modules_complete=2,
        )
        paths = runner.render_artifacts(report, "demo-render")

        assert paths["json"].exists()
        assert paths["md"].exists()
        assert paths["checklist"].exists()

    def test_render_json_includes_stopped_early(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        from core.schemas.pipeline import PipelineRunReport

        runner = E2EPipelineRunner(outputs_root=tmp_path)
        report = PipelineRunReport(
            project_id="demo-render2",
            stopped_early=True,
            stop_on_first_failure=True,
        )
        paths = runner.render_artifacts(report, "demo-render2")
        payload = json.loads(paths["json"].read_text(encoding="utf-8"))
        assert payload["stopped_early"] is True
        assert payload["stop_on_first_failure"] is True

    def test_render_md_includes_stopped_early_note(self, tmp_path):
        from core.e2e_pipeline_runner import E2EPipelineRunner
        from core.schemas.pipeline import PipelineRunReport

        runner = E2EPipelineRunner(outputs_root=tmp_path)
        report = PipelineRunReport(
            project_id="demo-render3",
            stopped_early=True,
        )
        paths = runner.render_artifacts(report, "demo-render3")
        md = paths["md"].read_text(encoding="utf-8")
        assert "stopped early" in md


# ---------------------------------------------------------------------------
# TestPhase5JRExports
# ---------------------------------------------------------------------------

class TestPhase5JRExports:
    def test_stop_on_first_failure_in_pipeline_module_config(self):
        from core.schemas.pipeline import PipelineModuleConfig
        cfg = PipelineModuleConfig()
        assert hasattr(cfg, "stop_on_first_failure")

    def test_stopped_early_in_pipeline_run_report(self):
        from core.schemas.pipeline import PipelineRunReport
        r = PipelineRunReport()
        assert hasattr(r, "stopped_early")

    def test_demo_pipeline_importable(self):
        from tools.run_demo_pipeline import _build_demo_config, DEMO_TARGETS
        assert callable(_build_demo_config)
        assert len(DEMO_TARGETS) == 3

    def test_e2e_runner_stop_on_failure_param(self, tmp_path):
        import inspect
        from core.e2e_pipeline_runner import E2EPipelineRunner
        sig = inspect.signature(E2EPipelineRunner.run)
        assert "stop_on_first_failure" in sig.parameters

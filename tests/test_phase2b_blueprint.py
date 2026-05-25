"""tests/test_phase2b_blueprint.py — Phase 2B: ProjectBlueprintBuilder tests.

Covers:
- Project type inference for each known type
- Environment inference (staging, production, local, none, unknown)
- task_source vs target_application separation
- Assumptions generation
- Missing information generation
- Blocked actions and required approvals
- Safe next steps
- Secret redaction safety
- WorkbenchController blueprint methods
- CLI --with-blueprint flag
"""
from __future__ import annotations

import json
from pathlib import Path

from core.project_blueprint_builder import (
    ProjectBlueprintBuilder,
    _infer_environment,
    _infer_project_type,
    _infer_target_application,
    _infer_task_source,
    _build_assumptions,
    _build_missing_info,
    _build_blocked_actions,
    _build_safe_next_steps,
    _build_required_approvals,
    _build_recommended_strategy,
    _build_tactical_focus,
    _infer_confidence,
)
from core.schemas.input_map import InputMap, InputSource
from core.schemas.project_blueprint import ProjectBlueprint
from core.schemas.task_classification import TaskClassification
from core.schemas.work_request import WorkRequest
from core.workbench_controller import WorkbenchController
from tools.classify_inputs import main as cli_main


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_input_map(project_id: str = "test-bp", sources: list | None = None) -> InputMap:
    return InputMap(
        project_id=project_id,
        sources=sources or [
            InputSource(
                input_type="pasted_brief",
                raw_value="brief text",
                label="[pasted_brief] brief text",
            )
        ],
    )


def _make_work_request(
    project_id: str = "test-bp",
    title: str = "Test",
    summary: str = "",
    raw_brief: str = "",
    platform: str = "unknown",
) -> WorkRequest:
    return WorkRequest(
        project_id=project_id,
        request_title=title,
        request_summary=summary,
        raw_brief=raw_brief,
        source_platform=platform,
    )


def _make_classification(
    project_id: str = "test-bp",
    task_type: str = "qa_automation",
    project_type: str = "unknown",
) -> TaskClassification:
    return TaskClassification(
        project_id=project_id,
        task_type=task_type,
        project_type=project_type,
        source_platform="unknown",
        confidence=0.5,
        signals=[],
        notes="",
        classified_at="2026-01-01T00:00:00+00:00",
    )


def _build(brief: str, task_type: str = "qa_automation", project_type: str = "unknown") -> ProjectBlueprint:
    pid = "test-bp"
    im = _make_input_map(pid)
    wr = _make_work_request(pid, "Test", brief, brief)
    tc = _make_classification(pid, task_type, project_type)
    return ProjectBlueprintBuilder().build(im, wr, tc)


# ---------------------------------------------------------------------------
# Project type inference
# ---------------------------------------------------------------------------

class TestProjectTypeInference:
    def test_web_saas_from_saas_signal(self):
        bp = _build("Need QA for a SaaS dashboard with user accounts and subscriptions")
        assert bp.project_type == "web_saas"

    def test_ecommerce_from_checkout_signal(self):
        bp = _build("Test the checkout flow cart and payment on our ecommerce shop")
        assert bp.project_type == "ecommerce"

    def test_api_backend_from_endpoint_signal(self):
        bp = _build("Write API endpoint tests for our REST backend with OpenAPI swagger spec")
        assert bp.project_type == "api_backend"

    def test_ai_generated_app_from_lovable_signal(self):
        bp = _build("Our app was built with Lovable — test the AI generated flows")
        assert bp.project_type == "ai_generated_app"

    def test_admin_panel_from_admin_signal(self):
        bp = _build("Test the admin panel CRUD operations with role permissions and backoffice")
        assert bp.project_type == "admin_panel"

    def test_auth_heavy_from_auth_signal(self):
        bp = _build("Test login logout 2FA password reset and OAuth2 SSO sign in sign up flows")
        assert bp.project_type == "auth_heavy"

    def test_mixed_ui_api_when_both_present(self):
        bp = _build("Test the SaaS dashboard and also the REST API endpoints backend service")
        assert bp.project_type == "mixed_ui_api"

    def test_unknown_for_generic_brief(self):
        result = _infer_project_type("help me with something", "unknown")
        assert result == "unknown"

    def test_infer_project_type_uses_preset_if_inferred_unknown(self):
        result = _infer_project_type("some vague text", "qa_automation", preset="ecommerce")
        assert result == "ecommerce"

    def test_infer_project_type_ignores_preset_if_inferred_known(self):
        result = _infer_project_type(
            "SaaS dashboard with user accounts and subscriptions", "qa_automation", preset="ecommerce"
        )
        assert result == "web_saas"


# ---------------------------------------------------------------------------
# Environment inference
# ---------------------------------------------------------------------------

class TestEnvironmentInference:
    def test_staging_environment(self):
        sources = []
        assert _infer_environment("test on staging environment", sources) == "staging"

    def test_production_environment(self):
        sources = []
        assert _infer_environment("production site with real users", sources) == "production"

    def test_local_environment(self):
        sources = []
        assert _infer_environment("running locally on localhost", sources) == "local"

    def test_none_environment_for_proposal(self):
        sources = []
        assert _infer_environment("write a proposal cover letter bid", sources) == "none"

    def test_unknown_environment_no_signals(self):
        sources = []
        assert _infer_environment("I need some QA help", sources) == "unknown"

    def test_unknown_environment_with_target_url(self):
        sources = [InputSource(input_type="target_url", raw_value="https://example.com", label="[target_url] ...")]
        assert _infer_environment("Test the app", sources) == "unknown"

    def test_production_keyword_in_blueprint(self):
        bp = _build("Need tests on production with real payment and real users")
        assert bp.environment == "production"

    def test_sandbox_is_staging(self):
        sources = []
        assert _infer_environment("test on the sandbox environment", sources) == "staging"


# ---------------------------------------------------------------------------
# task_source vs target_application separation
# ---------------------------------------------------------------------------

class TestTaskSourceVsTargetApplication:
    def test_task_source_from_task_url(self):
        sources = [
            InputSource(
                input_type="task_url",
                raw_value="https://linear.app/org/issue/QA-123",
                label="[task_url] https://linear.app/org/issue/QA-123",
            )
        ]
        im = _make_input_map(sources=sources)
        wr = _make_work_request()
        result = _infer_task_source(im, wr)
        assert result.startswith("task_url:")
        assert "linear.app" not in result or "[task_url]" in result

    def test_task_source_from_platform(self):
        im = _make_input_map()
        wr = _make_work_request(platform="upwork")
        result = _infer_task_source(im, wr)
        assert "upwork" in result

    def test_task_source_defaults_to_pasted_brief(self):
        im = _make_input_map()
        wr = _make_work_request(platform="unknown")
        result = _infer_task_source(im, wr)
        assert result == "pasted_brief"

    def test_target_application_from_target_url(self):
        sources = [
            InputSource(
                input_type="target_url",
                raw_value="https://app.example.com",
                label="[target_url] https://app.example.com",
            )
        ]
        im = _make_input_map(sources=sources)
        result = _infer_target_application(im)
        assert "target_url" in result or "example" in result

    def test_target_application_empty_when_no_target_url(self):
        im = _make_input_map()
        result = _infer_target_application(im)
        assert result == ""

    def test_task_url_does_not_become_target_application(self):
        sources = [
            InputSource(
                input_type="task_url",
                raw_value="https://linear.app/org/issue/QA-123",
                label="[task_url] https://linear.app/org/issue/QA-123",
            )
        ]
        im = _make_input_map(sources=sources)
        result = _infer_target_application(im)
        assert result == ""

    def test_blueprint_separates_task_source_from_target(self):
        sources = [
            InputSource(input_type="task_url", raw_value="https://linear.app/task", label="[task_url] https://linear.app/task"),
            InputSource(input_type="target_url", raw_value="https://app.example.com", label="[target_url] https://app.example.com"),
        ]
        im = _make_input_map("sep-test", sources)
        wr = _make_work_request("sep-test", "Test task", "Test app on staging", "Test app on staging")
        tc = _make_classification("sep-test")
        bp = ProjectBlueprintBuilder().build(im, wr, tc)
        assert "linear" not in bp.target_application.lower()
        assert "example" in bp.target_application or "target_url" in bp.target_application


# ---------------------------------------------------------------------------
# Assumptions generation
# ---------------------------------------------------------------------------

class TestAssumptions:
    def test_assumptions_always_contains_no_execution_note(self):
        bp = _build("SaaS dashboard with login")
        no_exec = any("no live execution" in a.lower() for a in bp.assumptions)
        assert no_exec

    def test_assumptions_contain_project_type_note(self):
        bp = _build("SaaS dashboard")
        type_note = any("project type" in a.lower() for a in bp.assumptions)
        assert type_note

    def test_assumptions_contain_credential_note_when_creds_detected(self):
        sources = [
            InputSource(
                input_type="credentials_reference",
                raw_value="[REDACTED_PASSWORD]",
                label="[credentials_reference] [REDACTED_PASSWORD]",
            )
        ]
        im = _make_input_map(sources=sources)
        result = _build_assumptions("web_saas", "staging", im)
        cred_note = any("credential" in a.lower() for a in result)
        assert cred_note

    def test_assumptions_no_credential_note_without_creds(self):
        im = _make_input_map()
        result = _build_assumptions("web_saas", "staging", im)
        cred_note = any("credential references were detected" in a.lower() for a in result)
        assert not cred_note


# ---------------------------------------------------------------------------
# Missing information
# ---------------------------------------------------------------------------

class TestMissingInformation:
    def test_missing_info_requests_target_url_when_absent(self):
        bp = _build("SaaS dashboard needs QA automation")
        target_missing = any("target application url" in m.lower() or "target" in m.lower() for m in bp.missing_information)
        assert target_missing

    def test_missing_info_does_not_request_url_when_present(self):
        sources = [
            InputSource(input_type="target_url", raw_value="https://app.example.com", label="[target_url] https://app.example.com"),
        ]
        im = _make_input_map(sources=sources)
        result = _build_missing_info("web_saas", "staging", im, "SaaS app needs QA automation")
        url_missing = any("target application url" in m.lower() for m in result)
        assert not url_missing

    def test_missing_info_adds_production_warning(self):
        im = _make_input_map()
        result = _build_missing_info("web_saas", "production", im, "production app")
        prod_warning = any("production" in m.lower() for m in result)
        assert prod_warning

    def test_missing_info_adds_payment_sandbox_note(self):
        bp = _build("Test checkout flow payment stripe billing on ecommerce shop")
        payment_note = any("payment" in m.lower() or "sandbox" in m.lower() for m in bp.missing_information)
        assert payment_note

    def test_missing_info_adds_mobile_scope_note(self):
        bp = _build("Test the mobile app on iOS android react native")
        mobile_note = any("mobile" in m.lower() for m in bp.missing_information)
        assert mobile_note

    def test_missing_info_adds_api_doc_request_for_api_project(self):
        im = _make_input_map()
        result = _build_missing_info("api_backend", "unknown", im, "api tests needed")
        api_doc = any("openapi" in m.lower() or "swagger" in m.lower() or "api documentation" in m.lower() for m in result)
        assert api_doc

    def test_missing_info_adds_credential_account_note_when_auth_detected(self):
        bp = _build("Test login and OAuth2 SSO authentication 2FA")
        cred_note = any("test account" in m.lower() or "credentials" in m.lower() for m in bp.missing_information)
        assert cred_note


# ---------------------------------------------------------------------------
# Blocked actions
# ---------------------------------------------------------------------------

class TestBlockedActions:
    def test_blocked_includes_browser_execution(self):
        im = _make_input_map()
        result = _build_blocked_actions(im, "SaaS dashboard")
        browser_blocked = any("playwright" in b.lower() or "browser" in b.lower() for b in result)
        assert browser_blocked

    def test_blocked_includes_mobile_when_mobile_detected(self):
        im = _make_input_map()
        result = _build_blocked_actions(im, "mobile iOS android flutter app")
        mobile_blocked = any("mobile" in b.lower() for b in result)
        assert mobile_blocked

    def test_blocked_includes_target_url_when_present(self):
        sources = [
            InputSource(input_type="target_url", raw_value="https://app.example.com", label="[target_url] https://app.example.com"),
        ]
        im = _make_input_map(sources=sources)
        result = _build_blocked_actions(im, "test this app")
        url_blocked = any("target url" in b.lower() or "fetch target" in b.lower() for b in result)
        assert url_blocked

    def test_blocked_includes_credentials_when_present(self):
        sources = [
            InputSource(input_type="credentials_reference", raw_value="[REDACTED]", label="[credentials_reference] [REDACTED]"),
        ]
        im = _make_input_map(sources=sources)
        result = _build_blocked_actions(im, "test auth flow")
        cred_blocked = any("credential" in b.lower() for b in result)
        assert cred_blocked

    def test_blocked_includes_payment_testing_when_payment_detected(self):
        im = _make_input_map()
        result = _build_blocked_actions(im, "test checkout payment stripe billing")
        payment_blocked = any("payment" in b.lower() for b in result)
        assert payment_blocked

    def test_blocked_includes_security_testing_when_security_detected(self):
        im = _make_input_map()
        result = _build_blocked_actions(im, "security pentest owasp xss injection")
        security_blocked = any("security" in b.lower() for b in result)
        assert security_blocked

    def test_blocked_includes_integration_calls_when_integration_detected(self):
        im = _make_input_map()
        result = _build_blocked_actions(im, "notify via webhook n8n slack")
        integration_blocked = any("integration" in b.lower() or "n8n" in b.lower() or "webhook" in b.lower() for b in result)
        assert integration_blocked

    def test_blocked_includes_delivery_without_human_review(self):
        im = _make_input_map()
        result = _build_blocked_actions(im, "")
        delivery_blocked = any("client" in b.lower() and "report" in b.lower() for b in result)
        assert delivery_blocked


# ---------------------------------------------------------------------------
# Required approvals
# ---------------------------------------------------------------------------

class TestRequiredApprovals:
    def test_required_approvals_includes_url_approval_when_target_present(self):
        sources = [
            InputSource(input_type="target_url", raw_value="https://app.example.com", label="[target_url] ..."),
        ]
        im = _make_input_map(sources=sources)
        result = _build_required_approvals(im, "test the app", "staging")
        url_approval = any("target url" in a.lower() for a in result)
        assert url_approval

    def test_required_approvals_includes_production_when_production(self):
        im = _make_input_map()
        result = _build_required_approvals(im, "production app", "production")
        prod_approval = any("production" in a.lower() for a in result)
        assert prod_approval

    def test_required_approvals_fallback_when_no_specific_risks(self):
        im = _make_input_map()
        result = _build_required_approvals(im, "simple pasted brief", "staging")
        assert len(result) >= 1


# ---------------------------------------------------------------------------
# Safe next steps
# ---------------------------------------------------------------------------

class TestSafeNextSteps:
    def test_safe_steps_include_clarify_missing_info(self):
        im = _make_input_map()
        result = _build_safe_next_steps("web_saas", "qa_automation", "staging", im)
        clarify = any("missing information" in s.lower() or "clarify" in s.lower() for s in result)
        assert clarify

    def test_safe_steps_include_qa_strategy_for_qa_task(self):
        im = _make_input_map()
        result = _build_safe_next_steps("web_saas", "qa_automation", "staging", im)
        strategy = any("strategy" in s.lower() or "test plan" in s.lower() for s in result)
        assert strategy

    def test_safe_steps_include_proposal_items_for_proposal_task(self):
        im = _make_input_map()
        result = _build_safe_next_steps("unknown", "proposal", "none", im)
        proposal = any("proposal" in s.lower() for s in result)
        assert proposal

    def test_safe_steps_include_obtain_url_when_missing(self):
        im = _make_input_map()
        result = _build_safe_next_steps("web_saas", "qa_automation", "unknown", im)
        obtain = any("url" in s.lower() for s in result)
        assert obtain


# ---------------------------------------------------------------------------
# Confidence inference
# ---------------------------------------------------------------------------

class TestConfidenceInference:
    def test_low_confidence_for_unknown_everything(self):
        result = _infer_confidence("unknown", "unknown", False, 30)
        assert result == "low"

    def test_medium_confidence_with_known_type_and_environment(self):
        result = _infer_confidence("web_saas", "staging", False, 50)
        assert result == "medium"

    def test_high_confidence_with_all_signals(self):
        result = _infer_confidence("web_saas", "staging", True, 200)
        assert result == "high"


# ---------------------------------------------------------------------------
# Recommended strategy and tactical focus
# ---------------------------------------------------------------------------

class TestStrategyAndFocus:
    def test_recommended_strategy_web_saas_mentions_auth(self):
        result = _build_recommended_strategy("web_saas", "qa_automation", "")
        assert "auth" in result.lower()

    def test_recommended_strategy_ecommerce_mentions_checkout(self):
        result = _build_recommended_strategy("ecommerce", "qa_automation", "")
        assert "checkout" in result.lower()

    def test_recommended_strategy_api_backend_mentions_contract(self):
        result = _build_recommended_strategy("api_backend", "qa_automation", "")
        assert "contract" in result.lower()

    def test_recommended_strategy_proposal_mode(self):
        result = _build_recommended_strategy("unknown", "proposal", "")
        assert "proposal" in result.lower()

    def test_tactical_focus_returns_list_for_known_type(self):
        result = _build_tactical_focus("web_saas", "qa_automation")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_tactical_focus_proposal_mode(self):
        result = _build_tactical_focus("unknown", "proposal")
        assert any("proposal" in f.lower() or "scoping" in f.lower() for f in result)


# ---------------------------------------------------------------------------
# Blueprint artifact rendering
# ---------------------------------------------------------------------------

class TestBlueprintArtifactRendering:
    def test_render_artifacts_writes_all_seven_files(self, tmp_path):
        bp = _build("SaaS dashboard with login")
        builder = ProjectBlueprintBuilder()
        paths = builder.render_artifacts(bp, "qa_automation", tmp_path)

        expected_keys = [
            "blueprint_json",
            "blueprint_md",
            "assumptions_md",
            "missing_info_md",
            "safe_next_steps_md",
            "blocked_actions_md",
            "strategy_outline_md",
        ]
        for key in expected_keys:
            assert key in paths, f"Missing artifact key: {key}"
            assert Path(paths[key]).exists(), f"File not written: {paths[key]}"

    def test_blueprint_json_is_valid(self, tmp_path):
        bp = _build("SaaS dashboard with login")
        builder = ProjectBlueprintBuilder()
        paths = builder.render_artifacts(bp, "qa_automation", tmp_path)
        data = json.loads(Path(paths["blueprint_json"]).read_text(encoding="utf-8"))
        assert data["project_id"] == "test-bp"
        assert "project_type" in data

    def test_blueprint_md_contains_no_execution_disclaimer(self, tmp_path):
        bp = _build("SaaS dashboard with login")
        builder = ProjectBlueprintBuilder()
        paths = builder.render_artifacts(bp, "qa_automation", tmp_path)
        content = Path(paths["blueprint_md"]).read_text(encoding="utf-8")
        assert "no execution" in content.lower()

    def test_blocked_actions_md_contains_blocked_label(self, tmp_path):
        bp = _build("SaaS dashboard with login")
        builder = ProjectBlueprintBuilder()
        paths = builder.render_artifacts(bp, "qa_automation", tmp_path)
        content = Path(paths["blocked_actions_md"]).read_text(encoding="utf-8")
        assert "BLOCKED" in content or "blocked" in content.lower()

    def test_strategy_outline_md_contains_planning_only_note(self, tmp_path):
        bp = _build("SaaS dashboard with login")
        builder = ProjectBlueprintBuilder()
        paths = builder.render_artifacts(bp, "qa_automation", tmp_path)
        content = Path(paths["strategy_outline_md"]).read_text(encoding="utf-8")
        assert "planning only" in content.lower() or "no execution" in content.lower()


# ---------------------------------------------------------------------------
# Secret redaction in blueprints
# ---------------------------------------------------------------------------

class TestBlueprintSecretRedaction:
    def test_secret_not_in_blueprint_fields(self):
        controller = WorkbenchController()
        result = controller.build_project_blueprint(
            _make_input_map(),
            _make_work_request(
                raw_brief="Need tests, password=SuperSecret123, login as admin"
            ),
            _make_classification(),
        )
        bp_dict = result.to_dict()
        bp_json = json.dumps(bp_dict)
        assert "SuperSecret123" not in bp_json

    def test_redacted_placeholder_appears_in_credential_assumption(self):
        sources = [
            InputSource(
                input_type="credentials_reference",
                raw_value="[REDACTED_PASSWORD]",
                label="[credentials_reference] [REDACTED_PASSWORD]",
            )
        ]
        im = _make_input_map(sources=sources)
        result = _build_assumptions("web_saas", "staging", im)
        cred_assumption = any("credential" in a.lower() for a in result)
        assert cred_assumption

    def test_blueprint_artifacts_do_not_contain_secrets(self, tmp_path):
        controller = WorkbenchController(outputs_root=tmp_path)
        result = controller.build_context_with_blueprint(
            raw_inputs=["Need login tests, password=FakePass456, username=testuser"],
            raw_text="Need login tests, password=FakePass456, username=testuser",
            project_id="secret-bp-test",
        )
        # Check blueprint JSON artifact
        bp_json_path = Path(result["blueprint_artifact_paths"]["blueprint_json"])
        content = bp_json_path.read_text(encoding="utf-8")
        assert "FakePass456" not in content

    def test_credentials_reference_blocks_and_notes_in_blueprint(self):
        controller = WorkbenchController()
        result = controller.build_context_with_blueprint(
            raw_inputs=["Test login with token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJ1c2VyMTIzIn0.abcdef"],
            project_id="jwt-bp-test",
        )
        bp = result["blueprint"]
        assert any("credential" in a.lower() for a in bp.assumptions)
        assert any("credential" in b.lower() for b in bp.blocked_actions)


# ---------------------------------------------------------------------------
# WorkbenchController blueprint methods
# ---------------------------------------------------------------------------

class TestWorkbenchControllerBlueprintMethods:
    def test_build_project_blueprint_returns_blueprint_instance(self):
        controller = WorkbenchController()
        im = _make_input_map()
        wr = _make_work_request(raw_brief="SaaS dashboard with login and subscriptions")
        tc = _make_classification()
        bp = controller.build_project_blueprint(im, wr, tc)
        assert isinstance(bp, ProjectBlueprint)
        assert bp.project_id == "test-bp"

    def test_render_blueprint_artifacts_writes_files(self, tmp_path):
        controller = WorkbenchController(outputs_root=tmp_path)
        im = _make_input_map("render-test")
        wr = _make_work_request("render-test", raw_brief="SaaS dashboard tests")
        tc = _make_classification("render-test")
        bp = controller.build_project_blueprint(im, wr, tc)
        paths = controller.render_blueprint_artifacts(bp, "qa_automation", "render-test")
        for key, path in paths.items():
            assert Path(path).exists(), f"Missing: {key} -> {path}"

    def test_update_project_status_for_blueprint_returns_status(self):
        controller = WorkbenchController()
        bp = _build("SaaS dashboard")
        status = controller.update_project_status_for_blueprint("test-bp", bp)
        assert status.phase == "blueprint"
        assert status.overall_status == "in_progress"
        assert "missing information" in status.next_action.lower()

    def test_build_context_with_blueprint_returns_all_keys(self, tmp_path):
        controller = WorkbenchController(outputs_root=tmp_path)
        result = controller.build_context_with_blueprint(
            raw_inputs=["Need Playwright tests for a SaaS dashboard with user login"],
            project_id="full-context-test",
        )
        required_keys = [
            "project_id", "input_map", "work_request", "task_classification",
            "project_status", "next_safe_step", "artifact_paths",
            "blueprint", "blueprint_status", "blueprint_artifact_paths",
        ]
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_build_context_with_blueprint_blueprint_status_phase(self, tmp_path):
        controller = WorkbenchController(outputs_root=tmp_path)
        result = controller.build_context_with_blueprint(
            raw_inputs=["SaaS dashboard Playwright QA tests"],
            project_id="status-phase-test",
        )
        assert result["blueprint_status"].phase == "blueprint"

    def test_build_context_with_blueprint_artifact_paths_combined(self, tmp_path):
        controller = WorkbenchController(outputs_root=tmp_path)
        result = controller.build_context_with_blueprint(
            raw_inputs=["SaaS dashboard needs E2E tests"],
            project_id="combined-paths-test",
        )
        combined = result["artifact_paths"]
        # Phase 2A artifacts
        assert "input_map_json" in combined
        assert "work_request_json" in combined
        # Phase 2B artifacts
        assert "blueprint_json" in combined
        assert "strategy_outline_md" in combined

    def test_build_context_with_blueprint_no_execution_in_artifacts(self, tmp_path):
        controller = WorkbenchController(outputs_root=tmp_path)
        result = controller.build_context_with_blueprint(
            raw_inputs=["Need tests for an ecommerce shop checkout payment"],
            project_id="no-exec-test",
        )
        bp_md = Path(result["blueprint_artifact_paths"]["blueprint_md"]).read_text(encoding="utf-8")
        assert "no execution" in bp_md.lower()


# ---------------------------------------------------------------------------
# CLI --with-blueprint flag
# ---------------------------------------------------------------------------

class TestCLIWithBlueprint:
    def test_cli_with_blueprint_exits_zero(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        exit_code = cli_main([
            "--input", "Need Playwright tests for a SaaS dashboard with user login",
            "--project-id", "cli-bp-test",
            "--with-blueprint",
        ])
        assert exit_code == 0

    def test_cli_with_blueprint_writes_blueprint_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cli_main([
            "--input", "Need Playwright tests for a SaaS dashboard with user login",
            "--project-id", "cli-bp-json-test",
            "--with-blueprint",
        ])
        bp_path = tmp_path / "outputs" / "cli-bp-json-test" / "00_project" / "PROJECT_BLUEPRINT.json"
        assert bp_path.exists()

    def test_cli_with_blueprint_no_write_does_not_write_files(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cli_main([
            "--input", "SaaS QA automation dashboard",
            "--project-id", "cli-no-write-test",
            "--no-write",
            "--with-blueprint",
        ])
        # --no-write takes precedence; no blueprint file should appear
        bp_path = tmp_path / "outputs" / "cli-no-write-test" / "00_project" / "PROJECT_BLUEPRINT.json"
        assert not bp_path.exists()

    def test_cli_with_blueprint_json_flag_includes_blueprint(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        cli_main([
            "--input", "SaaS QA automation Playwright dashboard",
            "--project-id", "cli-json-bp-test",
            "--json",
            "--with-blueprint",
        ])
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "blueprint" in output

    def test_cli_without_blueprint_flag_no_blueprint_key(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        cli_main([
            "--input", "SaaS QA automation Playwright dashboard",
            "--project-id", "cli-no-bp-test",
            "--json",
        ])
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "blueprint" not in output

    def test_cli_with_blueprint_secrets_not_in_artifacts(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        cli_main([
            "--input", "Test login with password=FakeCliSecret789",
            "--project-id", "cli-secret-bp-test",
            "--with-blueprint",
        ])
        bp_path = tmp_path / "outputs" / "cli-secret-bp-test" / "00_project" / "PROJECT_BLUEPRINT.json"
        if bp_path.exists():
            content = bp_path.read_text(encoding="utf-8")
            assert "FakeCliSecret789" not in content

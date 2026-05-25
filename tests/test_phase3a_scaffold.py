"""test_phase3a_scaffold.py — Phase 3A: Framework Scaffold Generation tests.

Covers:
- FrameworkScaffold / FrameworkFile / FrameworkScaffoldPlan schema round-trips
- FrameworkScaffoldGenerator for all 8 project types
- File manifest completeness and content safety checks
- Safety defaults: execution_allowed=False, client_visible=False, requires_review=True
- Auth/API spec test.skip guards
- Blocked specs (checkout, admin)
- No subprocess, no playwright import in generator module
- WorkbenchController Phase 3A methods
- CLI generate_scaffold.py smoke
- docs_audit and agent_readiness_audit pass
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))  # noqa: E402

from core.schemas.framework_scaffold import (  # noqa: E402
    FrameworkFile,
    FrameworkScaffold,
    FrameworkScaffoldPlan,
)
from core.framework_scaffold_generator import FrameworkScaffoldGenerator  # noqa: E402
from core.schemas.project_blueprint import ProjectBlueprint  # noqa: E402
from core.schemas.qa_strategy import QAStrategy, TestLayerRecommendation  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_blueprint(
    project_type: str = "web_saas",
    project_id: str = "test-proj",
    project_name: str = "Test Project",
) -> ProjectBlueprint:
    return ProjectBlueprint(
        project_id=project_id,
        project_name=project_name,
        project_type=project_type,
        client_goal="Automate QA for a SaaS dashboard",
        scope_notes="Login, dashboard, API",
        environment="staging",
        application_surfaces=["web", "api"],
        risk_areas=["auth", "payments"],
    )


def _make_strategy(layers=None) -> QAStrategy:
    if layers is None:
        layers = [
            TestLayerRecommendation(layer="smoke",   recommended=True,  blocked=False),
            TestLayerRecommendation(layer="auth",    recommended=True,  blocked=False),
            TestLayerRecommendation(layer="api",     recommended=True,  blocked=False),
            TestLayerRecommendation(layer="visual",  recommended=False, blocked=False),
            TestLayerRecommendation(layer="mobile_native", recommended=False, blocked=True),
        ]
    return QAStrategy(
        project_id="test-proj",
        project_type="web_saas",
        test_layers=layers,
        confidence_level="medium",
        client_ready=False,
    )


def _gen(project_type: str = "web_saas", tmp_path: Path = None):
    bp = _make_blueprint(project_type=project_type)
    strategy = _make_strategy()
    gen = FrameworkScaffoldGenerator()
    out_dir = tmp_path if tmp_path else Path("/tmp/scaffold-test")
    scaffold = gen.generate_scaffold(bp, strategy, out_dir)
    return scaffold, out_dir


# ---------------------------------------------------------------------------
# Schema: FrameworkFile
# ---------------------------------------------------------------------------

class TestFrameworkFileSchema:
    def test_defaults(self):
        f = FrameworkFile()
        assert f.id == ""
        assert f.file_type == "unknown"
        assert f.client_visible is False
        assert f.generated is True
        assert f.requires_review is True
        assert f.notes == []

    def test_round_trip(self):
        f = FrameworkFile(
            id="ff-001",
            path="tests/smoke/smoke.spec.ts",
            purpose="Smoke test",
            file_type="test_spec",
            client_visible=False,
            generated=True,
            requires_review=True,
            notes=["placeholder"],
        )
        d = f.to_dict()
        f2 = FrameworkFile.from_dict(d)
        assert f2.id == f.id
        assert f2.path == f.path
        assert f2.notes == ["placeholder"]

    def test_to_dict_keys(self):
        f = FrameworkFile(id="ff-002", path="pages/BasePage.ts", file_type="page_object")
        d = f.to_dict()
        assert "id" in d
        assert "path" in d
        assert "file_type" in d
        assert "client_visible" in d


# ---------------------------------------------------------------------------
# Schema: FrameworkScaffold
# ---------------------------------------------------------------------------

class TestFrameworkScaffoldSchema:
    def test_defaults(self):
        s = FrameworkScaffold()
        assert s.framework_type == "playwright_ts"
        assert s.language == "typescript"
        assert s.test_runner == "playwright"
        assert s.execution_allowed is False
        assert s.client_visible is False
        assert s.requires_review is True
        assert s.scaffold_status == "generated"
        assert s.files == []

    def test_nested_round_trip(self):
        files = [
            FrameworkFile(id="ff-001", path="tests/smoke.spec.ts", file_type="test_spec"),
            FrameworkFile(id="ff-002", path="pages/BasePage.ts",   file_type="page_object"),
        ]
        s = FrameworkScaffold(
            project_id="proj-abc",
            files=files,
            execution_allowed=False,
            client_visible=False,
        )
        d = s.to_dict()
        s2 = FrameworkScaffold.from_dict(d)
        assert s2.project_id == "proj-abc"
        assert len(s2.files) == 2
        assert isinstance(s2.files[0], FrameworkFile)
        assert s2.files[0].id == "ff-001"
        assert s2.execution_allowed is False

    def test_to_dict_includes_files(self):
        s = FrameworkScaffold(files=[FrameworkFile(id="ff-001")])
        d = s.to_dict()
        assert isinstance(d["files"], list)
        assert d["files"][0]["id"] == "ff-001"

    def test_from_dict_reconstructs_files_as_typed(self):
        d = {
            "project_id": "p1",
            "files": [{"id": "ff-001", "path": "x.ts", "file_type": "test_spec"}],
        }
        s = FrameworkScaffold.from_dict(d)
        assert isinstance(s.files[0], FrameworkFile)

    def test_execution_always_false_by_default(self):
        s = FrameworkScaffold()
        assert s.execution_allowed is False


# ---------------------------------------------------------------------------
# Schema: FrameworkScaffoldPlan
# ---------------------------------------------------------------------------

class TestFrameworkScaffoldPlanSchema:
    def test_defaults(self):
        p = FrameworkScaffoldPlan()
        assert p.target_framework == "playwright_ts"
        assert p.included_layers == []
        assert p.blocked_layers == []

    def test_round_trip(self):
        p = FrameworkScaffoldPlan(
            project_id="p",
            target_framework="playwright_ts",
            included_layers=["smoke", "auth"],
            blocked_layers=["mobile_native"],
        )
        d = p.to_dict()
        p2 = FrameworkScaffoldPlan.from_dict(d)
        assert p2.included_layers == ["smoke", "auth"]
        assert p2.blocked_layers == ["mobile_native"]


# ---------------------------------------------------------------------------
# Generator: safety defaults
# ---------------------------------------------------------------------------

class TestGeneratorSafetyDefaults:
    def test_execution_allowed_false(self, tmp_path):
        scaffold, _ = _gen(tmp_path=tmp_path)
        assert scaffold.execution_allowed is False

    def test_client_visible_false(self, tmp_path):
        scaffold, _ = _gen(tmp_path=tmp_path)
        assert scaffold.client_visible is False

    def test_requires_review_true(self, tmp_path):
        scaffold, _ = _gen(tmp_path=tmp_path)
        assert scaffold.requires_review is True

    def test_scaffold_status_generated(self, tmp_path):
        scaffold, _ = _gen(tmp_path=tmp_path)
        assert scaffold.scaffold_status == "generated"

    def test_no_subprocess_import_in_generator(self):
        gen_path = _PROJECT_ROOT / "core" / "framework_scaffold_generator.py"
        content = gen_path.read_text(encoding="utf-8")
        assert "import subprocess" not in content

    def test_no_playwright_import_in_generator(self):
        gen_path = _PROJECT_ROOT / "core" / "framework_scaffold_generator.py"
        content = gen_path.read_text(encoding="utf-8")
        assert "from playwright" not in content
        assert "import playwright" not in content

    def test_no_npm_call_in_generator(self):
        gen_path = _PROJECT_ROOT / "core" / "framework_scaffold_generator.py"
        content = gen_path.read_text(encoding="utf-8")
        assert "npm install" not in content or "# npm install" in content or "```bash" in content
        # More targeted check — no subprocess.run with npm
        assert "subprocess.run" not in content

    def test_no_hardcoded_real_url_in_generator(self):
        gen_path = _PROJECT_ROOT / "core" / "framework_scaffold_generator.py"
        content = gen_path.read_text(encoding="utf-8")
        # localhost is fine as placeholder; external URLs are not
        for bad in ["https://", "http://app.", "http://staging.", "http://prod."]:
            assert bad not in content


# ---------------------------------------------------------------------------
# Generator: file manifest
# ---------------------------------------------------------------------------

class TestGeneratorFileManifest:
    def test_always_present_files(self, tmp_path):
        scaffold, out = _gen(tmp_path=tmp_path)
        paths = [f.path for f in scaffold.files]
        always = [
            "03_framework/playwright/package.json",
            "03_framework/playwright/tsconfig.json",
            "03_framework/playwright/playwright.config.ts",
            "03_framework/playwright/.gitignore",
            "03_framework/playwright/.env.example",
            "03_framework/playwright/README.md",
            "03_framework/playwright/tests/smoke/smoke.spec.ts",
            "03_framework/playwright/tests/regression/regression-placeholder.spec.ts",
            "03_framework/playwright/pages/BasePage.ts",
            "03_framework/playwright/fixtures/test-fixtures.ts",
            "03_framework/playwright/utils/env.ts",
            "03_framework/playwright/utils/test-data.ts",
            "03_framework/playwright/test-data/README.md",
            "03_framework/playwright/test-data/sample-users.example.json",
            "03_framework/playwright/docs/TEST_STRATEGY.md",
            "03_framework/playwright/docs/HOW_TO_RUN.md",
            "03_framework/playwright/docs/SCAFFOLD_REVIEW_CHECKLIST.md",
        ]
        for a in always:
            assert a in paths, f"Missing always-present file: {a}"

    def test_auth_files_present_for_web_saas(self, tmp_path):
        scaffold, _ = _gen("web_saas", tmp_path)
        paths = [f.path for f in scaffold.files]
        assert "03_framework/playwright/tests/auth/auth-placeholder.spec.ts" in paths
        assert "03_framework/playwright/pages/LoginPage.ts" in paths

    def test_auth_files_present_for_auth_heavy(self, tmp_path):
        scaffold, _ = _gen("auth_heavy", tmp_path)
        paths = [f.path for f in scaffold.files]
        assert "03_framework/playwright/tests/auth/auth-placeholder.spec.ts" in paths

    def test_api_files_present_for_api_backend(self, tmp_path):
        scaffold, _ = _gen("api_backend", tmp_path)
        paths = [f.path for f in scaffold.files]
        assert "03_framework/playwright/tests/api/api-placeholder.spec.ts" in paths
        assert "03_framework/playwright/utils/api-client.ts" in paths

    def test_api_files_present_for_mixed_ui_api(self, tmp_path):
        scaffold, _ = _gen("mixed_ui_api", tmp_path)
        paths = [f.path for f in scaffold.files]
        assert "03_framework/playwright/tests/api/api-placeholder.spec.ts" in paths

    def test_dashboard_page_for_web_saas(self, tmp_path):
        scaffold, _ = _gen("web_saas", tmp_path)
        paths = [f.path for f in scaffold.files]
        assert "03_framework/playwright/pages/DashboardPage.ts" in paths

    def test_checkout_spec_for_ecommerce(self, tmp_path):
        scaffold, _ = _gen("ecommerce", tmp_path)
        paths = [f.path for f in scaffold.files]
        assert "03_framework/playwright/tests/ecommerce/checkout-placeholder.spec.ts" in paths

    def test_admin_spec_for_admin_panel(self, tmp_path):
        scaffold, _ = _gen("admin_panel", tmp_path)
        paths = [f.path for f in scaffold.files]
        assert "03_framework/playwright/tests/admin/admin-placeholder.spec.ts" in paths

    def test_no_checkout_for_web_saas(self, tmp_path):
        scaffold, _ = _gen("web_saas", tmp_path)
        paths = [f.path for f in scaffold.files]
        assert "03_framework/playwright/tests/ecommerce/checkout-placeholder.spec.ts" not in paths

    def test_metadata_files_written(self, tmp_path):
        _gen(tmp_path=tmp_path)
        assert (tmp_path / "FRAMEWORK_SCAFFOLD.json").exists()
        assert (tmp_path / "FRAMEWORK_SCAFFOLD.md").exists()

    def test_all_files_physically_written(self, tmp_path):
        scaffold, out = _gen(tmp_path=tmp_path)
        prefix = "03_framework/playwright/"
        for f in scaffold.files:
            rel = f.path.replace(prefix, "", 1) if f.path.startswith(prefix) else f.path
            assert (out / Path(rel)).exists(), f"File not written: {rel}"


# ---------------------------------------------------------------------------
# Generator: content safety
# ---------------------------------------------------------------------------

class TestGeneratorContentSafety:
    def _all_content(self, tmp_path) -> str:
        texts = []
        for p in tmp_path.rglob("*"):
            if p.is_file() and p.suffix in (".ts", ".json", ".md", ".env.example", ""):
                try:
                    texts.append(p.read_text(encoding="utf-8"))
                except Exception:
                    pass
        return "\n".join(texts)

    def test_no_hardcoded_real_url(self, tmp_path):
        _gen(tmp_path=tmp_path)
        content = self._all_content(tmp_path)
        for bad in ["https://app.", "https://staging.", "https://prod.", "https://my-"]:
            assert bad not in content, f"Hardcoded URL found: {bad}"

    def test_localhost_placeholder_ok(self, tmp_path):
        _gen(tmp_path=tmp_path)
        content = self._all_content(tmp_path)
        assert "localhost:3000" in content

    def test_env_vars_in_playwright_config(self, tmp_path):
        _gen(tmp_path=tmp_path)
        config = (tmp_path / "playwright.config.ts").read_text(encoding="utf-8")
        assert "process.env.BASE_URL" in config

    def test_no_raw_password_in_files(self, tmp_path):
        _gen(tmp_path=tmp_path)
        content = self._all_content(tmp_path)
        # PLACEHOLDER_DO_NOT_USE is fine; a real secret like "s3cr3t" or a real password is not
        # We check that no secret redaction target patterns appear as real values
        assert "password=FakeSecret123" not in content
        assert "s3cr3t" not in content

    def test_sample_users_are_placeholder_only(self, tmp_path):
        _gen(tmp_path=tmp_path)
        sample = (tmp_path / "test-data" / "sample-users.example.json").read_text(encoding="utf-8")
        data = json.loads(sample)
        for user in data["users"]:
            assert "PLACEHOLDER" in user["password"]

    def test_env_example_has_no_real_password(self, tmp_path):
        _gen(tmp_path=tmp_path)
        env_ex = (tmp_path / ".env.example").read_text(encoding="utf-8")
        assert "PLACEHOLDER_DO_NOT_USE" in env_ex or "test-user@example.com" in env_ex
        # Must NOT have a real-looking password
        assert "secret" not in env_ex.lower() or "PLACEHOLDER" in env_ex

    def test_gitignore_excludes_dotenv(self, tmp_path):
        _gen(tmp_path=tmp_path)
        gi = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert ".env" in gi

    def test_gitignore_excludes_node_modules(self, tmp_path):
        _gen(tmp_path=tmp_path)
        gi = (tmp_path / ".gitignore").read_text(encoding="utf-8")
        assert "node_modules" in gi


# ---------------------------------------------------------------------------
# Generator: spec skip guards
# ---------------------------------------------------------------------------

class TestSpecSkipGuards:
    def test_auth_spec_skipped_without_env(self, tmp_path):
        scaffold, out = _gen("auth_heavy", tmp_path)
        auth_spec = (out / "tests" / "auth" / "auth-placeholder.spec.ts").read_text(encoding="utf-8")
        assert "test.skip" in auth_spec
        assert "TEST_USERNAME" in auth_spec

    def test_api_spec_skipped_without_env(self, tmp_path):
        scaffold, out = _gen("api_backend", tmp_path)
        api_spec = (out / "tests" / "api" / "api-placeholder.spec.ts").read_text(encoding="utf-8")
        assert "test.skip" in api_spec
        assert "API_BASE_URL" in api_spec

    def test_checkout_spec_blocked(self, tmp_path):
        scaffold, out = _gen("ecommerce", tmp_path)
        checkout = (out / "tests" / "ecommerce" / "checkout-placeholder.spec.ts").read_text(encoding="utf-8")
        assert "test.skip" in checkout
        assert "BLOCKED" in checkout or "sandbox" in checkout.lower()

    def test_admin_spec_blocked(self, tmp_path):
        scaffold, out = _gen("admin_panel", tmp_path)
        admin = (out / "tests" / "admin" / "admin-placeholder.spec.ts").read_text(encoding="utf-8")
        assert "test.skip" in admin
        assert "BLOCKED" in admin or "approval" in admin.lower()

    def test_regression_spec_skipped(self, tmp_path):
        scaffold, out = _gen(tmp_path=tmp_path)
        reg = (out / "tests" / "regression" / "regression-placeholder.spec.ts").read_text(encoding="utf-8")
        assert "test.skip" in reg


# ---------------------------------------------------------------------------
# Generator: all 8 project types
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("project_type", [
    "web_saas", "ecommerce", "api_backend", "ai_generated_app",
    "admin_panel", "auth_heavy", "mixed_ui_api", "unknown",
])
def test_generate_all_project_types(project_type, tmp_path):
    bp = _make_blueprint(project_type=project_type)
    gen = FrameworkScaffoldGenerator()
    scaffold = gen.generate_scaffold(bp, None, tmp_path)
    assert scaffold.execution_allowed is False
    assert scaffold.client_visible is False
    assert len(scaffold.files) >= 17  # always-present files
    assert (tmp_path / "FRAMEWORK_SCAFFOLD.json").exists()


@pytest.mark.parametrize("project_type,expected_fw", [
    ("web_saas",        "playwright_ts"),
    ("ecommerce",       "playwright_ts"),
    ("api_backend",     "api_only"),
    ("ai_generated_app","playwright_ts"),
    ("admin_panel",     "playwright_ts"),
    ("auth_heavy",      "playwright_ts"),
    ("mixed_ui_api",    "mixed_ui_api"),
    ("unknown",         "playwright_ts"),
])
def test_framework_type_per_project_type(project_type, expected_fw, tmp_path):
    bp = _make_blueprint(project_type=project_type)
    gen = FrameworkScaffoldGenerator()
    scaffold = gen.generate_scaffold(bp, None, tmp_path)
    assert scaffold.framework_type == expected_fw


# ---------------------------------------------------------------------------
# Generator: build_scaffold_plan
# ---------------------------------------------------------------------------

class TestBuildScaffoldPlan:
    def test_returns_plan(self):
        bp = _make_blueprint()
        gen = FrameworkScaffoldGenerator()
        plan = gen.build_scaffold_plan(bp)
        assert plan.project_id == bp.project_id
        assert plan.target_framework in ("playwright_ts", "api_only", "mixed_ui_api")
        assert len(plan.recommended_structure) > 0

    def test_plan_has_required_approvals(self):
        bp = _make_blueprint()
        gen = FrameworkScaffoldGenerator()
        plan = gen.build_scaffold_plan(bp)
        assert len(plan.required_approvals) > 0

    def test_plan_with_strategy_layers(self):
        bp = _make_blueprint()
        strategy = _make_strategy()
        gen = FrameworkScaffoldGenerator()
        plan = gen.build_scaffold_plan(bp, strategy)
        assert "smoke" in plan.included_layers or len(plan.included_layers) > 0


# ---------------------------------------------------------------------------
# Generator: scaffold metadata JSON
# ---------------------------------------------------------------------------

class TestScaffoldMetadataJson:
    def test_json_valid(self, tmp_path):
        _gen(tmp_path=tmp_path)
        data = json.loads((tmp_path / "FRAMEWORK_SCAFFOLD.json").read_text(encoding="utf-8"))
        assert "project_id" in data
        assert "files" in data
        assert data["execution_allowed"] is False
        assert data["client_visible"] is False

    def test_json_files_list_nonempty(self, tmp_path):
        _gen(tmp_path=tmp_path)
        data = json.loads((tmp_path / "FRAMEWORK_SCAFFOLD.json").read_text(encoding="utf-8"))
        assert len(data["files"]) >= 17

    def test_md_contains_safety_notes(self, tmp_path):
        _gen(tmp_path=tmp_path)
        md = (tmp_path / "FRAMEWORK_SCAFFOLD.md").read_text(encoding="utf-8")
        assert "execution_allowed" in md
        assert "No tests have been executed" in md


# ---------------------------------------------------------------------------
# WorkbenchController Phase 3A
# ---------------------------------------------------------------------------

class TestWorkbenchControllerPhase3A:
    def test_build_framework_scaffold(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        ctrl = WorkbenchController(outputs_root=tmp_path)
        bp = _make_blueprint()
        scaffold = ctrl.build_framework_scaffold(bp)
        assert scaffold.execution_allowed is False
        assert scaffold.project_id == bp.project_id

    def test_render_framework_scaffold_artifacts(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        ctrl = WorkbenchController(outputs_root=tmp_path)
        bp = _make_blueprint(project_id="ctrl-test")
        scaffold = ctrl.build_framework_scaffold(bp)
        paths = ctrl.render_framework_scaffold_artifacts(scaffold, "ctrl-test")
        assert "framework_scaffold_json" in paths
        assert Path(paths["framework_scaffold_json"]).exists()

    def test_update_project_status_for_scaffold(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        ctrl = WorkbenchController(outputs_root=tmp_path)
        bp = _make_blueprint()
        scaffold = ctrl.build_framework_scaffold(bp)
        status = ctrl.update_project_status_for_scaffold(bp.project_id, scaffold)
        assert status.phase == "scaffold"
        assert "execution_allowed" in status.notes

    def test_build_context_with_scaffold(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        ctrl = WorkbenchController(outputs_root=tmp_path)
        result = ctrl.build_context_with_scaffold(
            raw_inputs=["Need Playwright tests for SaaS dashboard with login"],
            project_id="ctx-scaffold-test",
        )
        assert "scaffold" in result
        assert result["scaffold"].execution_allowed is False
        assert "scaffold_artifact_paths" in result
        assert "scaffold_status" in result

    def test_full_pipeline_result_keys(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        ctrl = WorkbenchController(outputs_root=tmp_path)
        result = ctrl.build_context_with_scaffold(
            raw_inputs=["API backend testing for REST service"],
            project_id="full-pipe-test",
        )
        required_keys = [
            "project_id", "input_map", "work_request", "task_classification",
            "blueprint", "strategy", "scaffold",
            "artifact_paths", "scaffold_artifact_paths",
        ]
        for k in required_keys:
            assert k in result, f"Missing key: {k}"


# ---------------------------------------------------------------------------
# CLI: generate_scaffold.py smoke
# ---------------------------------------------------------------------------

class TestGenerateScaffoldCli:
    def test_cli_help(self):
        result = subprocess.run(
            [sys.executable, "tools/generate_scaffold.py", "--help"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "scaffold" in result.stdout.lower()

    def test_cli_no_args_exits_1(self):
        result = subprocess.run(
            [sys.executable, "tools/generate_scaffold.py"],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 1

    def test_cli_input_no_write(self):
        result = subprocess.run(
            [
                sys.executable, "tools/generate_scaffold.py",
                "--input", "Need Playwright tests for a SaaS dashboard with login and API checks",
                "--project-id", "cli-smoke-test",
                "--no-write",
            ],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "cli-smoke-test" in result.stdout or "Phase 3A" in result.stdout

    def test_cli_json_output(self):
        result = subprocess.run(
            [
                sys.executable, "tools/generate_scaffold.py",
                "--input", "API backend with REST endpoints",
                "--project-id", "cli-json-test",
                "--json",
            ],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["execution_allowed"] is False
        assert "files" in data

    def test_cli_secret_not_in_scaffold(self):
        result = subprocess.run(
            [
                sys.executable, "tools/generate_scaffold.py",
                "--input", "password=FakeSecret123 Need SaaS tests",
                "--project-id", "cli-redact-test",
                "--json",
            ],
            cwd=str(_PROJECT_ROOT),
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "FakeSecret123" not in result.stdout


# ---------------------------------------------------------------------------
# Audit tools
# ---------------------------------------------------------------------------

class TestAuditTools:
    def test_docs_audit_passes(self):
        import tools.docs_audit as da
        orig = sys.argv[:]
        try:
            sys.argv = ["docs_audit.py", "--no-write"]
            exit_code = da.main()
        finally:
            sys.argv = orig
        assert exit_code == 0, "docs_audit reported failures"

    def test_agent_readiness_audit_passes(self):
        import tools.agent_readiness_audit as ara
        exit_code = ara.main(["--no-write"])
        assert exit_code == 0, "agent_readiness_audit reported failures"

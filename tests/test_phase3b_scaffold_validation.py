"""Tests for Phase 3B: Safe Local Scaffold Validation Planning and Static Checks."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from core.scaffold_validator import ScaffoldValidator
from core.schemas.scaffold_validation import (
    ScaffoldValidationCheck,
    ScaffoldValidationReport,
    ToolchainValidationPlan,
)
from core.workbench_controller import WorkbenchController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_minimal_scaffold(tmp_path: Path, project_id: str = "test-proj") -> Path:
    """Write the minimum required files for a passing scaffold inside a mock outputs/ tree."""
    root = tmp_path / "outputs" / project_id / "03_framework" / "playwright"
    root.mkdir(parents=True, exist_ok=True)

    pkg = {
        "name": "test-scaffold",
        "version": "1.0.0",
        "scripts": {"test": "playwright test"},
        "devDependencies": {"@playwright/test": "^1.40.0"},
    }
    (root / "package.json").write_text(json.dumps(pkg), encoding="utf-8")

    (root / "playwright.config.ts").write_text(
        "import { defineConfig } from '@playwright/test';\n"
        "export default defineConfig({ use: { baseURL: process.env.BASE_URL } });\n",
        encoding="utf-8",
    )

    (root / ".env.example").write_text(
        "BASE_URL=http://localhost:3000\nTEST_USERNAME=\nTEST_PASSWORD=\n",
        encoding="utf-8",
    )

    (root / "tsconfig.json").write_text(
        '{"compilerOptions": {"target": "ES2019", "module": "commonjs"}}',
        encoding="utf-8",
    )

    (root / "README.md").write_text(
        "# Test Scaffold\n\nCopy .env.example to .env. Set BASE_URL.\n",
        encoding="utf-8",
    )

    tests_dir = root / "tests" / "smoke"
    tests_dir.mkdir(parents=True)
    (tests_dir / "smoke.spec.ts").write_text(
        "import { test, expect } from '@playwright/test';\n"
        "test('placeholder', async ({ page }) => { expect(true).toBe(true); });\n",
        encoding="utf-8",
    )

    pages_dir = root / "pages"
    pages_dir.mkdir()
    (pages_dir / "BasePage.ts").write_text(
        "export class BasePage { constructor(protected page: any) {} }\n",
        encoding="utf-8",
    )

    fixtures_dir = root / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "test-fixtures.ts").write_text(
        "import { test as base } from '@playwright/test';\nexport const test = base;\n",
        encoding="utf-8",
    )

    utils_dir = root / "utils"
    utils_dir.mkdir()
    (utils_dir / "env.ts").write_text(
        "export const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';\n",
        encoding="utf-8",
    )

    # Metadata
    meta = {
        "project_id": "test-proj",
        "framework_type": "playwright_ts",
        "execution_allowed": False,
        "client_visible": False,
        "requires_review": True,
        "scaffold_status": "generated",
    }
    (root / "FRAMEWORK_SCAFFOLD.json").write_text(json.dumps(meta), encoding="utf-8")

    return root


def _scaffold_in_outputs(tmp_path: Path) -> Path:
    """Create scaffold inside a mock outputs/ structure for boundary checks."""
    outputs = tmp_path / "outputs" / "proj-abc" / "03_framework" / "playwright"
    outputs.mkdir(parents=True)
    return outputs


# ---------------------------------------------------------------------------
# Schema round-trips
# ---------------------------------------------------------------------------

class TestScaffoldValidationCheckSchema:
    def test_default_fields(self):
        c = ScaffoldValidationCheck()
        assert c.id == ""
        assert c.category == "structure"
        assert c.status == "skipped"
        assert c.severity == "info"
        assert c.blocks_next_phase is False
        assert c.notes == []

    def test_roundtrip(self):
        c = ScaffoldValidationCheck(
            id="CHK-001",
            name="file present",
            category="structure",
            status="pass",
            severity="info",
            file_path="package.json",
            message="ok",
            blocks_next_phase=False,
            notes=["note1"],
        )
        d = c.to_dict()
        c2 = ScaffoldValidationCheck.from_dict(d)
        assert c2.id == "CHK-001"
        assert c2.name == "file present"
        assert c2.notes == ["note1"]
        assert c2.blocks_next_phase is False


class TestScaffoldValidationReportSchema:
    def test_safety_defaults(self):
        r = ScaffoldValidationReport()
        assert r.execution_performed is False
        assert r.npm_performed is False
        assert r.npx_performed is False
        assert r.browser_performed is False
        assert r.external_calls_performed is False
        assert r.safe_to_execute_tests is False
        assert r.safe_to_proceed_to_toolchain_validation is False
        assert r.validation_status == "unknown"
        assert r.checks == []

    def test_roundtrip_with_checks(self):
        check = ScaffoldValidationCheck(id="CHK-001", name="test", status="pass")
        r = ScaffoldValidationReport(
            project_id="proj-1",
            scaffold_root="/tmp/x",
            validation_status="pass",
            checks=[check],
            blockers=[],
            warnings=["warn1"],
            safe_to_proceed_to_toolchain_validation=True,
        )
        d = r.to_dict()
        r2 = ScaffoldValidationReport.from_dict(d)
        assert r2.project_id == "proj-1"
        assert r2.validation_status == "pass"
        assert r2.safe_to_proceed_to_toolchain_validation is True
        assert len(r2.checks) == 1
        assert isinstance(r2.checks[0], ScaffoldValidationCheck)
        assert r2.checks[0].id == "CHK-001"
        assert r2.warnings == ["warn1"]
        assert r2.execution_performed is False
        assert r2.safe_to_execute_tests is False

    def test_checks_reconstructed_as_typed(self):
        raw = {
            "project_id": "p",
            "scaffold_root": "/x",
            "validation_status": "pass",
            "checks": [{"id": "CHK-001", "name": "x", "status": "pass", "category": "structure",
                        "severity": "info", "file_path": "", "message": "", "recommendation": "",
                        "blocks_next_phase": False, "notes": []}],
            "blockers": [],
            "warnings": [],
        }
        r = ScaffoldValidationReport.from_dict(raw)
        assert isinstance(r.checks[0], ScaffoldValidationCheck)


class TestToolchainValidationPlanSchema:
    def test_safety_defaults(self):
        p = ToolchainValidationPlan()
        assert p.approval_required is True
        assert p.network_access_required is True
        assert p.browser_execution_required is False
        assert p.safe_without_approval is False

    def test_roundtrip(self):
        p = ToolchainValidationPlan(
            project_id="proj-1",
            proposed_commands=["npm install"],
            approval_required=True,
        )
        d = p.to_dict()
        p2 = ToolchainValidationPlan.from_dict(d)
        assert p2.project_id == "proj-1"
        assert p2.proposed_commands == ["npm install"]
        assert p2.approval_required is True
        assert p2.safe_without_approval is False


# ---------------------------------------------------------------------------
# ScaffoldValidator: happy path
# ---------------------------------------------------------------------------

class TestScaffoldValidatorHappyPath:
    def test_complete_scaffold_passes(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        validator = ScaffoldValidator(outputs_root=tmp_path / "outputs")
        report = validator.validate_scaffold(root, "test-proj")

        assert report.validation_status in ("pass", "warning")
        assert report.execution_performed is False
        assert report.npm_performed is False
        assert report.npx_performed is False
        assert report.browser_performed is False
        assert report.external_calls_performed is False
        assert report.safe_to_execute_tests is False
        assert len(report.checks) > 0

    def test_safety_invariants_always_false(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root)
        assert report.execution_performed is False
        assert report.npm_performed is False
        assert report.npx_performed is False
        assert report.browser_performed is False
        assert report.external_calls_performed is False
        assert report.safe_to_execute_tests is False

    def test_scaffold_root_stored(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "my-proj")
        assert report.scaffold_root == str(root)
        assert report.project_id == "my-proj"

    def test_checks_have_ids(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root)
        for c in report.checks:
            assert c.id.startswith("CHK-")


# ---------------------------------------------------------------------------
# Structure checks
# ---------------------------------------------------------------------------

class TestStructureChecks:
    def test_missing_required_file_is_blocker(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        (root / "package.json").unlink()
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        failing = [c for c in report.checks if c.status == "fail" and "package.json" in c.file_path]
        assert any(c.blocks_next_phase for c in failing)
        assert report.validation_status == "fail"
        assert report.safe_to_proceed_to_toolchain_validation is False

    def test_missing_tests_dir_is_blocker(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        import shutil
        shutil.rmtree(root / "tests", ignore_errors=True)
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        assert report.validation_status == "fail"


# ---------------------------------------------------------------------------
# Metadata checks
# ---------------------------------------------------------------------------

class TestMetadataChecks:
    def test_execution_allowed_true_is_blocker(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        meta = json.loads((root / "FRAMEWORK_SCAFFOLD.json").read_text())
        meta["execution_allowed"] = True
        (root / "FRAMEWORK_SCAFFOLD.json").write_text(json.dumps(meta))
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        blocker_checks = [
            c for c in report.checks
            if "execution_allowed" in c.name and c.status == "fail"
        ]
        assert blocker_checks
        assert blocker_checks[0].blocks_next_phase is True
        assert report.validation_status == "fail"

    def test_client_visible_true_is_blocker(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        meta = json.loads((root / "FRAMEWORK_SCAFFOLD.json").read_text())
        meta["client_visible"] = True
        (root / "FRAMEWORK_SCAFFOLD.json").write_text(json.dumps(meta))
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        blocker_checks = [
            c for c in report.checks
            if "client_visible" in c.name and c.status == "fail"
        ]
        assert blocker_checks
        assert blocker_checks[0].blocks_next_phase is True

    def test_requires_review_false_is_blocker(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        meta = json.loads((root / "FRAMEWORK_SCAFFOLD.json").read_text())
        meta["requires_review"] = False
        (root / "FRAMEWORK_SCAFFOLD.json").write_text(json.dumps(meta))
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        blocker_checks = [
            c for c in report.checks
            if "requires_review" in c.name and c.status == "fail"
        ]
        assert blocker_checks
        assert blocker_checks[0].blocks_next_phase is True

    def test_missing_metadata_is_blocker(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        (root / "FRAMEWORK_SCAFFOLD.json").unlink()
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        assert report.validation_status == "fail"


# ---------------------------------------------------------------------------
# package.json checks
# ---------------------------------------------------------------------------

class TestPackageJsonChecks:
    def test_postinstall_hook_is_blocker(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        pkg = json.loads((root / "package.json").read_text())
        pkg["scripts"]["postinstall"] = "node evil.js"
        (root / "package.json").write_text(json.dumps(pkg))
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        blocker = [
            c for c in report.checks
            if "lifecycle" in c.name.lower() and c.status == "fail"
        ]
        assert blocker
        assert blocker[0].blocks_next_phase is True

    def test_preinstall_hook_is_blocker(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        pkg = json.loads((root / "package.json").read_text())
        pkg["scripts"]["preinstall"] = "node setup.js"
        (root / "package.json").write_text(json.dumps(pkg))
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        blocker = [
            c for c in report.checks
            if "lifecycle" in c.name.lower() and c.status == "fail"
        ]
        assert blocker

    def test_playwright_missing_is_warning(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        pkg = json.loads((root / "package.json").read_text())
        pkg["devDependencies"] = {}
        (root / "package.json").write_text(json.dumps(pkg))
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        warn = [
            c for c in report.checks
            if "@playwright/test" in c.name and c.status == "warning"
        ]
        assert warn


# ---------------------------------------------------------------------------
# Secrets check
# ---------------------------------------------------------------------------

class TestSecretsCheck:
    def test_literal_trigger_in_ts_file_is_blocker(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        (root / "tests" / "smoke" / "smoke.spec.ts").write_text(
            "const secret = 'FakeSecret123';\n",
            encoding="utf-8",
        )
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        secret_fail = [
            c for c in report.checks
            if c.category == "secrets" and c.status == "fail"
        ]
        assert secret_fail
        assert secret_fail[0].blocks_next_phase is True

    def test_no_secrets_passes(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        secret_checks = [c for c in report.checks if c.category == "secrets"]
        assert any(c.status == "pass" for c in secret_checks)

    def test_secret_not_in_validation_artifacts(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        validator = ScaffoldValidator(outputs_root=tmp_path / "outputs")
        report = validator.validate_scaffold(root, "p")
        plan = validator.build_toolchain_validation_plan(root, "p")
        paths = validator.render_validation_artifacts(report, plan, root)
        for artifact_path in paths.values():
            content = Path(artifact_path).read_text(encoding="utf-8")
            assert "FakeSecret123" not in content


# ---------------------------------------------------------------------------
# URL check
# ---------------------------------------------------------------------------

class TestUrlCheck:
    def test_external_url_in_config_is_blocker(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        (root / "playwright.config.ts").write_text(
            "export default { use: { baseURL: 'https://real-app.example.io/test' } };\n",
            encoding="utf-8",
        )
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        url_fail = [c for c in report.checks if c.category == "urls" and c.status == "fail"]
        assert url_fail
        assert url_fail[0].blocks_next_phase is True

    def test_process_env_url_passes(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        url_checks = [c for c in report.checks if c.category == "urls"]
        assert any(c.status == "pass" for c in url_checks)


# ---------------------------------------------------------------------------
# Repository boundary check
# ---------------------------------------------------------------------------

class TestRepositoryBoundaryCheck:
    def test_scaffold_outside_outputs_is_blocker(self, tmp_path):
        # Create scaffold outside the mock outputs/ root
        outside_root = tmp_path / "outside" / "playwright"
        outside_root.mkdir(parents=True)
        outputs_root = tmp_path / "outputs"
        outputs_root.mkdir(parents=True)

        validator = ScaffoldValidator(outputs_root=outputs_root)
        report = validator.validate_scaffold(outside_root, "p")
        boundary_fail = [
            c for c in report.checks
            if c.category == "repository_boundary" and c.status == "fail"
        ]
        assert boundary_fail, "Expected boundary blocker for scaffold outside outputs/"
        assert boundary_fail[0].blocks_next_phase is True

    def test_git_dir_in_scaffold_is_blocker(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        (root / ".git").mkdir()
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        git_fail = [
            c for c in report.checks
            if ".git" in c.name and c.status == "fail"
        ]
        assert git_fail
        assert git_fail[0].blocks_next_phase is True


# ---------------------------------------------------------------------------
# Toolchain validation plan
# ---------------------------------------------------------------------------

class TestToolchainValidationPlan:
    def test_npm_install_in_proposed_commands(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        plan = ScaffoldValidator(outputs_root=tmp_path / "outputs").build_toolchain_validation_plan(root, "p")
        assert plan.approval_required is True
        assert plan.safe_without_approval is False
        assert plan.network_access_required is True
        assert any("npm install" in cmd for cmd in plan.proposed_commands)

    def test_plan_roundtrip(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        plan = ScaffoldValidator().build_toolchain_validation_plan(root, "p")
        d = plan.to_dict()
        p2 = ToolchainValidationPlan.from_dict(d)
        assert p2.approval_required is True
        assert p2.safe_without_approval is False
        assert p2.proposed_commands == plan.proposed_commands


# ---------------------------------------------------------------------------
# Artifact rendering
# ---------------------------------------------------------------------------

class TestValidationArtifacts:
    def test_all_artifacts_written(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        validator = ScaffoldValidator(outputs_root=tmp_path / "outputs")
        report = validator.validate_scaffold(root, "p")
        plan = validator.build_toolchain_validation_plan(root, "p")
        paths = validator.render_validation_artifacts(report, plan, root)

        assert "validation_report_json" in paths
        assert "validation_report_md" in paths
        assert "validation_plan_md" in paths
        assert "local_checklist_md" in paths
        assert "toolchain_plan_md" in paths

        for key, path in paths.items():
            assert Path(path).exists(), f"Artifact not found: {key} -> {path}"

    def test_report_json_is_valid(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        validator = ScaffoldValidator(outputs_root=tmp_path / "outputs")
        report = validator.validate_scaffold(root, "p")
        plan = validator.build_toolchain_validation_plan(root, "p")
        paths = validator.render_validation_artifacts(report, plan, root)

        data = json.loads(Path(paths["validation_report_json"]).read_text())
        assert data["execution_performed"] is False
        assert data["safe_to_execute_tests"] is False
        assert "checks" in data

    def test_report_md_contains_safety_section(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        validator = ScaffoldValidator(outputs_root=tmp_path / "outputs")
        report = validator.validate_scaffold(root, "p")
        plan = validator.build_toolchain_validation_plan(root, "p")
        paths = validator.render_validation_artifacts(report, plan, root)

        md = Path(paths["validation_report_md"]).read_text(encoding="utf-8")
        assert "Safety Invariants" in md
        assert "execution_performed" in md

    def test_toolchain_plan_md_notes_approval_required(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        validator = ScaffoldValidator(outputs_root=tmp_path / "outputs")
        report = validator.validate_scaffold(root, "p")
        plan = validator.build_toolchain_validation_plan(root, "p")
        paths = validator.render_validation_artifacts(report, plan, root)

        md = Path(paths["toolchain_plan_md"]).read_text(encoding="utf-8")
        assert "approval" in md.lower()
        assert "NOT YET EXECUTED" in md

    def test_local_checklist_md_has_blocker_section(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        validator = ScaffoldValidator(outputs_root=tmp_path / "outputs")
        report = validator.validate_scaffold(root, "p")
        plan = validator.build_toolchain_validation_plan(root, "p")
        paths = validator.render_validation_artifacts(report, plan, root)

        md = Path(paths["local_checklist_md"]).read_text(encoding="utf-8")
        assert "Blockers" in md


# ---------------------------------------------------------------------------
# WorkbenchController Phase 3B API
# ---------------------------------------------------------------------------

class TestWorkbenchControllerPhase3B:
    def test_validate_framework_scaffold_by_path(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        ctrl = WorkbenchController(outputs_root=tmp_path / "outputs")
        report = ctrl.validate_framework_scaffold(str(root))
        assert report.execution_performed is False
        assert report.safe_to_execute_tests is False

    def test_build_toolchain_validation_plan(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        ctrl = WorkbenchController(outputs_root=tmp_path / "outputs")
        plan = ctrl.build_toolchain_validation_plan(str(root))
        assert plan.approval_required is True
        assert plan.safe_without_approval is False

    def test_render_scaffold_validation_artifacts(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        ctrl = WorkbenchController(outputs_root=tmp_path / "outputs")
        report = ctrl.validate_framework_scaffold(str(root), "p")
        plan = ctrl.build_toolchain_validation_plan(str(root), "p")
        paths = ctrl.render_scaffold_validation_artifacts(report, plan, "p")
        assert "validation_report_json" in paths


# ---------------------------------------------------------------------------
# Safety: validator module does not import subprocess or playwright
# ---------------------------------------------------------------------------

class TestValidatorModuleSafety:
    def test_no_subprocess_import(self):
        import ast
        src = Path("core/scaffold_validator.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]
                for name in names:
                    assert "subprocess" not in (name or ""), "subprocess imported in scaffold_validator"
                    assert "playwright" not in (name or "").lower(), "playwright imported in scaffold_validator"

    def test_no_npm_calls_in_source(self):
        src = Path("core/scaffold_validator.py").read_text(encoding="utf-8")
        assert "npm install" not in src or "proposed_commands" in src
        assert "subprocess.run" not in src
        assert "subprocess.Popen" not in src
        assert "os.system" not in src


# ---------------------------------------------------------------------------
# CLI smoke tests
# ---------------------------------------------------------------------------

class TestValidateScaffoldCli:
    def test_help(self):
        result = subprocess.run(
            [sys.executable, "tools/validate_scaffold.py", "--help"],
            capture_output=True, text=True
        )
        assert result.returncode == 0
        assert "scaffold" in result.stdout.lower()

    def test_missing_scaffold_root_exits_1(self, tmp_path):
        result = subprocess.run(
            [sys.executable, "tools/validate_scaffold.py",
             "--scaffold-root", str(tmp_path / "nonexistent")],
            capture_output=True, text=True
        )
        assert result.returncode == 1

    def test_no_args_exits_1(self):
        result = subprocess.run(
            [sys.executable, "tools/validate_scaffold.py"],
            capture_output=True, text=True
        )
        assert result.returncode == 1

    def test_json_output(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        result = subprocess.run(
            [sys.executable, "tools/validate_scaffold.py",
             "--scaffold-root", str(root), "--json", "--no-write"],
            capture_output=True, text=True
        )
        assert result.returncode in (0, 1)
        out = json.loads(result.stdout)
        assert "report" in out
        assert "plan" in out
        assert out["report"]["execution_performed"] is False
        assert out["report"]["safe_to_execute_tests"] is False

    def test_text_output_contains_safety_invariants(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        result = subprocess.run(
            [sys.executable, "tools/validate_scaffold.py",
             "--scaffold-root", str(root), "--no-write"],
            capture_output=True, text=True
        )
        assert "execution_performed" in result.stdout
        assert "safe_to_execute_tests" in result.stdout

    def test_no_write_skips_artifacts(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        subprocess.run(
            [sys.executable, "tools/validate_scaffold.py",
             "--scaffold-root", str(root), "--no-write"],
            capture_output=True, text=True
        )
        assert not (root / "STATIC_VALIDATION_REPORT.json").exists()

    def test_writes_artifacts_by_default(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        subprocess.run(
            [sys.executable, "tools/validate_scaffold.py",
             "--scaffold-root", str(root)],
            capture_output=True, text=True
        )
        assert (root / "STATIC_VALIDATION_REPORT.json").exists()

    def test_fail_exits_1_on_blocker(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        (root / "package.json").unlink()
        result = subprocess.run(
            [sys.executable, "tools/validate_scaffold.py",
             "--scaffold-root", str(root), "--no-write"],
            capture_output=True, text=True
        )
        assert result.returncode == 1


# ---------------------------------------------------------------------------
# Secret not in artifacts (integration smoke)
# ---------------------------------------------------------------------------

class TestSecretNotInArtifacts:
    def test_fake_secret_in_ts_not_echoed(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        (root / "tests" / "smoke" / "smoke.spec.ts").write_text(
            "const x = 'FakeSecret123';\n", encoding="utf-8"
        )
        validator = ScaffoldValidator(outputs_root=tmp_path / "outputs")
        report = validator.validate_scaffold(root, "secret-test")
        plan = validator.build_toolchain_validation_plan(root, "secret-test")
        paths = validator.render_validation_artifacts(report, plan, root)

        for artifact_path in paths.values():
            content = Path(artifact_path).read_text(encoding="utf-8")
            assert "FakeSecret123" not in content, (
                f"Secret echoed into artifact: {artifact_path}"
            )

    def test_validation_status_fail_on_secret(self, tmp_path):
        root = _make_minimal_scaffold(tmp_path)
        (root / "tests" / "smoke" / "smoke.spec.ts").write_text(
            "const key = 'FakeSecret123';\n", encoding="utf-8"
        )
        report = ScaffoldValidator(outputs_root=tmp_path / "outputs").validate_scaffold(root, "p")
        assert report.validation_status == "fail"
        assert report.safe_to_execute_tests is False

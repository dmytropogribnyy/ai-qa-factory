"""Phase 5M-R tests — end-to-end demo workflow with real fixture specs.

Validates the full pipeline:
  fixtures/demo_specs/ → APIContractImporter → APITestGenerator → CICDBuilder

All specs are local fixtures — no network calls.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.api_contract_importer import APIContractImporter
from core.api_test_generator import APITestGenerator
from core.cicd_builder import CICDBuilder

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "demo_specs"

PETSTORE_JSON = _FIXTURES / "petstore_openapi.json"
SAMPLE_YAML = _FIXTURES / "sample_openapi.yaml"
RISKY_JSON = _FIXTURES / "risky_api_openapi.json"
POSTMAN_JSON = _FIXTURES / "postman_sample.json"


# ---------------------------------------------------------------------------
# Petstore JSON — full pipeline
# ---------------------------------------------------------------------------

class TestPetstorePipeline:
    def test_spec_file_exists(self):
        assert PETSTORE_JSON.exists(), f"Missing fixture: {PETSTORE_JSON}"

    def test_importer_parses_petstore(self):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        assert report.total_endpoints > 0
        assert not report.parse_errors

    def test_petstore_title(self):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        assert "Petstore" in report.spec_title

    def test_petstore_base_url(self):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        assert "petstore.example.com" in report.base_url

    def test_petstore_get_pets_is_safe(self):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        ep = next((e for e in report.endpoints if e.method == "GET" and e.path == "/pets"), None)
        assert ep is not None
        assert ep.safety_classification == "safe_readonly"

    def test_petstore_head_is_safe(self):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        ep = next((e for e in report.endpoints if e.method == "HEAD"), None)
        assert ep is not None
        assert ep.safety_classification == "safe_readonly"

    def test_petstore_options_is_safe(self):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        ep = next((e for e in report.endpoints if e.method == "OPTIONS"), None)
        assert ep is not None
        assert ep.safety_classification == "safe_readonly"

    def test_petstore_post_requires_approval(self):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        ep = next((e for e in report.endpoints if e.method == "POST" and e.path == "/pets"), None)
        assert ep is not None
        assert ep.safety_classification == "requires_approval"

    def test_petstore_put_requires_approval(self):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        ep = next((e for e in report.endpoints if e.method == "PUT"), None)
        assert ep is not None
        assert ep.safety_classification == "requires_approval"

    def test_petstore_safe_count_gte_2(self):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        assert report.safe_readonly_count >= 2

    def test_petstore_generates_smoke_spec(self):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        content = APITestGenerator().get_smoke_content(report)
        assert "test.describe" in content
        assert "/pets" in content

    def test_petstore_smoke_no_secrets(self):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        content = APITestGenerator().get_smoke_content(report)
        assert "password" not in content.lower()
        assert "api_key" not in content.lower()
        assert "secret" not in content.lower()

    def test_petstore_smoke_no_destructive_methods(self):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        content = APITestGenerator().get_smoke_content(report)
        # No active test() blocks for DELETE
        lines = [ln for ln in content.split("\n") if "test(" in ln and "DELETE" in ln and "//" not in ln]
        assert len(lines) == 0

    def test_petstore_full_pipeline_writes_artifacts(self, tmp_path):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        gen = APITestGenerator()
        gen.generate(report, output_dir=str(tmp_path), write=True)
        assert (tmp_path / "api_smoke.generated.spec.ts").exists()
        assert (tmp_path / "api_schema.generated.spec.ts").exists()
        assert (tmp_path / "api_negative_candidates.md").exists()

    def test_petstore_cicd_github_actions(self):
        config = CICDBuilder().build("demo-petstore", platform="github_actions")
        assert "playwright" in config.workflow_content.lower()
        assert config.auto_pr_creation_allowed is False
        assert config.production_deploy_allowed is False


# ---------------------------------------------------------------------------
# YAML spec
# ---------------------------------------------------------------------------

class TestYAMLSpec:
    def test_yaml_fixture_exists(self):
        assert SAMPLE_YAML.exists(), f"Missing fixture: {SAMPLE_YAML}"

    def test_yaml_parses_successfully(self):
        pytest.importorskip("yaml")
        report = APIContractImporter().analyze("demo", str(SAMPLE_YAML))
        assert report.total_endpoints > 0
        assert not report.parse_errors

    def test_yaml_format_detected(self):
        pytest.importorskip("yaml")
        report = APIContractImporter().analyze("demo", str(SAMPLE_YAML))
        assert report.source_format == "openapi_yaml"

    def test_yaml_title(self):
        pytest.importorskip("yaml")
        report = APIContractImporter().analyze("demo", str(SAMPLE_YAML))
        assert "YAML" in report.spec_title or "yaml" in report.spec_title.lower()

    def test_yaml_get_items_is_safe(self):
        pytest.importorskip("yaml")
        report = APIContractImporter().analyze("demo", str(SAMPLE_YAML))
        ep = next((e for e in report.endpoints if e.method == "GET" and e.path == "/items"), None)
        assert ep is not None
        assert ep.safety_classification == "safe_readonly"

    def test_yaml_patch_requires_approval(self):
        pytest.importorskip("yaml")
        report = APIContractImporter().analyze("demo", str(SAMPLE_YAML))
        ep = next((e for e in report.endpoints if e.method == "PATCH"), None)
        assert ep is not None
        assert ep.safety_classification == "requires_approval"

    def test_yaml_smoke_content_generated(self):
        pytest.importorskip("yaml")
        report = APIContractImporter().analyze("demo", str(SAMPLE_YAML))
        content = APITestGenerator().get_smoke_content(report)
        assert "/items" in content


# ---------------------------------------------------------------------------
# Risky API — classification verification
# ---------------------------------------------------------------------------

class TestRiskyAPIClassification:
    def _report(self):
        return APIContractImporter().analyze("demo", str(RISKY_JSON))

    def test_risky_fixture_exists(self):
        assert RISKY_JSON.exists()

    def test_delete_user_is_blocked(self):
        report = self._report()
        ep = next(
            (e for e in report.endpoints if e.method == "DELETE" and "/users/" in e.path), None
        )
        assert ep is not None
        assert ep.safety_classification == "blocked_by_default"

    def test_admin_delete_is_blocked(self):
        report = self._report()
        ep = next(
            (e for e in report.endpoints if e.method == "DELETE" and "admin" in e.path), None
        )
        assert ep is not None
        assert ep.safety_classification == "blocked_by_default"

    def test_payment_charge_is_blocked(self):
        report = self._report()
        ep = next(
            (e for e in report.endpoints if "charge" in e.path.lower()), None
        )
        assert ep is not None
        assert ep.safety_classification == "blocked_by_default"

    def test_refund_is_blocked(self):
        report = self._report()
        ep = next(
            (e for e in report.endpoints if "refund" in e.path.lower()), None
        )
        assert ep is not None
        assert ep.safety_classification == "blocked_by_default"

    def test_deactivate_is_blocked(self):
        report = self._report()
        ep = next(
            (e for e in report.endpoints if "deactivate" in e.path.lower()), None
        )
        assert ep is not None
        assert ep.safety_classification == "blocked_by_default"

    def test_get_users_is_safe(self):
        report = self._report()
        ep = next(
            (e for e in report.endpoints if e.method == "GET" and e.path == "/users"), None
        )
        assert ep is not None
        assert ep.safety_classification == "safe_readonly"

    def test_get_products_is_safe(self):
        report = self._report()
        ep = next(
            (e for e in report.endpoints if e.method == "GET" and e.path == "/products"), None
        )
        assert ep is not None
        assert ep.safety_classification == "safe_readonly"

    def test_risky_blocked_count_gte_4(self):
        report = self._report()
        assert report.blocked_count >= 4

    def test_risky_smoke_excludes_blocked(self):
        report = self._report()
        content = APITestGenerator().get_smoke_content(report)
        # payment/charge should not appear as an active test
        active_lines = [
            ln for ln in content.split("\n")
            if "test(" in ln and "charge" in ln.lower() and not ln.strip().startswith("//")
        ]
        assert len(active_lines) == 0

    def test_risky_negative_doc_includes_blocked(self):
        report = self._report()
        content = APITestGenerator().get_negative_content(report)
        assert "blocked" in content.lower()


# ---------------------------------------------------------------------------
# Postman collection
# ---------------------------------------------------------------------------

class TestPostmanPipeline:
    def _report(self):
        return APIContractImporter().analyze("demo", str(POSTMAN_JSON))

    def test_postman_fixture_exists(self):
        assert POSTMAN_JSON.exists()

    def test_postman_format_detected(self):
        assert self._report().source_format == "postman_collection"

    def test_postman_health_get_is_safe(self):
        report = self._report()
        ep = next(
            (e for e in report.endpoints if e.method == "GET" and "health" in e.path.lower()), None
        )
        assert ep is not None
        assert ep.safety_classification == "safe_readonly"

    def test_postman_payment_charge_blocked(self):
        report = self._report()
        ep = next(
            (e for e in report.endpoints if "charge" in e.path.lower()), None
        )
        assert ep is not None
        assert ep.safety_classification == "blocked_by_default"

    def test_postman_generates_smoke(self):
        report = self._report()
        content = APITestGenerator().get_smoke_content(report)
        assert "test.describe" in content


# ---------------------------------------------------------------------------
# CI/CD hardening verification
# ---------------------------------------------------------------------------

class TestCICDHardening:
    def test_github_actions_no_password(self):
        config = CICDBuilder().build("demo")
        assert "password:" not in config.workflow_content.lower()

    def test_github_actions_no_api_key(self):
        config = CICDBuilder().build("demo")
        content = config.workflow_content.lower()
        assert "api_key:" not in content

    def test_github_actions_no_deploy_step(self):
        config = CICDBuilder().build("demo")
        assert "deploy" not in config.workflow_content.lower()

    def test_github_actions_no_git_push(self):
        config = CICDBuilder().build("demo")
        assert "git push" not in config.workflow_content

    def test_github_actions_no_gh_pr_create(self):
        config = CICDBuilder().build("demo")
        assert "gh pr create" not in config.workflow_content
        assert "create-pull-request" not in config.workflow_content

    def test_github_actions_uploads_artifacts(self):
        config = CICDBuilder().build("demo")
        assert "upload-artifact" in config.workflow_content

    def test_github_actions_runs_smoke_only(self):
        config = CICDBuilder().build("demo")
        assert "smoke" in config.workflow_content.lower()

    def test_gitlab_no_deploy(self):
        config = CICDBuilder().build("demo", platform="gitlab_ci")
        assert "deploy" not in config.workflow_content.lower()

    def test_gitlab_no_git_push(self):
        config = CICDBuilder().build("demo", platform="gitlab_ci")
        assert "git push" not in config.workflow_content

    def test_cicd_manifest_no_writeback(self):
        builder = CICDBuilder()
        config = builder.build("demo")
        manifest = builder.build_manifest(config)
        assert manifest.client_repo_writeback_allowed is False


# ---------------------------------------------------------------------------
# Artifact JSON validation
# ---------------------------------------------------------------------------

class TestGeneratedArtifactJSON:
    def test_inventory_is_valid_json(self, tmp_path):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        d = report.to_dict()
        # Must round-trip through JSON cleanly
        raw = json.dumps(d)
        loaded = json.loads(raw)
        assert loaded["project_id"] == "demo"

    def test_manifest_json_has_safety_flags(self, tmp_path):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        d = report.to_dict()
        assert d["raw_secrets_allowed"] is False
        assert d["human_review_required"] is True

    def test_generated_manifest_is_valid(self, tmp_path):
        report = APIContractImporter().analyze("demo", str(PETSTORE_JSON))
        gen = APITestGenerator()
        gen_report = gen.generate(report, output_dir=str(tmp_path), write=True)
        # manifest is written by CLI tool, not generate() — verify report dict instead
        d = gen_report.to_dict()
        assert d["executable_without_approval"] is False
        assert d["human_review_required"] is True

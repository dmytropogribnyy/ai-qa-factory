"""Phase 5M tests — CICDBuilder + CICDConfig + CICDManifest safety invariants."""
from __future__ import annotations


from core.cicd_builder import CICDBuilder
from core.schemas.api_contract import CICDConfig, CICDManifest


# ---------------------------------------------------------------------------
# GitHub Actions
# ---------------------------------------------------------------------------

class TestCICDBuilderGitHubActions:
    def test_returns_cicd_config(self):
        builder = CICDBuilder()
        config = builder.build("proj", platform="github_actions")
        assert isinstance(config, CICDConfig)

    def test_platform_set(self):
        config = CICDBuilder().build("proj", platform="github_actions")
        assert config.platform == "github_actions"

    def test_workflow_filename(self):
        config = CICDBuilder().build("proj", platform="github_actions")
        assert config.workflow_filename.endswith(".yml")

    def test_workflow_content_not_empty(self):
        config = CICDBuilder().build("proj", platform="github_actions")
        assert len(config.workflow_content) > 100

    def test_workflow_contains_checkout(self):
        config = CICDBuilder().build("proj", platform="github_actions")
        assert "checkout" in config.workflow_content.lower()

    def test_workflow_contains_playwright(self):
        config = CICDBuilder().build("proj", platform="github_actions")
        assert "playwright" in config.workflow_content.lower()

    def test_workflow_contains_upload_artifact(self):
        config = CICDBuilder().build("proj", platform="github_actions")
        assert "upload-artifact" in config.workflow_content

    def test_scaffold_root_in_workflow(self):
        config = CICDBuilder().build("proj", scaffold_root="my/scaffold")
        assert "my/scaffold" in config.workflow_content

    def test_steps_included_non_empty(self):
        config = CICDBuilder().build("proj", platform="github_actions")
        assert len(config.steps_included) > 0

    def test_project_id_in_workflow(self):
        config = CICDBuilder().build("myproject", platform="github_actions")
        assert "myproject" in config.workflow_content

    def test_no_hardcoded_secrets(self):
        config = CICDBuilder().build("proj", platform="github_actions")
        content = config.workflow_content.lower()
        # Must not contain literal credentials
        assert "password:" not in content
        assert "api_key:" not in content or "# " in config.workflow_content


# ---------------------------------------------------------------------------
# GitLab CI
# ---------------------------------------------------------------------------

class TestCICDBuilderGitLabCI:
    def test_gitlab_platform(self):
        config = CICDBuilder().build("proj", platform="gitlab_ci")
        assert config.platform == "gitlab_ci"

    def test_gitlab_filename(self):
        config = CICDBuilder().build("proj", platform="gitlab_ci")
        assert "gitlab" in config.workflow_filename.lower()

    def test_gitlab_workflow_contains_playwright_image(self):
        config = CICDBuilder().build("proj", platform="gitlab_ci")
        assert "playwright" in config.workflow_content.lower()

    def test_gitlab_steps_present(self):
        config = CICDBuilder().build("proj", platform="gitlab_ci")
        assert len(config.steps_included) > 0


# ---------------------------------------------------------------------------
# Unknown platform
# ---------------------------------------------------------------------------

class TestCICDBuilderUnknownPlatform:
    def test_unknown_platform_returns_config(self):
        config = CICDBuilder().build("proj", platform="azure_devops")
        assert isinstance(config, CICDConfig)

    def test_unknown_platform_has_filename(self):
        config = CICDBuilder().build("proj", platform="azure_devops")
        assert len(config.workflow_filename) > 0


# ---------------------------------------------------------------------------
# CICDConfig safety invariants
# ---------------------------------------------------------------------------

class TestCICDConfigSafetyInvariants:
    def _config(self):
        return CICDBuilder().build("proj")

    def test_auto_pr_creation_allowed_false(self):
        assert self._config().auto_pr_creation_allowed is False

    def test_client_repo_writeback_allowed_false(self):
        assert self._config().client_repo_writeback_allowed is False

    def test_production_deploy_allowed_false(self):
        assert self._config().production_deploy_allowed is False

    def test_human_review_required_true(self):
        assert self._config().human_review_required is True

    def test_client_delivery_allowed_false(self):
        assert self._config().client_delivery_allowed is False

    def test_invariants_survive_from_dict(self):
        config = self._config()
        d = config.to_dict()
        d["auto_pr_creation_allowed"] = True
        d["client_repo_writeback_allowed"] = True
        d["human_review_required"] = False
        c2 = CICDConfig.from_dict(d)
        assert c2.auto_pr_creation_allowed is False
        assert c2.client_repo_writeback_allowed is False
        assert c2.human_review_required is True


# ---------------------------------------------------------------------------
# CICDManifest
# ---------------------------------------------------------------------------

class TestCICDManifest:
    def test_build_manifest_returns_manifest(self):
        builder = CICDBuilder()
        config = builder.build("proj")
        manifest = builder.build_manifest(config)
        assert isinstance(manifest, CICDManifest)

    def test_manifest_has_artifacts(self):
        builder = CICDBuilder()
        config = builder.build("proj")
        manifest = builder.build_manifest(config)
        assert len(manifest.artifacts) > 0

    def test_manifest_auto_pr_false(self):
        builder = CICDBuilder()
        config = builder.build("proj")
        manifest = builder.build_manifest(config)
        assert manifest.auto_pr_creation_allowed is False

    def test_manifest_repo_writeback_false(self):
        builder = CICDBuilder()
        config = builder.build("proj")
        manifest = builder.build_manifest(config)
        assert manifest.client_repo_writeback_allowed is False

    def test_manifest_human_review_true(self):
        builder = CICDBuilder()
        config = builder.build("proj")
        manifest = builder.build_manifest(config)
        assert manifest.human_review_required is True

    def test_manifest_invariants_survive_from_dict(self):
        builder = CICDBuilder()
        config = builder.build("proj")
        manifest = builder.build_manifest(config)
        d = manifest.to_dict()
        d["auto_pr_creation_allowed"] = True
        d["human_review_required"] = False
        m2 = CICDManifest.from_dict(d)
        assert m2.auto_pr_creation_allowed is False
        assert m2.human_review_required is True

    def test_manifest_write(self, tmp_path):
        builder = CICDBuilder()
        config = builder.build("proj")
        builder.build_manifest(config, output_dir=str(tmp_path), write=True)
        assert (tmp_path / "cicd_summary.md").exists()
        assert (tmp_path / "cicd_manifest.json").exists()

    def test_write_creates_workflow_file(self, tmp_path):
        builder = CICDBuilder()
        builder.build("proj", output_dir=str(tmp_path), write=True)
        yml_files = list(tmp_path.glob("*.yml"))
        assert len(yml_files) >= 1

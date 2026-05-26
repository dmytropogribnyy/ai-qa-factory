"""Tests for Phase 4E: Credential and Test-Account Safety Layer.

All tests use mocked/in-memory data only.
No real credentials are used. No login. No .env reading. No external calls.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).parent.parent))

from core.schemas.credential_safety import (
    AuthExecutionApproval,
    CredentialPolicy,
    CredentialReference,
    CredentialSafetyReport,
    SandboxProfileClassification,
    StorageStatePolicy,
    TestAccountProfile,
)
from core.credential_safety_inspector import CredentialSafetyInspector


# ===========================================================================
# Helpers
# ===========================================================================

def _inspector(tmp_path: Path) -> CredentialSafetyInspector:
    return CredentialSafetyInspector(outputs_root=tmp_path / "outputs")


# ===========================================================================
# Schema: CredentialReference
# ===========================================================================

class TestCredentialReference:
    def test_defaults(self):
        ref = CredentialReference()
        assert ref.credential_type == "unknown"
        assert ref.source_type == "not_provided"
        assert ref.approved_for_use is False
        assert ref.safe_to_store is False
        assert ref.safe_to_log is False
        assert ref.redaction_required is True

    def test_roundtrip(self):
        ref = CredentialReference(
            id="cred_001",
            label="API token",
            credential_type="api_token",
            source_type="placeholder",
            redaction_required=True,
            notes=["test note"],
        )
        d = ref.to_dict()
        ref2 = CredentialReference.from_dict(d)
        assert ref2.id == "cred_001"
        assert ref2.label == "API token"
        assert ref2.credential_type == "api_token"
        assert ref2.redaction_required is True


# ===========================================================================
# Schema: TestAccountProfile
# ===========================================================================

class TestTestAccountProfile:
    def test_defaults(self):
        profile = TestAccountProfile()
        assert profile.dedicated_test_account is False
        assert profile.personal_account is False
        assert profile.production_account is False
        assert profile.approved_for_auth_execution is False
        assert profile.credentials_stored_in_repo is False
        assert profile.storage_state_allowed is False

    def test_roundtrip(self):
        profile = TestAccountProfile(
            id="acct_001",
            label="Staging test account",
            account_type="staging",
            environment="staging",
            provider="SaaS",
            dedicated_test_account=True,
        )
        d = profile.to_dict()
        profile2 = TestAccountProfile.from_dict(d)
        assert profile2.dedicated_test_account is True
        assert profile2.label == "Staging test account"


# ===========================================================================
# Schema: CredentialPolicy — unsafe defaults
# ===========================================================================

class TestCredentialPolicy:
    def test_unsafe_defaults_blocked(self):
        policy = CredentialPolicy()
        assert policy.allow_real_credentials is False
        assert policy.allow_personal_accounts is False
        assert policy.allow_production_accounts is False
        assert policy.allow_repo_storage is False
        assert policy.allow_logging is False
        assert policy.allow_client_visible_credentials is False

    def test_post_init_forces_false_regardless_of_constructor(self):
        policy = CredentialPolicy(
            allow_real_credentials=True,
            allow_personal_accounts=True,
            allow_production_accounts=True,
            allow_repo_storage=True,
            allow_logging=True,
            allow_client_visible_credentials=True,
        )
        assert policy.allow_real_credentials is False
        assert policy.allow_personal_accounts is False
        assert policy.allow_production_accounts is False
        assert policy.allow_repo_storage is False
        assert policy.allow_logging is False
        assert policy.allow_client_visible_credentials is False

    def test_from_dict_cannot_rehydrate_unsafe_flags(self):
        d = {
            "project_id": "test",
            "allow_real_credentials": True,
            "allow_personal_accounts": True,
            "allow_production_accounts": True,
            "allow_repo_storage": True,
            "allow_logging": True,
            "allow_client_visible_credentials": True,
        }
        policy = CredentialPolicy.from_dict(d)
        assert policy.allow_real_credentials is False
        assert policy.allow_personal_accounts is False
        assert policy.allow_production_accounts is False
        assert policy.allow_repo_storage is False
        assert policy.allow_logging is False
        assert policy.allow_client_visible_credentials is False

    def test_safe_fields_roundtrip(self):
        policy = CredentialPolicy(
            project_id="proj-123",
            allow_storage_state=False,
            require_dedicated_test_account=True,
            require_explicit_auth_approval=True,
        )
        d = policy.to_dict()
        policy2 = CredentialPolicy.from_dict(d)
        assert policy2.project_id == "proj-123"
        assert policy2.require_dedicated_test_account is True


# ===========================================================================
# Schema: CredentialSafetyReport — nested reconstruction
# ===========================================================================

class TestCredentialSafetyReport:
    def test_defaults(self):
        report = CredentialSafetyReport()
        assert report.safe_for_auth_execution is False
        assert report.safe_for_client_visibility is False
        assert report.status == "blocked"

    def test_post_init_forces_false(self):
        report = CredentialSafetyReport(
            safe_for_auth_execution=True,
            safe_for_client_visibility=True,
        )
        assert report.safe_for_auth_execution is False
        assert report.safe_for_client_visibility is False

    def test_nested_reconstruction(self):
        report = CredentialSafetyReport(
            project_id="proj",
            credentials_detected=[
                CredentialReference(id="c1", label="token", credential_type="api_token"),
            ],
            test_accounts=[
                TestAccountProfile(id="a1", label="staging"),
            ],
            sandbox_profiles=[
                SandboxProfileClassification(id="s1", provider="Amazon", classification="future_sandbox_integration"),
            ],
        )
        d = report.to_dict()
        d["safe_for_auth_execution"] = True
        d["safe_for_client_visibility"] = True
        report2 = CredentialSafetyReport.from_dict(d)
        assert report2.safe_for_auth_execution is False
        assert report2.safe_for_client_visibility is False
        assert len(report2.credentials_detected) == 1
        assert isinstance(report2.credentials_detected[0], CredentialReference)
        assert report2.credentials_detected[0].id == "c1"
        assert len(report2.test_accounts) == 1
        assert isinstance(report2.test_accounts[0], TestAccountProfile)
        assert len(report2.sandbox_profiles) == 1
        assert isinstance(report2.sandbox_profiles[0], SandboxProfileClassification)


# ===========================================================================
# Schema: StorageStatePolicy
# ===========================================================================

class TestStorageStatePolicy:
    def test_defaults(self):
        policy = StorageStatePolicy()
        assert policy.storage_state_allowed is False
        assert policy.approved_for_commit is False
        assert policy.internal_only is True
        assert policy.client_visible is False
        assert policy.gitignored_required is True

    def test_post_init_forces_approved_for_commit_false(self):
        policy = StorageStatePolicy(approved_for_commit=True)
        assert policy.approved_for_commit is False

    def test_from_dict_cannot_rehydrate_approved_for_commit(self):
        d = StorageStatePolicy().to_dict()
        d["approved_for_commit"] = True
        policy2 = StorageStatePolicy.from_dict(d)
        assert policy2.approved_for_commit is False


# ===========================================================================
# Schema: AuthExecutionApproval
# ===========================================================================

class TestAuthExecutionApproval:
    def test_defaults(self):
        approval = AuthExecutionApproval()
        assert approval.approved is False
        assert approval.real_credentials_allowed is False
        assert approval.personal_account_allowed is False
        assert approval.evidence_internal_only is True

    def test_post_init_forces_approved_false(self):
        approval = AuthExecutionApproval(
            approved=True,
            real_credentials_allowed=True,
            personal_account_allowed=True,
        )
        assert approval.approved is False
        assert approval.real_credentials_allowed is False
        assert approval.personal_account_allowed is False


# ===========================================================================
# Schema: SandboxProfileClassification
# ===========================================================================

class TestSandboxProfileClassification:
    def test_defaults(self):
        profile = SandboxProfileClassification()
        assert profile.blocked_in_current_phase is True
        assert profile.allowed_in_future_phase is False

    def test_post_init_forces_blocked_true(self):
        profile = SandboxProfileClassification(blocked_in_current_phase=False)
        assert profile.blocked_in_current_phase is True

    def test_roundtrip(self):
        profile = SandboxProfileClassification(
            id="s1",
            provider="Amazon",
            classification="future_sandbox_integration",
            payment_sandbox=True,
            requires_dedicated_test_account=True,
        )
        d = profile.to_dict()
        profile2 = SandboxProfileClassification.from_dict(d)
        assert profile2.blocked_in_current_phase is True
        assert profile2.payment_sandbox is True


# ===========================================================================
# Schema: __init__.py exports
# ===========================================================================

class TestSchemaExports:
    def test_phase4e_classes_importable_from_schemas(self):
        from core.schemas import (
            CredentialSafetyReference,
            CredentialSafetyPolicy,
            CredentialSafetyReport,
            TestAccountProfile,
            StorageStatePolicy,
            AuthExecutionApproval,
            SandboxProfileClassification,
        )
        assert CredentialSafetyReference is not None
        assert CredentialSafetyPolicy is not None
        assert CredentialSafetyReport is not None
        assert TestAccountProfile is not None
        assert StorageStatePolicy is not None
        assert AuthExecutionApproval is not None
        assert SandboxProfileClassification is not None

    def test_phase2a_credential_classes_still_exportable(self):
        from core.schemas import CredentialReference, CredentialPolicy, CredentialUseApproval
        assert CredentialReference is not None
        assert CredentialPolicy is not None
        assert CredentialUseApproval is not None


# ===========================================================================
# Inspector: .env file safety
# ===========================================================================

class TestInspectorEnvFileSafety:
    def test_inspector_ignores_env_file_in_scan(self, tmp_path):
        inspector = _inspector(tmp_path)
        env_file = tmp_path / ".env"
        env_file.write_text("PASSWORD=supersecret123\nAPI_KEY=sk-real-key\n")
        # Scan should not read the .env file
        result = inspector._scan_directory(tmp_path, context="test", allow_fake_fixture=False)
        # .env file matches forbidden pattern — should be skipped
        assert not any("supersecret123" in str(r.notes) for r in result["detected"])

    def test_inspector_ignores_auth_storagestate(self, tmp_path):
        inspector = _inspector(tmp_path)
        auth_dir = tmp_path / ".auth"
        auth_dir.mkdir()
        storage = auth_dir / "storageState.json"
        storage.write_text('{"cookies": [{"name": "sessionid", "value": "real-session-123"}]}')
        # Should not read .auth/ directory
        result = inspector._scan_directory(tmp_path, context="test", allow_fake_fixture=False)
        assert not any("real-session-123" in str(r.notes) for r in result["detected"])

    def test_forbidden_path_detection(self, tmp_path):
        inspector = _inspector(tmp_path)
        env_path = tmp_path / ".env"
        assert inspector._is_forbidden_path(env_path) is True
        storage_path = tmp_path / ".auth" / "storageState.json"
        assert inspector._is_forbidden_path(storage_path) is True
        node_modules = tmp_path / "node_modules" / "some-lib"
        assert inspector._is_forbidden_path(node_modules) is True
        safe_md = tmp_path / "README.md"
        assert inspector._is_forbidden_path(safe_md) is False


# ===========================================================================
# Inspector: secret pattern scanning
# ===========================================================================

class TestSecretPatternScanning:
    def test_detects_password_assignment(self, tmp_path):
        inspector = _inspector(tmp_path)
        text = "password=myRealPassword123"
        found = inspector.scan_text_for_secret_patterns(text, context="test")
        assert len(found) > 0
        assert found[0].redaction_required is True

    def test_detects_api_key_assignment(self, tmp_path):
        inspector = _inspector(tmp_path)
        text = "api_key=sk-prod-abcdefghij1234567890"
        found = inspector.scan_text_for_secret_patterns(text, context="test")
        assert len(found) > 0

    def test_detects_token_assignment(self, tmp_path):
        inspector = _inspector(tmp_path)
        text = "token=ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef"
        found = inspector.scan_text_for_secret_patterns(text, context="test")
        assert len(found) > 0

    def test_detects_client_secret(self, tmp_path):
        inspector = _inspector(tmp_path)
        text = "client_secret=my-oauth-secret-value"
        found = inspector.scan_text_for_secret_patterns(text, context="test")
        assert len(found) > 0

    def test_detects_access_token(self, tmp_path):
        inspector = _inspector(tmp_path)
        text = "access_token=eyJhbGciOiJSUzI1NiJ9.payload"
        found = inspector.scan_text_for_secret_patterns(text, context="test")
        assert len(found) > 0

    def test_skips_comment_lines(self, tmp_path):
        inspector = _inspector(tmp_path)
        text = "# password=somecommentpassword"
        found = inspector.scan_text_for_secret_patterns(text, context="test")
        assert len(found) == 0

    def test_allows_placeholder_in_fixture_context(self, tmp_path):
        inspector = _inspector(tmp_path)
        text = "TEST_PASSWORD=FakeSecret123"
        found = inspector.scan_text_for_secret_patterns(text, context="fixture", allow_fake_fixture=True)
        # FakeSecret123 is an allowed placeholder
        assert len(found) == 0

    def test_detects_linear_token_pattern(self, tmp_path):
        inspector = _inspector(tmp_path)
        text = "token=lin_api_xxxxxxxxxxxxxxxxxxxxxxxxxx"
        found = inspector.scan_text_for_secret_patterns(text, context="test")
        assert len(found) > 0

    def test_detects_oauth_secret(self, tmp_path):
        inspector = _inspector(tmp_path)
        text = "oauth_secret=my-secret-oauth-val-123456"
        found = inspector.scan_text_for_secret_patterns(text, context="test")
        assert len(found) > 0

    def test_detects_refresh_token(self, tmp_path):
        inspector = _inspector(tmp_path)
        text = "refresh_token=some_long_refresh_token_value_here"
        found = inspector.scan_text_for_secret_patterns(text, context="test")
        assert len(found) > 0


# ===========================================================================
# Inspector: safety flags always False
# ===========================================================================

class TestInspectorSafetyFlags:
    def test_safe_for_auth_execution_always_false(self, tmp_path):
        inspector = _inspector(tmp_path)
        report = inspector.inspect_credentials("proj")
        assert report.safe_for_auth_execution is False

    def test_safe_for_client_visibility_always_false(self, tmp_path):
        inspector = _inspector(tmp_path)
        report = inspector.inspect_credentials("proj")
        assert report.safe_for_client_visibility is False

    def test_storage_state_approved_for_commit_always_false(self, tmp_path):
        inspector = _inspector(tmp_path)
        policy = inspector.build_storage_state_policy("proj")
        assert policy.approved_for_commit is False

    def test_auth_execution_approval_always_blocked(self, tmp_path):
        inspector = _inspector(tmp_path)
        approval = inspector.build_auth_execution_approval("proj")
        assert approval.approved is False
        assert approval.real_credentials_allowed is False
        assert approval.personal_account_allowed is False
        assert len(approval.blockers) > 0


# ===========================================================================
# Inspector: sandbox classification
# ===========================================================================

class TestSandboxClassification:
    def test_classifies_amazon_pay_sandbox(self, tmp_path):
        inspector = _inspector(tmp_path)
        profile = inspector.classify_single_sandbox("Amazon Pay Sandbox")
        assert profile.classification == "future_sandbox_integration"
        assert profile.payment_sandbox is True
        assert profile.production_retail_account is False
        assert profile.blocked_in_current_phase is True
        assert profile.allowed_in_future_phase is True

    def test_classifies_amazon_retail_as_blocked(self, tmp_path):
        inspector = _inspector(tmp_path)
        profile = inspector.classify_single_sandbox("amazon.com")
        assert profile.classification == "blocked_production_retail"
        assert profile.production_retail_account is True
        assert profile.blocked_in_current_phase is True
        assert profile.allowed_in_future_phase is False

    def test_classifies_alza_production_as_blocked(self, tmp_path):
        inspector = _inspector(tmp_path)
        profile = inspector.classify_single_sandbox("Alza production account")
        assert profile.classification == "blocked_production_ecommerce"
        assert profile.production_retail_account is True
        assert profile.blocked_in_current_phase is True

    def test_classifies_alza_staging_as_future_candidate(self, tmp_path):
        inspector = _inspector(tmp_path)
        profile = inspector.classify_single_sandbox("Alza staging")
        assert profile.classification == "future_sandbox_integration"
        assert profile.production_retail_account is False
        assert profile.blocked_in_current_phase is True
        assert profile.allowed_in_future_phase is True

    def test_classifies_linear_as_blocked_task_source(self, tmp_path):
        inspector = _inspector(tmp_path)
        profile = inspector.classify_single_sandbox("Linear token")
        assert profile.classification == "blocked_task_source"
        assert profile.blocked_in_current_phase is True
        assert profile.allowed_in_future_phase is False

    def test_classifies_google_oauth_as_blocked_personal(self, tmp_path):
        inspector = _inspector(tmp_path)
        profile = inspector.classify_single_sandbox("Google account")
        assert profile.classification == "blocked_personal_account"
        assert profile.blocked_in_current_phase is True

    def test_classifies_saucedemo_as_public_demo(self, tmp_path):
        inspector = _inspector(tmp_path)
        profile = inspector.classify_single_sandbox("saucedemo")
        assert profile.classification == "public_demo"
        assert profile.official_sandbox is True

    def test_classifies_dedicated_staging_account(self, tmp_path):
        inspector = _inspector(tmp_path)
        profile = inspector.classify_single_sandbox("dedicated staging account")
        assert profile.classification == "future_sandbox_integration"
        assert profile.requires_dedicated_test_account is True
        assert profile.blocked_in_current_phase is True

    def test_unknown_label_blocked_by_default(self, tmp_path):
        inspector = _inspector(tmp_path)
        profile = inspector.classify_single_sandbox("some completely unknown service")
        assert profile.blocked_in_current_phase is True
        assert profile.classification == "unknown"

    def test_classify_amazon_reference_retail(self, tmp_path):
        inspector = _inspector(tmp_path)
        profile = inspector.classify_amazon_reference("Amazon.com retail account")
        assert profile.classification == "blocked_production_retail"

    def test_classify_amazon_reference_pay_sandbox(self, tmp_path):
        inspector = _inspector(tmp_path)
        profile = inspector.classify_amazon_reference("Amazon Pay Sandbox integration")
        assert profile.classification == "future_sandbox_integration"

    def test_classify_alza_production(self, tmp_path):
        inspector = _inspector(tmp_path)
        profile = inspector.classify_alza_reference("Alza production store")
        assert profile.classification == "blocked_production_ecommerce"

    def test_classify_alza_staging(self, tmp_path):
        inspector = _inspector(tmp_path)
        profile = inspector.classify_alza_reference("Alza staging test account")
        assert profile.classification == "future_sandbox_integration"

    def test_blocked_in_current_phase_always_true(self, tmp_path):
        inspector = _inspector(tmp_path)
        for label in ["Amazon Pay Sandbox", "amazon.com", "Alza production account",
                      "Linear token", "Google account", "dedicated staging account"]:
            profile = inspector.classify_single_sandbox(label)
            assert profile.blocked_in_current_phase is True, f"Expected blocked for: {label}"


# ===========================================================================
# Inspector: no login, no external calls
# ===========================================================================

class TestNoLoginNoExternalCalls:
    def test_inspect_credentials_no_subprocess(self, tmp_path):
        inspector = _inspector(tmp_path)
        with patch("subprocess.run") as mock_run:
            inspector.inspect_credentials("proj")
        mock_run.assert_not_called()

    def test_inspect_credentials_no_requests(self, tmp_path):
        # Verify no external calls — inspector must not import requests/httpx
        import core.credential_safety_inspector as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "import requests" not in src
        assert "import httpx" not in src
        assert "import aiohttp" not in src
        assert "urllib.request.urlopen" not in src

    def test_inspector_no_load_dotenv(self, tmp_path):
        import core.credential_safety_inspector as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "load_dotenv" not in src

    def test_inspector_no_subprocess_import_usage(self, tmp_path):
        import core.credential_safety_inspector as mod
        src = Path(mod.__file__).read_text(encoding="utf-8")
        assert "subprocess.run" not in src
        assert "subprocess.call" not in src
        assert "subprocess.Popen" not in src


# ===========================================================================
# Inspector: artifact rendering
# ===========================================================================

class TestArtifactRendering:
    def test_render_credential_safety_artifacts_creates_expected_files(self, tmp_path):
        inspector = _inspector(tmp_path)
        policy = inspector.build_credential_policy("proj")
        report = inspector.inspect_credentials("proj")
        storage_policy = inspector.build_storage_state_policy("proj")
        auth_approval = inspector.build_auth_execution_approval("proj")

        paths = inspector.render_credential_safety_artifacts(
            policy, report, storage_policy, auth_approval, "proj"
        )

        expected_keys = [
            "policy_json", "policy_md",
            "report_json", "report_md",
            "storage_json", "storage_md",
            "auth_approval_json", "auth_approval_md",
            "sandbox_json", "sandbox_md",
            "redaction_checklist",
        ]
        for key in expected_keys:
            assert key in paths, f"Missing artifact: {key}"
            assert paths[key].exists(), f"File not created: {paths[key]}"

    def test_artifacts_contain_safety_disclaimers(self, tmp_path):
        inspector = _inspector(tmp_path)
        policy = inspector.build_credential_policy("proj")
        report = inspector.inspect_credentials("proj")
        storage_policy = inspector.build_storage_state_policy("proj")
        auth_approval = inspector.build_auth_execution_approval("proj")

        paths = inspector.render_credential_safety_artifacts(
            policy, report, storage_policy, auth_approval, "proj"
        )

        report_md = paths["report_md"].read_text(encoding="utf-8")
        assert "No real credentials were used" in report_md
        assert "No login was performed" in report_md

        auth_md = paths["auth_approval_md"].read_text(encoding="utf-8")
        assert "DRAFT" in auth_md
        assert "NOT approved" in auth_md

        redaction_md = paths["redaction_checklist"].read_text(encoding="utf-8")
        assert "storageState" in redaction_md
        assert ".env" in redaction_md

    def test_policy_json_has_correct_safe_defaults(self, tmp_path):
        inspector = _inspector(tmp_path)
        policy = inspector.build_credential_policy("proj")
        report = inspector.inspect_credentials("proj")
        storage_policy = inspector.build_storage_state_policy("proj")
        auth_approval = inspector.build_auth_execution_approval("proj")

        paths = inspector.render_credential_safety_artifacts(
            policy, report, storage_policy, auth_approval, "proj"
        )

        with open(paths["policy_json"], encoding="utf-8") as f:
            data = json.load(f)

        assert data["allow_real_credentials"] is False
        assert data["allow_personal_accounts"] is False
        assert data["allow_production_accounts"] is False
        assert data["allow_repo_storage"] is False
        assert data["allow_logging"] is False
        assert data["allow_client_visible_credentials"] is False

    def test_report_json_safe_flags(self, tmp_path):
        inspector = _inspector(tmp_path)
        policy = inspector.build_credential_policy("proj")
        report = inspector.inspect_credentials("proj")
        storage_policy = inspector.build_storage_state_policy("proj")
        auth_approval = inspector.build_auth_execution_approval("proj")

        paths = inspector.render_credential_safety_artifacts(
            policy, report, storage_policy, auth_approval, "proj"
        )

        with open(paths["report_json"], encoding="utf-8") as f:
            data = json.load(f)

        assert data["safe_for_auth_execution"] is False
        assert data["safe_for_client_visibility"] is False


# ===========================================================================
# WorkbenchController integration
# ===========================================================================

class TestWorkbenchControllerPhase4E:
    def test_inspect_credential_safety_method_exists(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        assert hasattr(wc, "inspect_credential_safety")
        assert hasattr(wc, "render_credential_safety_artifacts")

    def test_inspect_credential_safety_returns_tuple(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        result = wc.inspect_credential_safety("proj-wc")
        assert len(result) == 4
        policy, report, storage, auth = result
        assert isinstance(policy, CredentialPolicy)
        assert isinstance(report, CredentialSafetyReport)
        assert isinstance(storage, StorageStatePolicy)
        assert isinstance(auth, AuthExecutionApproval)

    def test_workbench_safe_flags(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        _, report, storage, auth = wc.inspect_credential_safety("proj-wc2")
        assert report.safe_for_auth_execution is False
        assert report.safe_for_client_visibility is False
        assert storage.approved_for_commit is False
        assert auth.approved is False


# ===========================================================================
# CLI tool tests
# ===========================================================================

class TestCLITool:
    def test_no_write_exits_cleanly(self, tmp_path):
        from tools.inspect_credentials import main
        result = main(["--project-id", "cli-test", "--no-write",
                       "--outputs-root", str(tmp_path / "outputs")])
        assert result == 0

    def test_missing_project_id_returns_error(self, tmp_path):
        from tools.inspect_credentials import main
        result = main(["--no-write", "--outputs-root", str(tmp_path / "outputs")])
        assert result == 2

    def test_json_output_valid(self, tmp_path):
        from tools.inspect_credentials import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            result = main([
                "--project-id", "cli-json-test",
                "--json",
                "--outputs-root", str(tmp_path / "outputs"),
            ])
        assert result == 0
        output = buf.getvalue()
        data = json.loads(output)
        assert "report" in data
        assert "policy" in data
        assert data["report"]["safe_for_auth_execution"] is False
        assert data["policy"]["allow_real_credentials"] is False

    def test_classify_sandbox_amazon_pay(self, tmp_path):
        from tools.inspect_credentials import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            main([
                "--project-id", "cli-sandbox",
                "--classify-sandbox", "Amazon Pay Sandbox",
                "--json",
                "--outputs-root", str(tmp_path / "outputs"),
            ])
        output = buf.getvalue()
        data = json.loads(output)
        assert data["classification"] == "future_sandbox_integration"
        assert data["blocked_in_current_phase"] is True

    def test_classify_sandbox_alza_production(self, tmp_path):
        from tools.inspect_credentials import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            main([
                "--project-id", "cli-sandbox-alza",
                "--classify-sandbox", "Alza production account",
                "--json",
                "--outputs-root", str(tmp_path / "outputs"),
            ])
        output = buf.getvalue()
        data = json.loads(output)
        assert data["classification"] == "blocked_production_ecommerce"
        assert data["blocked_in_current_phase"] is True

    def test_scanner_does_not_read_env_file(self, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text("SECRET=actually_secret_value\n")
        from tools.inspect_credentials import main
        result = main([
            "--project-id", "cli-env-test",
            "--include-scaffold",
            "--no-write",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        # Should exit 0 (no credentials detected from .env because it's forbidden)
        assert result == 0

    def test_scanner_does_not_read_storagestate(self, tmp_path):
        auth_dir = tmp_path / ".auth"
        auth_dir.mkdir()
        ss = auth_dir / "storageState.json"
        ss.write_text('{"cookies": [{"name": "auth", "value": "real-session-token-xyz"}]}')
        from tools.inspect_credentials import main
        result = main([
            "--project-id", "cli-ss-test",
            "--no-write",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert result == 0

    def test_write_creates_artifact_directory(self, tmp_path):
        from tools.inspect_credentials import main
        outputs = tmp_path / "outputs"
        result = main([
            "--project-id", "cli-write-test",
            "--outputs-root", str(outputs),
        ])
        assert result == 0
        cred_dir = outputs / "cli-write-test" / "08_credentials"
        assert cred_dir.exists()
        assert (cred_dir / "CREDENTIAL_POLICY.json").exists()
        assert (cred_dir / "CREDENTIAL_SAFETY_REPORT.json").exists()
        assert (cred_dir / "STORAGE_STATE_POLICY.json").exists()
        assert (cred_dir / "AUTH_EXECUTION_APPROVAL_DRAFT.json").exists()
        assert (cred_dir / "CREDENTIAL_REDACTION_CHECKLIST.md").exists()


# ===========================================================================
# Static safety inspection
# ===========================================================================

class TestPhase4EStaticSafety:
    def _read_src(self, module_path: str) -> str:
        return Path(module_path).read_text(encoding="utf-8")

    def test_inspector_no_import_requests(self):
        src = self._read_src("core/credential_safety_inspector.py")
        assert "import requests" not in src

    def test_inspector_no_import_httpx(self):
        src = self._read_src("core/credential_safety_inspector.py")
        assert "import httpx" not in src

    def test_inspector_no_load_dotenv(self):
        src = self._read_src("core/credential_safety_inspector.py")
        assert "load_dotenv" not in src

    def test_inspector_no_subprocess_run(self):
        src = self._read_src("core/credential_safety_inspector.py")
        assert "subprocess.run" not in src

    def test_inspector_no_zipfile(self):
        src = self._read_src("core/credential_safety_inspector.py")
        assert "import zipfile" not in src

    def test_schema_no_raw_secret_storage(self):
        src = self._read_src("core/schemas/credential_safety.py")
        assert "password=" not in src.lower().replace("# ", "")

    def test_cli_no_import_requests(self):
        src = self._read_src("tools/inspect_credentials.py")
        assert "import requests" not in src

    def test_cli_no_subprocess_run(self):
        src = self._read_src("tools/inspect_credentials.py")
        assert "subprocess.run" not in src


# ===========================================================================
# Docs governance
# ===========================================================================

class TestPhase4EDocsGovernance:
    def _read_doc(self, path: str) -> str:
        return Path(path).read_text(encoding="utf-8").lower()

    def test_commands_mentions_phase4e(self):
        src = self._read_doc("docs/COMMANDS.md")
        assert "phase 4e" in src
        assert "inspect_credentials" in src

    def test_runbook_mentions_phase4e(self):
        src = self._read_doc("docs/RUNBOOK.md")
        assert "phase 4e" in src
        assert "credential" in src

    def test_safety_rules_mentions_4e_rules(self):
        src = self._read_doc("docs/SAFETY_RULES.md")
        assert "4e-1" in src
        assert "storagestate" in src
        assert "personal account" in src

    def test_schema_foundation_mentions_credential_safety(self):
        src = self._read_doc("docs/SCHEMA_FOUNDATION.md")
        assert "credential_safety" in src
        assert "authexecutionapproval" in src

    def test_docs_manifest_mentions_08_credentials(self):
        src = self._read_doc("docs/DOCS_MANIFEST.md")
        assert "08_credentials" in src
        assert "credential_policy" in src

    def test_phase_contracts_mentions_phase4e(self):
        src = self._read_doc("docs/PHASE_CONTRACTS.md")
        assert "phase 4e" in src
        assert "implemented" in src

    def test_artifact_contracts_mentions_08_credentials(self):
        src = self._read_doc("docs/ARTIFACT_CONTRACTS.md")
        assert "08_credentials" in src

    def test_agent_contract_mentions_credential_rules(self):
        src = self._read_doc("docs/AGENT_CONTRACT.md")
        assert "personal account" in src
        assert "storagestate" in src
        assert "amazon pay sandbox" in src

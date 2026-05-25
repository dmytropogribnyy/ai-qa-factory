"""Phase 2A classification tests.

Covers:
- InputContextResolver: URL classification, file classification, text classification
- Secret redaction (passwords, tokens, cookies, API keys)
- WorkRequestClassifier: task type, project type, domain, signals
- WorkbenchController: analyze_inputs (no write), build_initial_context (writes artifacts)
- classify-only guarantees: no URL fetch, no browser, no external calls
- Blocked-type detection in next_safe_step
- No raw secrets stored in any output artifact
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from core.input_context_resolver import InputContextResolver, _redact_secrets
from core.schemas.input_map import InputSource
from core.work_request_classifier import WorkRequestClassifier
from core.workbench_controller import WorkbenchController


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_resolver() -> InputContextResolver:
    return InputContextResolver()


def _make_classifier() -> WorkRequestClassifier:
    return WorkRequestClassifier()


def _make_controller(tmp_path: Path) -> WorkbenchController:
    return WorkbenchController(outputs_root=tmp_path)


# ---------------------------------------------------------------------------
# Secret redaction unit tests
# ---------------------------------------------------------------------------

class TestSecretRedaction:
    def test_redacts_password_equals(self):
        text = "Login with password=SuperSecret123"
        redacted, found = _redact_secrets(text)
        assert found is True
        assert "SuperSecret123" not in redacted
        assert "[REDACTED_PASSWORD]" in redacted

    def test_redacts_password_colon(self):
        redacted, found = _redact_secrets("pass: mysecret")
        assert found is True
        assert "mysecret" not in redacted

    def test_redacts_api_key(self):
        redacted, found = _redact_secrets("api_key=abc123xyz")
        assert found is True
        assert "abc123xyz" not in redacted
        assert "[REDACTED_TOKEN]" in redacted

    def test_redacts_bearer_token(self):
        redacted, found = _redact_secrets("Authorization: Bearer eyJhbGciOiJSUzI1NiJ9xyz")
        assert found is True
        assert "eyJhbGciOiJSUzI1NiJ9xyz" not in redacted

    def test_redacts_openai_key(self):
        redacted, found = _redact_secrets("key is sk-abcdefghijklmnopqrstuvwx")
        assert found is True
        assert "sk-abcdefghijklmnopqrstuvwx" not in redacted

    def test_redacts_cookie(self):
        redacted, found = _redact_secrets("cookie=session_value_here")
        assert found is True
        assert "session_value_here" not in redacted
        assert "[REDACTED_COOKIE]" in redacted

    def test_redacts_client_secret(self):
        redacted, found = _redact_secrets("client_secret=my_oauth_secret")
        assert found is True
        assert "my_oauth_secret" not in redacted
        assert "[REDACTED_SECRET]" in redacted

    def test_clean_text_not_flagged(self):
        text = "Need Playwright tests for a SaaS dashboard"
        _, found = _redact_secrets(text)
        assert found is False

    def test_multiple_secrets_all_redacted(self):
        text = "username=admin password=secret123 api_key=xyz789"
        redacted, found = _redact_secrets(text)
        assert found is True
        assert "secret123" not in redacted
        assert "xyz789" not in redacted

    def test_redacts_jwt(self):
        jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
        redacted, found = _redact_secrets(jwt)
        assert found is True
        assert "SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c" not in redacted

    def test_redacts_basic_auth_url(self):
        url = "https://user:mypassword@api.example.com/data"
        redacted, found = _redact_secrets(url)
        assert found is True
        assert "mypassword" not in redacted
        assert "[REDACTED_URL_WITH_CREDENTIALS]" in redacted


# ---------------------------------------------------------------------------
# InputContextResolver — URL classification
# ---------------------------------------------------------------------------

class TestInputContextResolverURLs:
    def setup_method(self):
        self.resolver = _make_resolver()

    def _resolve_one(self, raw: str) -> InputSource:
        im = self.resolver.resolve([raw], "test-proj")
        assert len(im.sources) == 1
        return im.sources[0]

    def test_jira_url_is_task_url(self):
        src = self._resolve_one("https://mycompany.atlassian.net/browse/PROJ-123")
        assert src.input_type == "task_url"

    def test_linear_url_is_task_url(self):
        src = self._resolve_one("https://linear.app/myteam/issue/TEAM-42")
        assert src.input_type == "task_url"

    def test_github_issue_is_task_url(self):
        src = self._resolve_one("https://github.com/org/repo/issues/5")
        assert src.input_type == "task_url"

    def test_github_repo_is_repo_url(self):
        src = self._resolve_one("https://github.com/org/my-repo")
        assert src.input_type == "repo_url"

    def test_gitlab_repo_is_repo_url(self):
        src = self._resolve_one("https://gitlab.com/mygroup/myrepo")
        assert src.input_type == "repo_url"

    def test_swagger_url_is_api_docs(self):
        src = self._resolve_one("https://petstore.swagger.io/v2/swagger.json")
        assert src.input_type == "api_docs_url"

    def test_figma_url_is_design(self):
        src = self._resolve_one("https://www.figma.com/file/abc123/MyDesign")
        assert src.input_type == "design_url"

    def test_generic_app_url_is_target(self):
        src = self._resolve_one("https://app.example.com/dashboard")
        assert src.input_type == "target_url"

    def test_target_url_not_approved(self):
        src = self._resolve_one("https://app.example.com")
        assert src.approved is False

    def test_target_url_has_execution_blocked_note(self):
        src = self._resolve_one("https://app.example.com")
        assert "blocked" in src.classification_notes.lower() or "approval" in src.classification_notes.lower()

    def test_url_with_password_becomes_credentials_ref(self):
        src = self._resolve_one("https://api.example.com login password=MySecret99")
        assert src.input_type == "credentials_reference"
        assert "MySecret99" not in src.raw_value
        assert "[REDACTED_PASSWORD]" in src.raw_value


# ---------------------------------------------------------------------------
# InputContextResolver — file classification
# ---------------------------------------------------------------------------

class TestInputContextResolverFiles:
    def setup_method(self):
        self.resolver = _make_resolver()

    def _resolve_one(self, raw: str) -> InputSource:
        im = self.resolver.resolve([raw], "test-proj")
        return im.sources[0]

    def test_png_is_screenshot(self):
        src = self._resolve_one("C:\\Users\\test\\screenshot.png")
        assert src.input_type == "screenshot"

    def test_zip_is_archive(self):
        src = self._resolve_one("/home/user/project.zip")
        assert src.input_type == "uploaded_archive"

    def test_spec_ts_is_test_file(self):
        src = self._resolve_one("./tests/smoke.spec.ts")
        assert src.input_type == "test_file"

    def test_yaml_is_api_docs(self):
        src = self._resolve_one("openapi.yaml")
        assert src.input_type == "api_docs_file"


# ---------------------------------------------------------------------------
# InputContextResolver — text / brief classification
# ---------------------------------------------------------------------------

class TestInputContextResolverText:
    def setup_method(self):
        self.resolver = _make_resolver()

    def _resolve_one(self, raw: str) -> InputSource:
        im = self.resolver.resolve([raw], "test-proj")
        return im.sources[0]

    def test_plain_brief_is_pasted_brief(self):
        src = self._resolve_one("Need Playwright tests for a SaaS dashboard")
        assert src.input_type == "pasted_brief"

    def test_brief_with_secret_is_credentials_ref(self):
        src = self._resolve_one(
            "Need login test. username=test@example.com password=FakeSecret123"
        )
        assert src.input_type == "credentials_reference"
        assert "FakeSecret123" not in src.raw_value
        assert "[REDACTED_PASSWORD]" in src.raw_value

    def test_credentials_ref_note_present(self):
        src = self._resolve_one("token=abcdef123456 use it for auth")
        assert "credential" in src.classification_notes.lower()
        assert "No credential use performed" in src.classification_notes

    def test_label_truncated_to_reasonable_length(self):
        long_text = "A" * 200
        src = self._resolve_one(long_text)
        assert len(src.label) < 150

    def test_multiple_inputs_resolved(self):
        im = self.resolver.resolve([
            "https://app.example.com",
            "Need Playwright tests",
            "https://github.com/org/repo",
        ], "multi-proj")
        assert len(im.sources) == 3
        types = {s.input_type for s in im.sources}
        assert "target_url" in types
        assert "pasted_brief" in types
        assert "repo_url" in types


# ---------------------------------------------------------------------------
# WorkRequestClassifier
# ---------------------------------------------------------------------------

class TestWorkRequestClassifier:
    def setup_method(self):
        self.classifier = _make_classifier()
        self.resolver = _make_resolver()

    def _classify(self, text: str, inputs: list[str] | None = None) -> tuple:
        if inputs is None:
            inputs = [text]
        im = self.resolver.resolve(inputs, "cls-proj")
        return self.classifier.classify(text, im)

    def test_playwright_brief_is_qa_automation(self):
        wr, tc = self._classify("Need Playwright e2e test automation for SaaS dashboard")
        assert tc.task_type == "qa_automation"

    def test_api_brief_is_api_testing(self):
        wr, tc = self._classify("Write API tests for REST endpoints using Postman/OpenAPI")
        assert tc.task_type == "api_testing"

    def test_upwork_proposal_domain(self):
        wr, tc = self._classify(
            "Write an upwork proposal for a Playwright automation freelance job"
        )
        assert "upwork" in tc.notes or "proposal" in tc.task_type or "upwork" in tc.signals

    def test_saas_project_type_detected(self):
        wr, tc = self._classify(
            "Automate tests for a multi-tenant SaaS with billing and subscriptions"
        )
        assert tc.project_type == "web_saas"

    def test_ecommerce_project_type(self):
        wr, tc = self._classify("Test checkout and cart flow for ecommerce shop")
        assert tc.project_type == "ecommerce"

    def test_confidence_is_between_0_and_1(self):
        _, tc = self._classify("Need tests for a web app")
        assert 0.0 <= tc.confidence <= 1.0

    def test_signals_list_populated(self):
        _, tc = self._classify("Write Playwright automation for SaaS login")
        assert len(tc.signals) > 0

    def test_classified_at_is_set(self):
        _, tc = self._classify("Brief text")
        assert tc.classified_at != ""

    def test_work_request_has_project_id(self):
        wr, _ = self._classify("Brief text")
        assert wr.project_id == "cls-proj"

    def test_target_urls_extracted_from_input_map(self):
        im = self.resolver.resolve(
            ["https://app.example.com", "Need Playwright tests"], "url-proj"
        )
        wr, _ = self.classifier.classify("Need Playwright tests", im)
        assert "https://app.example.com" in wr.target_urls

    def test_mobile_signal_detected(self):
        _, tc = self._classify("Write mobile testing strategy for iOS app with Appium")
        assert "mobile_detected" in tc.signals

    def test_security_signal_detected(self):
        _, tc = self._classify("Security pentest and OWASP vulnerability checks needed")
        assert "security_detected" in tc.signals

    def test_credentials_reference_forces_high_risk(self):
        im = self.resolver.resolve(["password=Secret123 login test"], "cred-risk")
        _, tc = self.classifier.classify("login test", im)
        assert "high_risk" in tc.notes or "high_risk" == tc.notes.split("complexity:")[-1].strip()

    def test_multiline_text_not_classified_as_file(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        result = ctrl.analyze_inputs(
            ["python-dotenv>=1.0.1\nlitellm>=1.60.0\ntenacity>=8.0.0"],
            project_id="multiline-test",
        )
        src = result["input_map"].sources[0]
        assert src.input_type == "pasted_brief"


# ---------------------------------------------------------------------------
# WorkbenchController — analyze_inputs (no write)
# ---------------------------------------------------------------------------

class TestWorkbenchControllerAnalyze:
    def test_returns_all_required_keys(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        result = ctrl.analyze_inputs(
            raw_inputs=["Need Playwright tests for a SaaS dashboard"],
            project_id="test-analyze",
        )
        assert "project_id" in result
        assert "input_map" in result
        assert "work_request" in result
        assert "task_classification" in result
        assert "project_status" in result
        assert "next_safe_step" in result

    def test_project_id_propagated(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        result = ctrl.analyze_inputs(["brief"], project_id="my-pid")
        assert result["project_id"] == "my-pid"

    def test_auto_project_id_generated(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        result = ctrl.analyze_inputs(["brief"])
        assert result["project_id"] != ""

    def test_next_step_blocked_for_credentials(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        result = ctrl.analyze_inputs(
            ["password=Secret123 need login test"],
            project_id="cred-test",
        )
        assert "BLOCKED" in result["next_safe_step"]

    def test_next_step_review_for_target_url(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        result = ctrl.analyze_inputs(
            ["https://app.example.com"],
            project_id="url-test",
        )
        assert "REVIEW REQUIRED" in result["next_safe_step"] or "approval" in result["next_safe_step"].lower()

    def test_no_files_written_when_analyze_only(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        ctrl.analyze_inputs(["brief text"], project_id="no-write")
        project_dir = tmp_path / "no-write"
        assert not project_dir.exists()


# ---------------------------------------------------------------------------
# WorkbenchController — build_initial_context (writes artifacts)
# ---------------------------------------------------------------------------

class TestWorkbenchControllerBuildContext:
    def test_writes_all_expected_files(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        ctrl.build_initial_context(
            raw_inputs=["Need Playwright automation for SaaS dashboard"],
            project_id="write-test",
        )
        out_dir = tmp_path / "write-test" / "00_project"
        assert (out_dir / "INPUT_MAP.json").exists()
        assert (out_dir / "INPUT_MAP.md").exists()
        assert (out_dir / "WORK_REQUEST.json").exists()
        assert (out_dir / "WORK_REQUEST.md").exists()
        assert (out_dir / "TASK_CLASSIFICATION.json").exists()
        assert (out_dir / "TASK_CLASSIFICATION.md").exists()
        assert (out_dir / "PROJECT_STATUS.json").exists()
        assert (out_dir / "PROJECT_STATUS.md").exists()
        assert (out_dir / "NEXT_SAFE_STEP.md").exists()

    def test_json_artifacts_are_valid_json(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        ctrl.build_initial_context(["Brief for a SaaS app"], project_id="json-test")
        out_dir = tmp_path / "json-test" / "00_project"
        for fname in ["INPUT_MAP.json", "WORK_REQUEST.json",
                      "TASK_CLASSIFICATION.json", "PROJECT_STATUS.json"]:
            data = json.loads((out_dir / fname).read_text(encoding="utf-8"))
            assert isinstance(data, dict)

    def test_secrets_not_in_artifacts(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        ctrl.build_initial_context(
            raw_inputs=["Need login test. password=FakeSecret123"],
            project_id="secret-test",
        )
        out_dir = tmp_path / "secret-test" / "00_project"
        for fpath in out_dir.iterdir():
            content = fpath.read_text(encoding="utf-8")
            assert "FakeSecret123" not in content, f"Secret found in {fpath.name}"

    def test_redaction_notice_in_artifacts(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        ctrl.build_initial_context(
            raw_inputs=["password=MySecret456 run login test"],
            project_id="redact-notice",
        )
        input_map_json = (
            tmp_path / "redact-notice" / "00_project" / "INPUT_MAP.json"
        ).read_text(encoding="utf-8")
        # The classification_notes or raw_value should mention redaction
        assert "REDACTED" in input_map_json or "redacted" in input_map_json.lower()

    def test_artifact_paths_returned(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        result = ctrl.build_initial_context(["brief"], project_id="paths-test")
        assert "artifact_paths" in result
        assert len(result["artifact_paths"]) > 0

    def test_project_status_phase_is_intake(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        result = ctrl.build_initial_context(["brief"], project_id="status-test")
        ps = result["project_status"]
        assert ps.phase == "intake"

    def test_input_map_project_id_matches(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        result = ctrl.build_initial_context(["brief"], project_id="pid-test")
        assert result["input_map"].project_id == "pid-test"

    def test_md_artifacts_not_empty(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        ctrl.build_initial_context(["Playwright tests for SaaS"], project_id="md-test")
        out_dir = tmp_path / "md-test" / "00_project"
        for fname in ["INPUT_MAP.md", "WORK_REQUEST.md",
                      "TASK_CLASSIFICATION.md", "NEXT_SAFE_STEP.md"]:
            content = (out_dir / fname).read_text(encoding="utf-8")
            assert len(content) > 50, f"{fname} is too short"


# ---------------------------------------------------------------------------
# Classify-only guarantees
# ---------------------------------------------------------------------------

class TestClassifyOnlyGuarantees:
    def test_resolver_source_has_no_import_of_requests(self):
        """The resolver module must not import requests, httpx, urllib.request, or aiohttp."""
        resolver_src = Path("core/input_context_resolver.py").read_text(encoding="utf-8")
        forbidden = ["import requests", "import httpx", "import aiohttp",
                     "urllib.request.urlopen", "urllib.request.urlretrieve"]
        for f in forbidden:
            assert f not in resolver_src, f"Forbidden import found: {f}"

    def test_controller_source_has_no_external_http(self):
        ctrl_src = Path("core/workbench_controller.py").read_text(encoding="utf-8")
        forbidden = ["import requests", "import httpx", "import aiohttp",
                     "urllib.request.urlopen", "subprocess"]
        for f in forbidden:
            assert f not in ctrl_src, f"Forbidden found in controller: {f}"

    def test_classifier_source_has_no_external_http(self):
        cls_src = Path("core/work_request_classifier.py").read_text(encoding="utf-8")
        forbidden = ["import requests", "import httpx", "import aiohttp",
                     "urllib.request.urlopen"]
        for f in forbidden:
            assert f not in cls_src, f"Forbidden found in classifier: {f}"

    def test_all_sources_not_approved_by_default(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        result = ctrl.analyze_inputs(
            ["https://app.example.com", "Need tests", "https://github.com/org/repo"],
            project_id="approval-test",
        )
        for src in result["input_map"].sources:
            assert src.approved is False

    def test_mobile_input_detected_not_executed(self, tmp_path):
        ctrl = _make_controller(tmp_path)
        result = ctrl.analyze_inputs(
            ["Need iOS mobile app testing with Appium and Android emulator"],
            project_id="mobile-test",
        )
        tc = result["task_classification"]
        assert "mobile_detected" in tc.signals
        # No execution — just classification
        assert result["project_status"].phase == "intake"


# ---------------------------------------------------------------------------
# classify_inputs.py CLI smoke tests
# ---------------------------------------------------------------------------

class TestClassifyInputsCLI:
    def _run(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "tools/classify_inputs.py"] + args,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_basic_brief_exits_0(self):
        result = self._run(["--input", "Need Playwright tests for SaaS", "--no-write"])
        assert result.returncode == 0, result.stderr

    def test_output_contains_project_id(self):
        result = self._run(["--input", "Need Playwright tests", "--no-write"])
        assert "Project ID" in result.stdout

    def test_json_mode_produces_valid_json(self):
        result = self._run(["--input", "Need API tests", "--json"])
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "project_id" in data
        assert "input_map" in data
        assert "task_classification" in data

    def test_secret_not_in_cli_output(self):
        result = self._run([
            "--input", "Need login test. username=admin password=FakeSecret123",
            "--no-write",
        ])
        assert "FakeSecret123" not in result.stdout
        assert "FakeSecret123" not in result.stderr

    def test_secret_redaction_shown_in_output(self):
        result = self._run([
            "--input", "Need login test. password=FakeSecret123",
            "--no-write",
        ])
        # CLI output should mention redaction or show [REDACTED_PASSWORD]
        combined = result.stdout + result.stderr
        assert "REDACTED" in combined or "redacted" in combined.lower() or "credential" in combined.lower()

    def test_no_args_exits_nonzero(self):
        result = self._run([])
        assert result.returncode != 0

    def test_missing_input_file_exits_nonzero(self):
        result = self._run(["--input-file", "nonexistent_file_xyz.txt"])
        assert result.returncode != 0

    def test_url_classified_in_output(self):
        result = self._run([
            "--input", "https://app.example.com",
            "--no-write",
        ])
        assert "target_url" in result.stdout

    def test_project_id_flag_respected(self):
        result = self._run([
            "--input", "Brief", "--no-write", "--project-id", "my-custom-id",
        ])
        assert "my-custom-id" in result.stdout

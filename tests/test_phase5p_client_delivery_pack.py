"""Phase 5P tests — Client Delivery Pack.

Validates:
  ClientDeliveryManifest safety invariants (injection-proof)
  SecretScanner detection of blocked filenames
  ClientDeliveryPack.build() artifact generation and ZIP creation
  Report content (sections, no credentials, correct format)
  CLI tool flags and exit codes
"""
from __future__ import annotations

import json
import subprocess
import sys
import zipfile
from pathlib import Path

from core.client_delivery_pack import (
    BLOCKED_DELIVERY_FILENAME_PATTERNS,
    ClientDeliveryPack,
    SecretScanner,
    _md_to_html,
)
from core.schemas.client_delivery import (
    ClientDeliveryManifest,
    DeliveryArtifact,
    SecretScanResult,
)

_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# TestClientDeliverySchemas
# ---------------------------------------------------------------------------

class TestClientDeliverySchemas:
    def test_delivery_artifact_defaults(self):
        a = DeliveryArtifact()
        assert a.filename == ""
        assert a.artifact_type == ""
        assert a.size_bytes == 0

    def test_delivery_artifact_included_in_zip_default_true(self):
        assert DeliveryArtifact().included_in_zip is True

    def test_delivery_artifact_secret_clean_default_true(self):
        assert DeliveryArtifact().secret_clean is True

    def test_delivery_artifact_to_dict(self):
        a = DeliveryArtifact(filename="QA_Report.md", artifact_type="qa_report_md", size_bytes=100)
        d = a.to_dict()
        assert d["filename"] == "QA_Report.md"
        assert d["size_bytes"] == 100

    def test_secret_scan_no_issues(self):
        r = SecretScanResult(scanned_files=5, blocked_files=[])
        assert r.issues_found == 0
        assert r.scan_passed is True

    def test_secret_scan_with_issues(self):
        r = SecretScanResult(scanned_files=3, blocked_files=["storageState.json"])
        assert r.issues_found == 1
        assert r.scan_passed is False

    def test_secret_scan_issues_found_computed(self):
        r = SecretScanResult(blocked_files=["a.json", "b.json", "c.json"])
        assert r.issues_found == 3

    def test_secret_scan_injection_scan_passed_blocked(self):
        r = SecretScanResult(blocked_files=["x.json"], scan_passed=True)
        assert r.scan_passed is False

    def test_secret_scan_to_dict(self):
        r = SecretScanResult(scanned_files=2, blocked_files=[])
        d = r.to_dict()
        assert d["scan_passed"] is True
        assert d["issues_found"] == 0

    def test_manifest_approved_default_false(self):
        assert ClientDeliveryManifest().approved_for_client_delivery is False

    def test_manifest_human_review_required_true(self):
        assert ClientDeliveryManifest().human_review_required is True

    def test_manifest_auto_send_false(self):
        assert ClientDeliveryManifest().auto_send_to_client is False

    def test_manifest_secret_scan_before_delivery_true(self):
        assert ClientDeliveryManifest().secret_scan_before_delivery is True

    def test_manifest_raw_secrets_included_false(self):
        assert ClientDeliveryManifest().raw_secrets_included is False

    def test_manifest_injection_approved_blocked(self):
        m = ClientDeliveryManifest(project_id="x", approved_for_client_delivery=True)
        assert m.approved_for_client_delivery is False

    def test_manifest_injection_human_review_blocked(self):
        m = ClientDeliveryManifest(project_id="x", human_review_required=False)
        assert m.human_review_required is True

    def test_manifest_injection_auto_send_blocked(self):
        m = ClientDeliveryManifest(project_id="x", auto_send_to_client=True)
        assert m.auto_send_to_client is False

    def test_manifest_injection_raw_secrets_blocked(self):
        m = ClientDeliveryManifest(project_id="x", raw_secrets_included=True)
        assert m.raw_secrets_included is False

    def test_manifest_project_id_preserved(self):
        m = ClientDeliveryManifest(project_id="demo-5p")
        assert m.project_id == "demo-5p"

    def test_manifest_to_dict_json_round_trip(self):
        m = ClientDeliveryManifest(project_id="demo", generated_at="2026-05-27")
        raw = json.dumps(m.to_dict())
        loaded = json.loads(raw)
        assert loaded["project_id"] == "demo"
        assert loaded["approved_for_client_delivery"] is False
        assert loaded["human_review_required"] is True

    def test_manifest_from_dict_injection_blocked(self):
        d = {"project_id": "x", "approved_for_client_delivery": True, "human_review_required": False}
        m = ClientDeliveryManifest.from_dict(d)
        assert m.approved_for_client_delivery is False
        assert m.human_review_required is True

    def test_manifest_notes_preserved(self):
        m = ClientDeliveryManifest(notes=["note1", "note2"])
        assert "note1" in m.notes


# ---------------------------------------------------------------------------
# TestSecretScanner
# ---------------------------------------------------------------------------

class TestSecretScanner:
    def test_clean_directory(self, tmp_path):
        (tmp_path / "QA_Report.md").write_text("# Report", encoding="utf-8")
        (tmp_path / "Bug_Report.md").write_text("# Bugs", encoding="utf-8")
        result = SecretScanner().scan(tmp_path)
        assert result.scan_passed is True
        assert result.issues_found == 0

    def test_detects_storagestate(self, tmp_path):
        (tmp_path / "storageState.json").write_text("{}", encoding="utf-8")
        result = SecretScanner().scan(tmp_path)
        assert result.scan_passed is False
        assert any("storageState" in f for f in result.blocked_files)

    def test_detects_env_file(self, tmp_path):
        (tmp_path / ".env").write_text("KEY=value", encoding="utf-8")
        result = SecretScanner().scan(tmp_path)
        assert result.scan_passed is False

    def test_detects_credentials_file(self, tmp_path):
        (tmp_path / "credentials.json").write_text("{}", encoding="utf-8")
        result = SecretScanner().scan(tmp_path)
        assert result.scan_passed is False

    def test_detects_password_file(self, tmp_path):
        (tmp_path / "passwords.txt").write_text("pw", encoding="utf-8")
        result = SecretScanner().scan(tmp_path)
        assert result.scan_passed is False

    def test_detects_token_file(self, tmp_path):
        (tmp_path / "auth_token.json").write_text("{}", encoding="utf-8")
        result = SecretScanner().scan(tmp_path)
        assert result.scan_passed is False

    def test_detects_secret_file(self, tmp_path):
        (tmp_path / "api_secret.json").write_text("{}", encoding="utf-8")
        result = SecretScanner().scan(tmp_path)
        assert result.scan_passed is False

    def test_detects_cookie_file(self, tmp_path):
        (tmp_path / "cookies.json").write_text("{}", encoding="utf-8")
        result = SecretScanner().scan(tmp_path)
        assert result.scan_passed is False

    def test_detects_authsession_file(self, tmp_path):
        (tmp_path / "authSession.json").write_text("{}", encoding="utf-8")
        result = SecretScanner().scan(tmp_path)
        assert result.scan_passed is False

    def test_qa_report_not_blocked(self, tmp_path):
        (tmp_path / "QA_Report.md").write_text("# QA Report", encoding="utf-8")
        result = SecretScanner().scan(tmp_path)
        assert result.scan_passed is True

    def test_manifest_json_not_blocked(self, tmp_path):
        (tmp_path / "client_delivery_manifest.json").write_text("{}", encoding="utf-8")
        result = SecretScanner().scan(tmp_path)
        assert result.scan_passed is True

    def test_blocked_count_correct(self, tmp_path):
        (tmp_path / "storageState.json").write_text("{}", encoding="utf-8")
        (tmp_path / "cookies.json").write_text("{}", encoding="utf-8")
        (tmp_path / "QA_Report.md").write_text("# ok", encoding="utf-8")
        result = SecretScanner().scan(tmp_path)
        assert result.issues_found == 2

    def test_scanned_count_correct(self, tmp_path):
        for i in range(3):
            (tmp_path / f"file{i}.md").write_text("x", encoding="utf-8")
        result = SecretScanner().scan(tmp_path)
        assert result.scanned_files == 3

    def test_empty_directory(self, tmp_path):
        result = SecretScanner().scan(tmp_path)
        assert result.scan_passed is True
        assert result.scanned_files == 0

    def test_returns_secret_scan_result_type(self, tmp_path):
        result = SecretScanner().scan(tmp_path)
        assert isinstance(result, SecretScanResult)

    def test_blocked_delivery_patterns_not_empty(self):
        assert len(BLOCKED_DELIVERY_FILENAME_PATTERNS) >= 5

    def test_storagestate_in_patterns(self):
        assert "storagestate" in BLOCKED_DELIVERY_FILENAME_PATTERNS

    def test_env_in_patterns(self):
        assert ".env" in BLOCKED_DELIVERY_FILENAME_PATTERNS


# ---------------------------------------------------------------------------
# TestClientDeliveryPack
# ---------------------------------------------------------------------------

class TestClientDeliveryPack:
    def _build(self, tmp_path):
        pack = ClientDeliveryPack(outputs_root=str(tmp_path / "outputs"))
        return pack.build("demo", output_dir=str(tmp_path / "delivery"))

    def test_build_returns_manifest(self, tmp_path):
        m = self._build(tmp_path)
        assert isinstance(m, ClientDeliveryManifest)

    def test_build_project_id_in_manifest(self, tmp_path):
        m = self._build(tmp_path)
        assert m.project_id == "demo"

    def test_build_generated_at_not_empty(self, tmp_path):
        m = self._build(tmp_path)
        assert m.generated_at != ""

    def test_build_artifacts_list_not_empty(self, tmp_path):
        m = self._build(tmp_path)
        assert len(m.artifacts) > 0

    def test_build_total_artifacts_matches_list(self, tmp_path):
        m = self._build(tmp_path)
        assert m.total_artifacts == len(m.artifacts)

    def test_build_qa_report_md_exists(self, tmp_path):
        self._build(tmp_path)
        assert (tmp_path / "delivery" / "QA_Report.md").exists()

    def test_build_qa_report_html_exists(self, tmp_path):
        self._build(tmp_path)
        assert (tmp_path / "delivery" / "QA_Report.html").exists()

    def test_build_bug_report_exists(self, tmp_path):
        self._build(tmp_path)
        assert (tmp_path / "delivery" / "Bug_Report.md").exists()

    def test_build_test_cases_csv_exists(self, tmp_path):
        self._build(tmp_path)
        assert (tmp_path / "delivery" / "Test_Cases.csv").exists()

    def test_build_risk_matrix_exists(self, tmp_path):
        self._build(tmp_path)
        assert (tmp_path / "delivery" / "Risk_Matrix.md").exists()

    def test_build_recommendations_exists(self, tmp_path):
        self._build(tmp_path)
        assert (tmp_path / "delivery" / "Recommendations.md").exists()

    def test_build_evidence_index_exists(self, tmp_path):
        self._build(tmp_path)
        assert (tmp_path / "delivery" / "Evidence_Index.md").exists()

    def test_build_delivery_checklist_exists(self, tmp_path):
        self._build(tmp_path)
        assert (tmp_path / "delivery" / "Delivery_Checklist.md").exists()

    def test_build_manifest_json_exists(self, tmp_path):
        self._build(tmp_path)
        assert (tmp_path / "delivery" / "client_delivery_manifest.json").exists()

    def test_build_zip_exists(self, tmp_path):
        self._build(tmp_path)
        assert (tmp_path / "delivery" / "client_delivery.zip").exists()

    def test_build_zip_nonempty(self, tmp_path):
        self._build(tmp_path)
        zp = tmp_path / "delivery" / "client_delivery.zip"
        assert zp.stat().st_size > 0

    def test_build_zip_contains_qa_report(self, tmp_path):
        self._build(tmp_path)
        zp = tmp_path / "delivery" / "client_delivery.zip"
        with zipfile.ZipFile(zp) as zf:
            names = zf.namelist()
        assert "QA_Report.md" in names

    def test_build_zip_contains_bug_report(self, tmp_path):
        self._build(tmp_path)
        zp = tmp_path / "delivery" / "client_delivery.zip"
        with zipfile.ZipFile(zp) as zf:
            names = zf.namelist()
        assert "Bug_Report.md" in names

    def test_build_zip_contains_manifest(self, tmp_path):
        self._build(tmp_path)
        zp = tmp_path / "delivery" / "client_delivery.zip"
        with zipfile.ZipFile(zp) as zf:
            names = zf.namelist()
        assert "client_delivery_manifest.json" in names

    def test_build_zip_excludes_itself(self, tmp_path):
        self._build(tmp_path)
        zp = tmp_path / "delivery" / "client_delivery.zip"
        with zipfile.ZipFile(zp) as zf:
            names = zf.namelist()
        assert "client_delivery.zip" not in names

    def test_build_zip_excludes_storagestate(self, tmp_path):
        delivery_dir = tmp_path / "delivery"
        delivery_dir.mkdir(parents=True)
        (delivery_dir / "storageState.json").write_text("{}", encoding="utf-8")
        pack = ClientDeliveryPack(outputs_root=str(tmp_path / "outputs"))
        pack.build("demo", output_dir=str(delivery_dir))
        zp = delivery_dir / "client_delivery.zip"
        with zipfile.ZipFile(zp) as zf:
            names = zf.namelist()
        assert "storageState.json" not in names

    def test_build_secret_scan_ran(self, tmp_path):
        m = self._build(tmp_path)
        assert isinstance(m.secret_scan, SecretScanResult)

    def test_build_scan_passed_for_clean_output(self, tmp_path):
        m = self._build(tmp_path)
        assert m.secret_scan.scan_passed is True

    def test_build_approved_always_false(self, tmp_path):
        m = self._build(tmp_path)
        assert m.approved_for_client_delivery is False

    def test_build_human_review_always_true(self, tmp_path):
        m = self._build(tmp_path)
        assert m.human_review_required is True

    def test_build_auto_send_always_false(self, tmp_path):
        m = self._build(tmp_path)
        assert m.auto_send_to_client is False

    def test_build_secret_scan_before_delivery_true(self, tmp_path):
        m = self._build(tmp_path)
        assert m.secret_scan_before_delivery is True

    def test_build_raw_secrets_included_false(self, tmp_path):
        m = self._build(tmp_path)
        assert m.raw_secrets_included is False

    def test_build_no_write_returns_manifest(self):
        pack = ClientDeliveryPack()
        m = pack.build("demo", write=False)
        assert isinstance(m, ClientDeliveryManifest)
        assert m.project_id == "demo"

    def test_build_no_write_approved_false(self):
        pack = ClientDeliveryPack()
        m = pack.build("demo", write=False)
        assert m.approved_for_client_delivery is False


# ---------------------------------------------------------------------------
# TestArtifactContent
# ---------------------------------------------------------------------------

class TestArtifactContent:
    def _delivery_dir(self, tmp_path):
        pack = ClientDeliveryPack(outputs_root=str(tmp_path / "outputs"))
        pack.build("demo-content", output_dir=str(tmp_path / "delivery"))
        return tmp_path / "delivery"

    def test_qa_report_contains_executive_summary(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "QA_Report.md").read_text(encoding="utf-8")
        assert "Executive Summary" in content

    def test_qa_report_contains_scope_tested(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "QA_Report.md").read_text(encoding="utf-8")
        assert "Scope Tested" in content

    def test_qa_report_contains_project_id(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "QA_Report.md").read_text(encoding="utf-8")
        assert "demo-content" in content

    def test_qa_report_contains_next_steps(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "QA_Report.md").read_text(encoding="utf-8")
        assert "Next Steps" in content

    def test_qa_report_no_raw_password(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "QA_Report.md").read_text(encoding="utf-8").lower()
        assert "password:" not in content
        assert "password=" not in content

    def test_qa_report_no_api_key_value(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "QA_Report.md").read_text(encoding="utf-8").lower()
        assert "api_key:" not in content

    def test_qa_report_no_token_value(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "QA_Report.md").read_text(encoding="utf-8").lower()
        assert "token=" not in content

    def test_qa_report_approved_false_stated(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "QA_Report.md").read_text(encoding="utf-8")
        assert "No" in content or "pending" in content.lower()

    def test_qa_report_html_contains_doctype(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "QA_Report.html").read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content

    def test_qa_report_html_contains_html_tag(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "QA_Report.html").read_text(encoding="utf-8")
        assert "<html" in content

    def test_qa_report_html_contains_draft_notice(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "QA_Report.html").read_text(encoding="utf-8")
        assert "DRAFT" in content or "Not approved" in content

    def test_bug_report_contains_bug(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "Bug_Report.md").read_text(encoding="utf-8")
        assert "Bug" in content or "bug" in content

    def test_bug_report_contains_severity(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "Bug_Report.md").read_text(encoding="utf-8")
        assert "Severity" in content

    def test_test_cases_csv_has_header(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        lines = (d / "Test_Cases.csv").read_text(encoding="utf-8").splitlines()
        assert lines[0].startswith("ID,")
        assert "Title" in lines[0]

    def test_test_cases_csv_has_tc001(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "Test_Cases.csv").read_text(encoding="utf-8")
        assert "TC-001" in content

    def test_test_cases_csv_multiple_rows(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        lines = (d / "Test_Cases.csv").read_text(encoding="utf-8").splitlines()
        assert len(lines) >= 5

    def test_risk_matrix_contains_risk(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "Risk_Matrix.md").read_text(encoding="utf-8")
        assert "Risk" in content

    def test_risk_matrix_contains_severity(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "Risk_Matrix.md").read_text(encoding="utf-8")
        assert "Severity" in content

    def test_recommendations_contains_ci(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "Recommendations.md").read_text(encoding="utf-8")
        assert "CI" in content or "ci" in content.lower()

    def test_recommendations_contains_security(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "Recommendations.md").read_text(encoding="utf-8")
        assert "Security" in content or "secret" in content.lower()

    def test_evidence_index_contains_evidence(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "Evidence_Index.md").read_text(encoding="utf-8")
        assert "Evidence" in content

    def test_evidence_index_has_checklist(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "Evidence_Index.md").read_text(encoding="utf-8")
        assert "[ ]" in content

    def test_delivery_checklist_has_unchecked_items(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "Delivery_Checklist.md").read_text(encoding="utf-8")
        assert "[ ]" in content

    def test_delivery_checklist_mentions_sign_off(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        content = (d / "Delivery_Checklist.md").read_text(encoding="utf-8")
        assert "sign" in content.lower() or "Sign" in content

    def test_manifest_json_is_valid(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        raw = (d / "client_delivery_manifest.json").read_text(encoding="utf-8")
        loaded = json.loads(raw)
        assert loaded["project_id"] == "demo-content"

    def test_manifest_json_approved_false(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        loaded = json.loads((d / "client_delivery_manifest.json").read_text(encoding="utf-8"))
        assert loaded["approved_for_client_delivery"] is False

    def test_manifest_json_human_review_true(self, tmp_path):
        d = self._delivery_dir(tmp_path)
        loaded = json.loads((d / "client_delivery_manifest.json").read_text(encoding="utf-8"))
        assert loaded["human_review_required"] is True

    def test_md_to_html_produces_h1(self):
        html = _md_to_html("# Title\n\nBody text.", "Test")
        assert "<h1>" in html
        assert "Title" in html

    def test_md_to_html_produces_h2(self):
        html = _md_to_html("## Section\n\nContent.", "Test")
        assert "<h2>" in html

    def test_md_to_html_bold(self):
        html = _md_to_html("**bold text**", "Test")
        assert "<strong>bold text</strong>" in html

    def test_md_to_html_code(self):
        html = _md_to_html("`code_snippet`", "Test")
        assert "<code>code_snippet</code>" in html


# ---------------------------------------------------------------------------
# TestCLITool
# ---------------------------------------------------------------------------

class TestCLITool:
    _CLI = [sys.executable, "tools/create_client_delivery_pack.py"]

    def test_missing_project_id_exits_2(self):
        result = subprocess.run(
            self._CLI, capture_output=True, cwd=str(_ROOT)
        )
        assert result.returncode == 2

    def test_help_exits_0(self):
        result = subprocess.run(
            self._CLI + ["--help"], capture_output=True, cwd=str(_ROOT)
        )
        assert result.returncode == 0

    def test_blocked_approve_flag_exits_1(self):
        result = subprocess.run(
            self._CLI + ["--project-id", "demo", "--approve", "--no-write"],
            capture_output=True, cwd=str(_ROOT)
        )
        assert result.returncode == 1

    def test_blocked_auto_send_exits_1(self):
        result = subprocess.run(
            self._CLI + ["--project-id", "demo", "--auto-send", "--no-write"],
            capture_output=True, cwd=str(_ROOT)
        )
        assert result.returncode == 1

    def test_blocked_skip_secret_scan_exits_1(self):
        result = subprocess.run(
            self._CLI + ["--project-id", "demo", "--skip-secret-scan", "--no-write"],
            capture_output=True, cwd=str(_ROOT)
        )
        assert result.returncode == 1

    def test_no_write_flag_exits_0(self):
        result = subprocess.run(
            self._CLI + ["--project-id", "demo-cli-test", "--no-write"],
            capture_output=True, cwd=str(_ROOT)
        )
        assert result.returncode == 0

    def test_output_mentions_review_required(self):
        result = subprocess.run(
            self._CLI + ["--project-id", "demo-cli-test", "--no-write"],
            capture_output=True, text=True, cwd=str(_ROOT)
        )
        assert "REVIEW REQUIRED" in result.stdout or "review" in result.stdout.lower()

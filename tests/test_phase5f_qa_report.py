"""
Phase 5F — QA Evidence Report Generator tests.

Fixture-based only — no real filesystem artifacts required for most tests.
No execution. No network calls. No .env reading.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch


from core.qa_report_generator import QAReportGenerator
from core.schemas.qa_report import (
    QAEvidenceReport,
)


# ---------------------------------------------------------------------------
# Fixtures — synthetic artifact files
# ---------------------------------------------------------------------------

BROWSER_ARTIFACT = {
    "project_id": "fixture-browser",
    "execution_status": "passed",
    "scenario_lane": "dedicated_test_account_auth_future",
    "target_category": "orangehrm_demo_auth",
    "target_url": "https://opensource-demo.orangehrmlive.com",
    "raw_credentials_logged": False,
    "raw_credentials_serialized": False,
    "personal_account_used": False,
    "production_account_used": False,
    "safe_to_deliver": False,
    "approved_for_client_delivery": False,
    "commands": [
        {
            "id": "dedicated_auth_cmd_001",
            "command": "npx playwright test tests/auth --reporter=list",
            "status": "passed",
            "exit_code": 0,
            "duration_seconds": 10.75,
            "executed": True,
        }
    ],
}

API_ARTIFACT = {
    "project_id": "fixture-api",
    "target_profile": "restful_booker_public_api",
    "base_url": "https://restful-booker.herokuapp.com",
    "execution_status": "passed",
    "raw_credentials_logged": False,
    "raw_credentials_serialized": False,
    "token_logged": False,
    "token_serialized": False,
    "safe_to_deliver": False,
    "approved_for_client_delivery": False,
    "personal_account_used": False,
    "production_account_used": False,
    "commands": [
        {"id": "api_auth_step1_post_auth", "method": "POST",
         "url": "https://restful-booker.herokuapp.com/auth",
         "status": "passed", "status_code": 200, "duration_seconds": 0.78,
         "token_present": True},
        {"id": "api_auth_step2_get_booking", "method": "GET",
         "url": "https://restful-booker.herokuapp.com/booking",
         "status": "passed", "status_code": 200, "duration_seconds": 0.69,
         "token_present": False},
    ],
}


def _write_browser_fixture(root: Path, project_id: str, data: dict = None) -> Path:
    d = root / project_id / "12_dedicated_auth"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "DEDICATED_AUTH_EXECUTION_REPORT.json"
    p.write_text(json.dumps(data or BROWSER_ARTIFACT), encoding="utf-8")
    return p


def _write_api_fixture(root: Path, project_id: str, data: dict = None) -> Path:
    d = root / project_id / "13_api_auth"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "API_AUTH_EXECUTION_REPORT.json"
    p.write_text(json.dumps(data or API_ARTIFACT), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Schema invariant tests
# ---------------------------------------------------------------------------

class TestQAEvidenceReportInvariants:
    def test_safety_flags_hardcoded(self):
        report = QAEvidenceReport(
            execution_performed=True,
            network_calls_performed=True,
            raw_credentials_in_report=True,
            raw_tokens_in_report=True,
            storage_state_content_read=True,
            safe_to_deliver=True,
            approved_for_client_delivery=True,
            client_ready=True,
            human_review_required=False,
        )
        assert report.execution_performed is False
        assert report.network_calls_performed is False
        assert report.raw_credentials_in_report is False
        assert report.raw_tokens_in_report is False
        assert report.storage_state_content_read is False
        assert report.safe_to_deliver is False
        assert report.approved_for_client_delivery is False
        assert report.client_ready is False
        assert report.human_review_required is True

    def test_from_dict_safety_flags_forced(self):
        report = QAEvidenceReport.from_dict({
            "safe_to_deliver": True,
            "approved_for_client_delivery": True,
            "client_ready": True,
            "human_review_required": False,
            "execution_performed": True,
        })
        assert report.safe_to_deliver is False
        assert report.approved_for_client_delivery is False
        assert report.client_ready is False
        assert report.human_review_required is True
        assert report.execution_performed is False


# ---------------------------------------------------------------------------
# Single-source tests
# ---------------------------------------------------------------------------

class TestQAReportGeneratorSingleSource:
    def test_browser_only_source(self, tmp_path):
        _write_browser_fixture(tmp_path, "proj-browser")
        gen = QAReportGenerator(outputs_root=tmp_path)
        report = gen.generate("out-report", ["proj-browser"], write=False)

        assert len(report.sources) == 1
        src = report.sources[0]
        assert src.source_project_id == "proj-browser"
        assert len(src.evidence_items) == 1
        item = src.evidence_items[0]
        assert item.lane == "browser_auth"
        assert item.status == "passed"

    def test_api_only_source(self, tmp_path):
        _write_api_fixture(tmp_path, "proj-api")
        gen = QAReportGenerator(outputs_root=tmp_path)
        report = gen.generate("out-report", ["proj-api"], write=False)

        assert len(report.sources) == 1
        item = report.sources[0].evidence_items[0]
        assert item.lane == "api_auth"
        assert item.status == "passed"
        assert item.commands_executed == 2

    def test_missing_artifacts_handled_gracefully(self, tmp_path):
        # No artifacts written — source dir doesn't exist
        gen = QAReportGenerator(outputs_root=tmp_path)
        report = gen.generate("out-report", ["nonexistent-project"], write=False)

        src = report.sources[0]
        assert len(src.artifacts_found) == 0
        assert len(src.artifacts_missing) == 2
        assert len(src.evidence_items) == 0

    def test_partial_artifacts(self, tmp_path):
        # Only browser, no API
        _write_browser_fixture(tmp_path, "partial-proj")
        gen = QAReportGenerator(outputs_root=tmp_path)
        report = gen.generate("out-report", ["partial-proj"], write=False)

        src = report.sources[0]
        assert len(src.artifacts_found) == 1
        assert len(src.artifacts_missing) == 1
        assert src.evidence_items[0].lane == "browser_auth"


# ---------------------------------------------------------------------------
# Multi-source tests
# ---------------------------------------------------------------------------

class TestQAReportGeneratorMultiSource:
    def test_combined_browser_and_api(self, tmp_path):
        _write_browser_fixture(tmp_path, "browser-proj")
        _write_api_fixture(tmp_path, "api-proj")
        gen = QAReportGenerator(outputs_root=tmp_path)
        report = gen.generate("combined", ["browser-proj", "api-proj"], write=False)

        assert len(report.sources) == 2
        assert report.source_project_ids == ["browser-proj", "api-proj"]
        all_items = [i for s in report.sources for i in s.evidence_items]
        lanes = {i.lane for i in all_items}
        assert "browser_auth" in lanes
        assert "api_auth" in lanes

    def test_coverage_aggregation(self, tmp_path):
        _write_browser_fixture(tmp_path, "bp")
        _write_api_fixture(tmp_path, "ap")
        gen = QAReportGenerator(outputs_root=tmp_path)
        report = gen.generate("cov-test", ["bp", "ap"], write=False)

        cov = report.coverage
        assert cov is not None
        assert cov.passed == 2
        assert cov.total_evidence_items == 2
        assert "browser_auth" in cov.covered_lanes
        assert "api_auth" in cov.covered_lanes
        assert "functional_tests" in cov.not_covered
        assert "e2e_scenarios" in cov.not_covered

    def test_same_project_id_as_source(self, tmp_path):
        # project_id same as source_project_id — valid case
        _write_browser_fixture(tmp_path, "same-proj")
        gen = QAReportGenerator(outputs_root=tmp_path)
        report = gen.generate("same-proj", ["same-proj"], write=False)
        assert len(report.sources) == 1

    def test_three_sources(self, tmp_path):
        for name in ["s1", "s2", "s3"]:
            _write_browser_fixture(tmp_path, name)
        gen = QAReportGenerator(outputs_root=tmp_path)
        report = gen.generate("multi3", ["s1", "s2", "s3"], write=False)
        assert len(report.sources) == 3
        assert report.coverage.total_evidence_items == 3


# ---------------------------------------------------------------------------
# Safety invariants in generated report
# ---------------------------------------------------------------------------

class TestQAReportSafetyInGenerated:
    def test_no_execution_performed(self, tmp_path):
        _write_browser_fixture(tmp_path, "bp")
        gen = QAReportGenerator(outputs_root=tmp_path)
        report = gen.generate("test", ["bp"], write=False)
        assert report.execution_performed is False
        assert report.network_calls_performed is False

    def test_storage_state_not_read(self, tmp_path):
        # Even if storageState exists, generator must not read it
        _write_browser_fixture(tmp_path, "bp")
        auth_dir = tmp_path / "bp" / "12_dedicated_auth" / ".auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        (auth_dir / "storageState.json").write_text('{"cookies": [{"name": "auth", "value": "secret_session"}]}')

        gen = QAReportGenerator(outputs_root=tmp_path)
        report = gen.generate("test", ["bp"], write=True)

        # storageState content must not appear in any output artifact
        out_dir = tmp_path / "test" / "14_qa_report"
        for f in out_dir.rglob("*"):
            if f.is_file():
                content = f.read_text(encoding="utf-8")
                assert "secret_session" not in content, f"storageState content leaked into {f.name}"
        assert report.storage_state_content_read is False

    def test_safety_flags_in_written_json(self, tmp_path):
        _write_api_fixture(tmp_path, "ap")
        gen = QAReportGenerator(outputs_root=tmp_path)
        gen.generate("flag-test", ["ap"], write=True)

        data = json.loads((tmp_path / "flag-test" / "14_qa_report" / "QA_EVIDENCE_REPORT.json").read_text())
        assert data["safe_to_deliver"] is False
        assert data["approved_for_client_delivery"] is False
        assert data["client_ready"] is False
        assert data["human_review_required"] is True
        assert data["execution_performed"] is False
        assert data["storage_state_content_read"] is False


# ---------------------------------------------------------------------------
# Secret scan tests
# ---------------------------------------------------------------------------

class TestQAReportSecretScan:
    def test_clean_report_passes_scan(self, tmp_path):
        _write_browser_fixture(tmp_path, "bp")
        gen = QAReportGenerator(outputs_root=tmp_path)
        with patch.dict(os.environ, {"ORANGEHRM_USERNAME": "admin_test_xyz"}):
            report = gen.generate("test", ["bp"], write=False)

        scan = report.secret_scan
        assert scan is not None
        assert scan.scan_performed is True
        # The fixture does not contain "admin_test_xyz" so should be clean
        assert scan.raw_secret_found is False
        assert scan.verdict == "clean"

    def test_injected_secret_detected(self, tmp_path):
        # Inject a fake secret value into the artifact, then check it's detected
        secret = "FAKE_INJECTED_SECRET_12345"
        bad_artifact = dict(BROWSER_ARTIFACT)
        bad_artifact["notes"] = [f"debug: user={secret}"]
        _write_browser_fixture(tmp_path, "bp", data=bad_artifact)

        gen = QAReportGenerator(outputs_root=tmp_path)
        with patch.dict(os.environ, {"QA_TEST_USERNAME": secret}):
            report = gen.generate("test", ["bp"], write=False)

        scan = report.secret_scan
        assert scan.raw_secret_found is True
        assert scan.verdict == "fail"
        assert any("QA_TEST_USERNAME" in f for f in scan.findings)

    def test_scan_checks_multiple_env_vars(self, tmp_path):
        _write_api_fixture(tmp_path, "ap")
        gen = QAReportGenerator(outputs_root=tmp_path)
        env = {
            "RESTFUL_BOOKER_USERNAME": "rb_user_xyz",
            "RESTFUL_BOOKER_PASSWORD": "rb_pass_xyz",
        }
        with patch.dict(os.environ, env):
            report = gen.generate("test", ["ap"], write=False)

        scan = report.secret_scan
        # Fixture doesn't contain these values, so scan should be clean
        assert scan.raw_secret_found is False
        assert "RESTFUL_BOOKER_USERNAME" in scan.checked_env_var_names
        assert "RESTFUL_BOOKER_PASSWORD" in scan.checked_env_var_names

    def test_scan_result_written_to_artifact(self, tmp_path):
        _write_browser_fixture(tmp_path, "bp")
        gen = QAReportGenerator(outputs_root=tmp_path)
        gen.generate("test", ["bp"], write=True)

        scan_json = json.loads((tmp_path / "test" / "14_qa_report" / "QA_REPORT_SECRET_SCAN.json").read_text())
        assert "verdict" in scan_json
        assert "raw_secret_found" in scan_json
        assert scan_json["raw_secret_found"] is False


# ---------------------------------------------------------------------------
# Artifact writing tests
# ---------------------------------------------------------------------------

class TestQAReportArtifacts:
    def test_five_artifacts_written(self, tmp_path):
        _write_browser_fixture(tmp_path, "bp")
        _write_api_fixture(tmp_path, "ap")
        gen = QAReportGenerator(outputs_root=tmp_path)
        gen.generate("written-test", ["bp", "ap"], write=True)

        out = tmp_path / "written-test" / "14_qa_report"
        assert (out / "QA_EVIDENCE_REPORT.json").exists()
        assert (out / "QA_EVIDENCE_REPORT.md").exists()
        assert (out / "QA_REPORT_REVIEW_CHECKLIST.md").exists()
        assert (out / "QA_REPORT_SECRET_SCAN.json").exists()
        assert (out / "QA_REPORT_SECRET_SCAN.md").exists()

    def test_no_write_produces_no_files(self, tmp_path):
        _write_browser_fixture(tmp_path, "bp")
        gen = QAReportGenerator(outputs_root=tmp_path)
        gen.generate("nowrote", ["bp"], write=False)
        assert not (tmp_path / "nowrote" / "14_qa_report").exists()

    def test_md_report_contains_key_sections(self, tmp_path):
        _write_browser_fixture(tmp_path, "bp")
        _write_api_fixture(tmp_path, "ap")
        gen = QAReportGenerator(outputs_root=tmp_path)
        gen.generate("sec-test", ["bp", "ap"], write=True)

        md = (tmp_path / "sec-test" / "14_qa_report" / "QA_EVIDENCE_REPORT.md").read_text()
        for section in ["## Summary", "## Browser Auth Evidence", "## API Auth Evidence",
                        "## Coverage", "## Secret Scan", "## Safety Boundary",
                        "## Human Review Checklist", "## Not Covered"]:
            assert section in md, f"Missing section: {section}"

    def test_md_report_has_safety_boundary(self, tmp_path):
        _write_browser_fixture(tmp_path, "bp")
        gen = QAReportGenerator(outputs_root=tmp_path)
        gen.generate("safety-test", ["bp"], write=True)

        md = (tmp_path / "safety-test" / "14_qa_report" / "QA_EVIDENCE_REPORT.md").read_text()
        assert "safe_to_deliver: **False**" in md
        assert "approved_for_client_delivery: **False**" in md
        assert "human_review_required: **True**" in md

    def test_checklist_has_all_items(self, tmp_path):
        _write_browser_fixture(tmp_path, "bp")
        gen = QAReportGenerator(outputs_root=tmp_path)
        gen.generate("cl-test", ["bp"], write=True)

        cl = (tmp_path / "cl-test" / "14_qa_report" / "QA_REPORT_REVIEW_CHECKLIST.md").read_text()
        assert "approved_for_client_delivery=False" in cl
        assert "DO NOT SEND TO CLIENT" in cl


# ---------------------------------------------------------------------------
# CLI safety
# ---------------------------------------------------------------------------

class TestQAReportCLI:
    def test_no_execution_flags_in_cli(self):
        src = Path("tools/generate_qa_report.py").read_text(encoding="utf-8")
        # No flags that could trigger execution
        assert "--approve" not in src
        assert "subprocess" not in src
        assert "urlopen" not in src
        assert "requests" not in src

    def test_source_project_id_flag_present(self):
        src = Path("tools/generate_qa_report.py").read_text(encoding="utf-8")
        assert "--source-project-id" in src
        assert "--source-projects" in src

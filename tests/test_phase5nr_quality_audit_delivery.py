"""Phase 5N-R tests — Quality audit demo workflow + Delivery Pack integration.

Validates that:
1. demo_quality_audit fixture set is complete and correct
2. planning_only mode produces no-network artifacts
3. approved execution mode (passive security) returns real results with mocked HEAD
4. Client Delivery Pack correctly integrates Phase 5N modules
5. ZIP excludes all blocked filenames
6. QA report content reflects planning_only vs executed status honestly

Fixture layout:
  fixtures/demo_quality_audit/
    29_accessibility/   — planning_only spec + report
    30_performance/     — planning_only spec + report
    31_passive_security/ — executed report (3 present, 2 missing)
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from unittest.mock import patch

import pytest

from core.accessibility_runner import AccessibilityRunner
from core.client_delivery_pack import ClientDeliveryPack
from core.performance_smoke_runner import PerformanceSmokeRunner
from core.passive_security_runner import PassiveSecurityRunner
from core.schemas.accessibility import AccessibilityReport
from core.schemas.performance_smoke import PerformanceSmokeReport

_FIXTURES_ROOT = Path(__file__).parent.parent / "fixtures"
_DEMO_ID = "demo_quality_audit"
_DEMO_DIR = _FIXTURES_ROOT / _DEMO_ID

_MOCK_HEADERS_PARTIAL = {
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "x-content-type-options": "nosniff",
    "x-frame-options": "SAMEORIGIN",
}


# ---------------------------------------------------------------------------
# TestDemoFixtureIntegrity — committed fixture set is complete and valid
# ---------------------------------------------------------------------------

class TestDemoFixtureIntegrity:
    def test_demo_dir_exists(self):
        assert _DEMO_DIR.exists(), f"Missing demo fixture dir: {_DEMO_DIR}"

    # 29_accessibility
    def test_a11y_dir_exists(self):
        assert (_DEMO_DIR / "29_accessibility").exists()

    def test_a11y_spec_exists(self):
        assert (_DEMO_DIR / "29_accessibility" / "accessibility_smoke.generated.spec.ts").exists()

    def test_a11y_report_json_exists(self):
        assert (_DEMO_DIR / "29_accessibility" / "accessibility_report.json").exists()

    def test_a11y_summary_md_exists(self):
        assert (_DEMO_DIR / "29_accessibility" / "accessibility_summary.md").exists()

    def test_a11y_violations_csv_exists(self):
        assert (_DEMO_DIR / "29_accessibility" / "accessibility_violations.csv").exists()

    def test_a11y_report_json_valid(self):
        d = json.loads((_DEMO_DIR / "29_accessibility" / "accessibility_report.json").read_text(encoding="utf-8"))
        assert d["project_id"] == _DEMO_ID
        assert d["status"] == "planning_only"

    def test_a11y_report_safety_flags(self):
        d = json.loads((_DEMO_DIR / "29_accessibility" / "accessibility_report.json").read_text(encoding="utf-8"))
        assert d["read_only"] is True
        assert d["active_scan_allowed"] is False
        assert d["exploit_attempts_allowed"] is False
        assert d["human_review_required"] is True

    def test_a11y_report_planning_only(self):
        d = json.loads((_DEMO_DIR / "29_accessibility" / "accessibility_report.json").read_text(encoding="utf-8"))
        assert d["status"] == "planning_only"

    # 30_performance
    def test_perf_dir_exists(self):
        assert (_DEMO_DIR / "30_performance").exists()

    def test_perf_spec_exists(self):
        assert (_DEMO_DIR / "30_performance" / "performance_smoke.generated.spec.ts").exists()

    def test_perf_report_json_exists(self):
        assert (_DEMO_DIR / "30_performance" / "performance_report.json").exists()

    def test_perf_report_json_valid(self):
        d = json.loads((_DEMO_DIR / "30_performance" / "performance_report.json").read_text(encoding="utf-8"))
        assert d["project_id"] == _DEMO_ID
        assert d["status"] == "planning_only"

    def test_perf_report_safety_flags(self):
        d = json.loads((_DEMO_DIR / "30_performance" / "performance_report.json").read_text(encoding="utf-8"))
        assert d["load_testing_allowed"] is False
        assert d["active_scan_allowed"] is False
        assert d["human_review_required"] is True

    def test_perf_report_has_thresholds(self):
        d = json.loads((_DEMO_DIR / "30_performance" / "performance_report.json").read_text(encoding="utf-8"))
        assert len(d["thresholds"]) > 0
        metrics = [t["metric"] for t in d["thresholds"]]
        assert "LCP" in metrics

    def test_perf_slow_resources_json_exists(self):
        assert (_DEMO_DIR / "30_performance" / "slow_resources.json").exists()

    # 31_passive_security — executed demo
    def test_sec_dir_exists(self):
        assert (_DEMO_DIR / "31_passive_security").exists()

    def test_sec_spec_exists(self):
        assert (_DEMO_DIR / "31_passive_security" / "passive_security.generated.spec.ts").exists()

    def test_sec_report_json_exists(self):
        assert (_DEMO_DIR / "31_passive_security" / "passive_security_report.json").exists()

    def test_sec_report_status_executed(self):
        d = json.loads((_DEMO_DIR / "31_passive_security" / "passive_security_report.json").read_text(encoding="utf-8"))
        assert d["status"] == "executed"

    def test_sec_report_has_real_header_results(self):
        d = json.loads((_DEMO_DIR / "31_passive_security" / "passive_security_report.json").read_text(encoding="utf-8"))
        assert d["total_headers_checked"] == 5
        assert d["missing_headers"] == 2
        assert len(d["headers_found"]) == 3
        assert len(d["headers_missing"]) == 2

    def test_sec_report_safety_flags(self):
        d = json.loads((_DEMO_DIR / "31_passive_security" / "passive_security_report.json").read_text(encoding="utf-8"))
        assert d["read_only"] is True
        assert d["active_scan_allowed"] is False
        assert d["exploit_attempts_allowed"] is False
        assert d["auth_bypass_allowed"] is False
        assert d["human_review_required"] is True

    def test_sec_report_missing_headers_are_csp_and_referrer(self):
        d = json.loads((_DEMO_DIR / "31_passive_security" / "passive_security_report.json").read_text(encoding="utf-8"))
        assert "content-security-policy" in d["headers_missing"]
        assert "referrer-policy" in d["headers_missing"]

    def test_sec_security_headers_json_exists(self):
        assert (_DEMO_DIR / "31_passive_security" / "security_headers.json").exists()

    def test_sec_security_headers_json_valid(self):
        d = json.loads((_DEMO_DIR / "31_passive_security" / "security_headers.json").read_text(encoding="utf-8"))
        assert "headers" in d

    def test_sec_security_headers_no_credentials(self):
        content = (_DEMO_DIR / "31_passive_security" / "security_headers.json").read_text(encoding="utf-8").lower()
        assert "password" not in content
        assert "api_key" not in content
        assert "secret" not in content
        assert "token" not in content


# ---------------------------------------------------------------------------
# TestPlanningOnlyMode — runners in default mode produce no-network artifacts
# ---------------------------------------------------------------------------

class TestPlanningOnlyMode:
    def test_a11y_generate_plan_status_planning_only(self, tmp_path):
        r = AccessibilityRunner("qa-test", "https://example.com", str(tmp_path))
        report = r.generate_plan()
        assert report.status == "planning_only"

    def test_perf_generate_plan_status_planning_only(self, tmp_path):
        r = PerformanceSmokeRunner("qa-test", "https://example.com", str(tmp_path))
        report = r.generate_plan()
        assert report.status == "planning_only"

    def test_sec_generate_plan_status_planning_only(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        report = r.generate_plan()
        assert report.status == "planning_only"

    def test_a11y_planning_only_has_safety_flags(self, tmp_path):
        r = AccessibilityRunner("qa-test", "https://example.com", str(tmp_path))
        report = r.generate_plan()
        assert report.read_only is True
        assert report.active_scan_allowed is False
        assert report.human_review_required is True

    def test_perf_planning_only_has_safety_flags(self, tmp_path):
        r = PerformanceSmokeRunner("qa-test", "https://example.com", str(tmp_path))
        report = r.generate_plan()
        assert report.load_testing_allowed is False
        assert report.active_scan_allowed is False
        assert report.human_review_required is True

    def test_sec_planning_only_has_safety_flags(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        report = r.generate_plan()
        assert report.active_scan_allowed is False
        assert report.exploit_attempts_allowed is False
        assert report.human_review_required is True

    def test_a11y_planning_report_json_has_status(self, tmp_path):
        r = AccessibilityRunner("qa-test", "https://example.com", str(tmp_path))
        r.generate_plan()
        d = json.loads((tmp_path / "qa-test" / "29_accessibility" / "accessibility_report.json").read_text(encoding="utf-8"))
        assert d["status"] == "planning_only"

    def test_perf_planning_report_json_has_status(self, tmp_path):
        r = PerformanceSmokeRunner("qa-test", "https://example.com", str(tmp_path))
        r.generate_plan()
        d = json.loads((tmp_path / "qa-test" / "30_performance" / "performance_report.json").read_text(encoding="utf-8"))
        assert d["status"] == "planning_only"

    def test_sec_planning_report_json_has_status(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        r.generate_plan()
        d = json.loads((tmp_path / "qa-test" / "31_passive_security" / "passive_security_report.json").read_text(encoding="utf-8"))
        assert d["status"] == "planning_only"

    def test_a11y_planning_summary_has_draft_notice(self, tmp_path):
        r = AccessibilityRunner("qa-test", "https://example.com", str(tmp_path))
        r.generate_plan()
        content = (tmp_path / "qa-test" / "29_accessibility" / "accessibility_summary.md").read_text(encoding="utf-8")
        assert "DRAFT" in content or "planning_only" in content

    def test_perf_planning_summary_has_draft_notice(self, tmp_path):
        r = PerformanceSmokeRunner("qa-test", "https://example.com", str(tmp_path))
        r.generate_plan()
        content = (tmp_path / "qa-test" / "30_performance" / "performance_summary.md").read_text(encoding="utf-8")
        assert "DRAFT" in content or "planning_only" in content

    def test_sec_planning_summary_has_draft_notice(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        r.generate_plan()
        content = (tmp_path / "qa-test" / "31_passive_security" / "passive_security_summary.md").read_text(encoding="utf-8")
        assert "DRAFT" in content or "planning_only" in content

    def test_a11y_planning_spec_has_human_review_notice(self, tmp_path):
        r = AccessibilityRunner("qa-test", "https://example.com", str(tmp_path))
        r.generate_plan()
        content = (tmp_path / "qa-test" / "29_accessibility" / "accessibility_smoke.generated.spec.ts").read_text(encoding="utf-8")
        assert "planning_only" in content or "human review" in content.lower()

    def test_sec_planning_only_all_checks_not_checked(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        report = r.generate_plan()
        for check in report.headers_checked:
            assert check.check_status == "not_checked"


# ---------------------------------------------------------------------------
# TestApprovedExecutionMode — approved path with mocked HEAD request
# ---------------------------------------------------------------------------

class TestApprovedExecutionMode:
    def test_sec_execute_requires_approval(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        with pytest.raises(ValueError, match="approve-public-readonly"):
            r.execute(approve_public_readonly=False)

    def test_sec_execute_approved_returns_executed(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_PARTIAL):
            report = r.execute(approve_public_readonly=True)
        assert report.status == "executed"

    def test_sec_execute_approved_finds_present_headers(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_PARTIAL):
            report = r.execute(approve_public_readonly=True)
        assert len(report.headers_found) == 3
        assert "x-content-type-options" in report.headers_found

    def test_sec_execute_approved_finds_missing_headers(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_PARTIAL):
            report = r.execute(approve_public_readonly=True)
        assert "content-security-policy" in report.headers_missing
        assert "referrer-policy" in report.headers_missing

    def test_sec_execute_approved_total_checked_is_5(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_PARTIAL):
            report = r.execute(approve_public_readonly=True)
        assert report.total_headers_checked == 5

    def test_sec_execute_approved_missing_count_is_2(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_PARTIAL):
            report = r.execute(approve_public_readonly=True)
        assert report.missing_headers == 2

    def test_sec_execute_safety_invariants_intact(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_PARTIAL):
            report = r.execute(approve_public_readonly=True)
        assert report.read_only is True
        assert report.active_scan_allowed is False
        assert report.exploit_attempts_allowed is False
        assert report.auth_bypass_allowed is False
        assert report.destructive_actions_allowed is False
        assert report.human_review_required is True

    def test_sec_execute_report_json_shows_executed(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_PARTIAL):
            r.execute(approve_public_readonly=True)
        d = json.loads(
            (tmp_path / "qa-test" / "31_passive_security" / "passive_security_report.json").read_text(encoding="utf-8")
        )
        assert d["status"] == "executed"
        assert d["active_scan_allowed"] is False

    def test_sec_execute_summary_shows_executed(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_PARTIAL):
            r.execute(approve_public_readonly=True)
        content = (
            tmp_path / "qa-test" / "31_passive_security" / "passive_security_summary.md"
        ).read_text(encoding="utf-8")
        assert "Executed" in content or "executed" in content

    def test_a11y_execute_without_browser_approval_raises(self, tmp_path):
        r = AccessibilityRunner("qa-test", "https://example.com", str(tmp_path))
        with pytest.raises(ValueError, match="approve-browser-execution"):
            r.execute(approve_public_readonly=True, approve_browser_execution=False)

    def test_a11y_execute_approved_still_planning_only(self, tmp_path):
        r = AccessibilityRunner("qa-test", "https://example.com", str(tmp_path))
        report = r.execute(approve_public_readonly=True, approve_browser_execution=True)
        assert isinstance(report, AccessibilityReport)
        assert report.status == "planning_only"

    def test_perf_execute_approved_still_planning_only(self, tmp_path):
        r = PerformanceSmokeRunner("qa-test", "https://example.com", str(tmp_path))
        report = r.execute(approve_public_readonly=True, approve_browser_execution=True)
        assert isinstance(report, PerformanceSmokeReport)
        assert report.status == "planning_only"

    def test_a11y_execute_approved_adds_run_note(self, tmp_path):
        r = AccessibilityRunner("qa-test", "https://example.com", str(tmp_path))
        report = r.execute(approve_public_readonly=True, approve_browser_execution=True)
        notes = " ".join(report.notes).lower()
        assert "npx playwright test" in notes or "approved" in notes

    def test_sec_execute_failed_head_raises_runtime_error(self, tmp_path):
        r = PassiveSecurityRunner("qa-test", "https://example.com", str(tmp_path))
        with patch(
            "core.passive_security_runner._fetch_response_headers",
            side_effect=RuntimeError("HEAD request failed"),
        ):
            with pytest.raises(RuntimeError, match="HEAD request failed"):
                r.execute(approve_public_readonly=True)


# ---------------------------------------------------------------------------
# TestDeliveryPackIntegration5N — delivery pack reads and integrates 5N modules
# ---------------------------------------------------------------------------

class TestDeliveryPackIntegration5N:
    def _build(self, tmp_path):
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        return pack.build(_DEMO_ID, output_dir=str(tmp_path / "delivery"))

    def _qa_report(self, tmp_path) -> str:
        self._build(tmp_path)
        return (tmp_path / "delivery" / "QA_Report.md").read_text(encoding="utf-8")

    def _evidence_index(self, tmp_path) -> str:
        self._build(tmp_path)
        return (tmp_path / "delivery" / "Evidence_Index.md").read_text(encoding="utf-8")

    def test_build_returns_manifest(self, tmp_path):
        from core.schemas.client_delivery import ClientDeliveryManifest
        assert isinstance(self._build(tmp_path), ClientDeliveryManifest)

    def test_manifest_approved_false(self, tmp_path):
        assert self._build(tmp_path).approved_for_client_delivery is False

    def test_manifest_human_review_true(self, tmp_path):
        assert self._build(tmp_path).human_review_required is True

    def test_manifest_auto_send_false(self, tmp_path):
        assert self._build(tmp_path).auto_send_to_client is False

    def test_manifest_raw_secrets_false(self, tmp_path):
        assert self._build(tmp_path).raw_secrets_included is False

    def test_qa_report_has_accessibility_row(self, tmp_path):
        assert "Accessibility" in self._qa_report(tmp_path)

    def test_qa_report_has_performance_row(self, tmp_path):
        assert "Performance" in self._qa_report(tmp_path)

    def test_qa_report_has_passive_security_row(self, tmp_path):
        assert "Passive security" in self._qa_report(tmp_path)

    def test_qa_report_planning_only_shows_generated_checks_label(self, tmp_path):
        content = self._qa_report(tmp_path)
        assert "Generated checks only" in content or "execution requires approval" in content

    def test_qa_report_executed_shows_executed_label(self, tmp_path):
        content = self._qa_report(tmp_path)
        # passive security fixture is "executed" — should show "Executed" or "executed"
        assert "Executed" in content

    def test_evidence_index_has_29_accessibility(self, tmp_path):
        assert "29_accessibility" in self._evidence_index(tmp_path)

    def test_evidence_index_has_30_performance(self, tmp_path):
        assert "30_performance" in self._evidence_index(tmp_path)

    def test_evidence_index_has_31_passive_security(self, tmp_path):
        assert "31_passive_security" in self._evidence_index(tmp_path)

    def test_evidence_index_shows_executed_for_sec(self, tmp_path):
        content = self._evidence_index(tmp_path)
        assert "executed" in content.lower()

    def test_evidence_index_shows_approval_required_for_a11y(self, tmp_path):
        content = self._evidence_index(tmp_path)
        assert "approval" in content.lower() or "planning_only" in content.lower()

    def test_qa_report_no_raw_credentials(self, tmp_path):
        content = self._qa_report(tmp_path).lower()
        assert "password:" not in content
        assert "api_key:" not in content
        assert "storagestate" not in content

    def test_qa_report_has_draft_notice(self, tmp_path):
        content = self._qa_report(tmp_path).lower()
        assert "draft" in content or "pending" in content

    def test_html_report_has_accessibility_content(self, tmp_path):
        self._build(tmp_path)
        content = (tmp_path / "delivery" / "QA_Report.html").read_text(encoding="utf-8")
        assert "Accessibility" in content

    def test_html_report_has_performance_content(self, tmp_path):
        self._build(tmp_path)
        content = (tmp_path / "delivery" / "QA_Report.html").read_text(encoding="utf-8")
        assert "Performance" in content


# ---------------------------------------------------------------------------
# TestZIPSafety5N — ZIP excludes blocked filenames, includes safe ones
# ---------------------------------------------------------------------------

class TestZIPSafety5N:
    def _zip_names(self, tmp_path):
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(tmp_path / "delivery"))
        zp = tmp_path / "delivery" / "client_delivery.zip"
        with zipfile.ZipFile(zp) as zf:
            return zf.namelist()

    def test_zip_exists_and_nonempty(self, tmp_path):
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(tmp_path / "delivery"))
        zp = tmp_path / "delivery" / "client_delivery.zip"
        assert zp.exists() and zp.stat().st_size > 0

    def test_zip_excludes_storagestate(self, tmp_path):
        d = tmp_path / "delivery"
        d.mkdir(parents=True, exist_ok=True)
        (d / "storageState.json").write_text("{}", encoding="utf-8")
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(d))
        with zipfile.ZipFile(d / "client_delivery.zip") as zf:
            names = zf.namelist()
        assert not any("storagestate" in n.lower() for n in names)

    def test_zip_excludes_env_file(self, tmp_path):
        d = tmp_path / "delivery"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".env").write_text("SECRET=abc", encoding="utf-8")
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(d))
        with zipfile.ZipFile(d / "client_delivery.zip") as zf:
            names = zf.namelist()
        assert ".env" not in names

    def test_zip_excludes_token_file(self, tmp_path):
        d = tmp_path / "delivery"
        d.mkdir(parents=True, exist_ok=True)
        (d / "auth_token.json").write_text("{}", encoding="utf-8")
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(d))
        with zipfile.ZipFile(d / "client_delivery.zip") as zf:
            names = zf.namelist()
        assert "auth_token.json" not in names

    def test_zip_excludes_auth_session_file(self, tmp_path):
        d = tmp_path / "delivery"
        d.mkdir(parents=True, exist_ok=True)
        (d / "authSession.json").write_text("{}", encoding="utf-8")
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(d))
        with zipfile.ZipFile(d / "client_delivery.zip") as zf:
            names = zf.namelist()
        assert not any("authsession" in n.lower() for n in names)

    def test_zip_excludes_credential_file(self, tmp_path):
        d = tmp_path / "delivery"
        d.mkdir(parents=True, exist_ok=True)
        (d / "credentials.json").write_text("{}", encoding="utf-8")
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(d))
        with zipfile.ZipFile(d / "client_delivery.zip") as zf:
            names = zf.namelist()
        assert "credentials.json" not in names

    def test_zip_excludes_itself(self, tmp_path):
        assert "client_delivery.zip" not in self._zip_names(tmp_path)

    def test_zip_contains_qa_report_md(self, tmp_path):
        assert "QA_Report.md" in self._zip_names(tmp_path)

    def test_zip_contains_evidence_index(self, tmp_path):
        assert "Evidence_Index.md" in self._zip_names(tmp_path)

    def test_zip_manifest_approved_false(self, tmp_path):
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(tmp_path / "delivery"))
        zp = tmp_path / "delivery" / "client_delivery.zip"
        with zipfile.ZipFile(zp) as zf:
            d = json.loads(zf.read("client_delivery_manifest.json").decode("utf-8"))
        assert d["approved_for_client_delivery"] is False
        assert d["human_review_required"] is True


# ---------------------------------------------------------------------------
# TestGoldenContent5N — report content is human-readable and accurate
# ---------------------------------------------------------------------------

class TestGoldenContent5N:
    def _report(self, tmp_path) -> str:
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(tmp_path / "delivery"))
        return (tmp_path / "delivery" / "QA_Report.md").read_text(encoding="utf-8")

    def test_report_contains_executive_summary(self, tmp_path):
        assert "Executive Summary" in self._report(tmp_path)

    def test_report_contains_scope_tested(self, tmp_path):
        assert "Scope Tested" in self._report(tmp_path)

    def test_report_contains_test_results(self, tmp_path):
        assert "Test Results" in self._report(tmp_path)

    def test_report_contains_evidence(self, tmp_path):
        assert "Evidence" in self._report(tmp_path)

    def test_report_contains_recommendations(self, tmp_path):
        assert "Recommendations" in self._report(tmp_path)

    def test_report_contains_next_steps(self, tmp_path):
        assert "Next Steps" in self._report(tmp_path)

    def test_report_no_password_value(self, tmp_path):
        content = self._report(tmp_path).lower()
        assert "password:" not in content
        assert "password=" not in content

    def test_report_no_api_key_value(self, tmp_path):
        assert "api_key:" not in self._report(tmp_path).lower()

    def test_report_no_storagestate(self, tmp_path):
        assert "storagestate" not in self._report(tmp_path).lower()

    def test_report_approved_false_stated(self, tmp_path):
        content = self._report(tmp_path)
        assert "No" in content or "false" in content.lower()

    def test_report_nonempty(self, tmp_path):
        assert len(self._report(tmp_path)) > 500

    def test_html_nonempty(self, tmp_path):
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(tmp_path / "delivery"))
        content = (tmp_path / "delivery" / "QA_Report.html").read_text(encoding="utf-8")
        assert len(content) > 500
        assert "<!DOCTYPE html>" in content

    def test_delivery_checklist_has_human_review(self, tmp_path):
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(tmp_path / "delivery"))
        content = (tmp_path / "delivery" / "Delivery_Checklist.md").read_text(encoding="utf-8")
        # checklist uses "sign-off" / "approved" / "approved_for_client_delivery"
        assert "sign-off" in content.lower() or "approved_for_client_delivery" in content or "not approved" in content.lower()

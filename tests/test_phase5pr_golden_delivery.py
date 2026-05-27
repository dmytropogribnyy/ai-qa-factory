"""Phase 5P-R tests — Golden client delivery pack from real demo fixtures.

Validates that ClientDeliveryPack produces a readable, client-quality output
when real artifacts from previous phases are present (fixtures/demo_client_delivery/).

Pipeline:
  fixtures/demo_client_delivery/ → ClientDeliveryPack → 10 delivery artifacts + ZIP
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

from core.client_delivery_pack import ClientDeliveryPack
from core.schemas.client_delivery import ClientDeliveryManifest

_FIXTURES_ROOT = Path(__file__).parent.parent / "fixtures"
_DEMO_ID = "demo_client_delivery"
_DEMO_DIR = _FIXTURES_ROOT / _DEMO_ID


# ---------------------------------------------------------------------------
# TestGoldenFixtures — fixture files exist and are valid
# ---------------------------------------------------------------------------

class TestGoldenFixtures:
    def test_demo_directory_exists(self):
        assert _DEMO_DIR.exists(), f"Missing: {_DEMO_DIR}"

    def test_qa_report_fixture_exists(self):
        assert (_DEMO_DIR / "14_qa_report" / "qa_report_summary.md").exists()

    def test_api_contract_fixture_exists(self):
        assert (_DEMO_DIR / "25_api_contract" / "api_contract_inventory.json").exists()

    def test_generated_smoke_spec_exists(self):
        assert (_DEMO_DIR / "26_generated_tests" / "api_smoke.generated.spec.ts").exists()

    def test_generated_schema_spec_exists(self):
        assert (_DEMO_DIR / "26_generated_tests" / "api_schema.generated.spec.ts").exists()

    def test_cicd_yml_exists(self):
        assert (_DEMO_DIR / "27_cicd" / "github-actions-qa-smoke.yml").exists()

    def test_api_contract_json_is_valid(self):
        raw = (_DEMO_DIR / "25_api_contract" / "api_contract_inventory.json").read_text(encoding="utf-8")
        d = json.loads(raw)
        assert d["total_endpoints"] > 0
        assert d["safe_readonly_count"] > 0
        assert d["raw_secrets_allowed"] is False
        assert d["human_review_required"] is True

    def test_api_contract_has_12_endpoints(self):
        d = json.loads(
            (_DEMO_DIR / "25_api_contract" / "api_contract_inventory.json").read_text(encoding="utf-8")
        )
        assert d["total_endpoints"] == 12

    def test_api_contract_spec_title(self):
        d = json.loads(
            (_DEMO_DIR / "25_api_contract" / "api_contract_inventory.json").read_text(encoding="utf-8")
        )
        assert d["spec_title"] == "Demo Client API"

    def test_cicd_yml_no_secrets_embedded(self):
        content = (_DEMO_DIR / "27_cicd" / "github-actions-qa-smoke.yml").read_text(encoding="utf-8")
        assert "password:" not in content.lower()
        assert "api_key:" not in content.lower()
        assert "deploy" not in content.lower()

    def test_cicd_yml_uses_github_secrets(self):
        content = (_DEMO_DIR / "27_cicd" / "github-actions-qa-smoke.yml").read_text(encoding="utf-8")
        assert "secrets." in content

    def test_smoke_spec_no_delete_tests(self):
        content = (_DEMO_DIR / "26_generated_tests" / "api_smoke.generated.spec.ts").read_text(encoding="utf-8")
        active = [ln for ln in content.splitlines() if "test(" in ln and "DELETE" in ln and not ln.strip().startswith("//")]
        assert len(active) == 0

    def test_qa_summary_mentions_browser_smoke(self):
        content = (_DEMO_DIR / "14_qa_report" / "qa_report_summary.md").read_text(encoding="utf-8")
        assert "browser" in content.lower() or "smoke" in content.lower()


# ---------------------------------------------------------------------------
# TestGoldenDeliveryBuild — build from fixtures produces full delivery pack
# ---------------------------------------------------------------------------

class TestGoldenDeliveryBuild:
    def _build(self, tmp_path):
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        return pack.build(_DEMO_ID, output_dir=str(tmp_path / "delivery"))

    def test_build_returns_manifest(self, tmp_path):
        assert isinstance(self._build(tmp_path), ClientDeliveryManifest)

    def test_build_project_id_correct(self, tmp_path):
        assert self._build(tmp_path).project_id == _DEMO_ID

    def test_build_10_artifacts(self, tmp_path):
        m = self._build(tmp_path)
        assert m.total_artifacts == 10

    def test_build_all_files_exist(self, tmp_path):
        self._build(tmp_path)
        d = tmp_path / "delivery"
        expected = [
            "QA_Report.md", "QA_Report.html", "Bug_Report.md", "Test_Cases.csv",
            "Risk_Matrix.md", "Recommendations.md", "Evidence_Index.md",
            "Delivery_Checklist.md", "client_delivery_manifest.json", "client_delivery.zip",
        ]
        for name in expected:
            assert (d / name).exists(), f"Missing: {name}"

    def test_build_secret_scan_passed(self, tmp_path):
        m = self._build(tmp_path)
        assert m.secret_scan.scan_passed is True

    def test_build_approved_false(self, tmp_path):
        assert self._build(tmp_path).approved_for_client_delivery is False

    def test_build_human_review_true(self, tmp_path):
        assert self._build(tmp_path).human_review_required is True

    def test_build_auto_send_false(self, tmp_path):
        assert self._build(tmp_path).auto_send_to_client is False

    def test_build_raw_secrets_false(self, tmp_path):
        assert self._build(tmp_path).raw_secrets_included is False


# ---------------------------------------------------------------------------
# TestGoldenQAReportContent — report is rich and data-driven from fixtures
# ---------------------------------------------------------------------------

class TestGoldenQAReportContent:
    def _report(self, tmp_path) -> str:
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(tmp_path / "delivery"))
        return (tmp_path / "delivery" / "QA_Report.md").read_text(encoding="utf-8")

    def test_contains_project_id(self, tmp_path):
        assert _DEMO_ID in self._report(tmp_path)

    def test_contains_executive_summary(self, tmp_path):
        assert "Executive Summary" in self._report(tmp_path)

    def test_contains_scope_tested(self, tmp_path):
        assert "Scope Tested" in self._report(tmp_path)

    def test_contains_test_results(self, tmp_path):
        assert "Test Results" in self._report(tmp_path)

    def test_contains_bugs_section(self, tmp_path):
        assert "Bugs" in self._report(tmp_path)

    def test_contains_risks_section(self, tmp_path):
        assert "Risks" in self._report(tmp_path)

    def test_contains_evidence_section(self, tmp_path):
        assert "Evidence" in self._report(tmp_path)

    def test_contains_recommendations(self, tmp_path):
        assert "Recommendations" in self._report(tmp_path)

    def test_contains_next_steps(self, tmp_path):
        assert "Next Steps" in self._report(tmp_path)

    def test_api_endpoint_count_present(self, tmp_path):
        assert "12" in self._report(tmp_path)

    def test_api_safe_count_present(self, tmp_path):
        content = self._report(tmp_path)
        assert "7" in content

    def test_api_blocked_count_present(self, tmp_path):
        content = self._report(tmp_path)
        assert "2" in content

    def test_generated_test_files_mentioned(self, tmp_path):
        content = self._report(tmp_path)
        assert "api_smoke.generated.spec.ts" in content

    def test_cicd_platform_mentioned(self, tmp_path):
        content = self._report(tmp_path)
        assert "GitHub Actions" in content

    def test_qa_summary_excerpt_included(self, tmp_path):
        content = self._report(tmp_path)
        assert "browser" in content.lower() or "smoke" in content.lower()

    def test_api_contract_title_in_evidence(self, tmp_path):
        content = self._report(tmp_path)
        assert "Demo Client API" in content

    def test_no_raw_password_value(self, tmp_path):
        content = self._report(tmp_path).lower()
        assert "password:" not in content
        assert "password=" not in content

    def test_no_api_key_value(self, tmp_path):
        assert "api_key:" not in self._report(tmp_path).lower()

    def test_no_storagestate_reference(self, tmp_path):
        assert "storagestate" not in self._report(tmp_path).lower()

    def test_draft_notice_present(self, tmp_path):
        content = self._report(tmp_path).lower()
        assert "draft" in content or "pending" in content

    def test_approved_false_stated(self, tmp_path):
        content = self._report(tmp_path)
        assert "No" in content or "false" in content.lower()


# ---------------------------------------------------------------------------
# TestGoldenHTMLReport — HTML is valid and contains required content
# ---------------------------------------------------------------------------

class TestGoldenHTMLReport:
    def _html(self, tmp_path) -> str:
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(tmp_path / "delivery"))
        return (tmp_path / "delivery" / "QA_Report.html").read_text(encoding="utf-8")

    def test_html_has_doctype(self, tmp_path):
        assert "<!DOCTYPE html>" in self._html(tmp_path)

    def test_html_has_html_tag(self, tmp_path):
        assert "<html" in self._html(tmp_path)

    def test_html_has_body_tag(self, tmp_path):
        assert "<body>" in self._html(tmp_path)

    def test_html_has_h1(self, tmp_path):
        assert "<h1>" in self._html(tmp_path)

    def test_html_has_h2(self, tmp_path):
        assert "<h2>" in self._html(tmp_path)

    def test_html_has_draft_notice(self, tmp_path):
        assert "DRAFT" in self._html(tmp_path) or "Not approved" in self._html(tmp_path)

    def test_html_contains_project_id(self, tmp_path):
        assert _DEMO_ID in self._html(tmp_path)

    def test_html_nonempty(self, tmp_path):
        assert len(self._html(tmp_path)) > 500


# ---------------------------------------------------------------------------
# TestGoldenZIPContents — ZIP has right files, excludes secrets
# ---------------------------------------------------------------------------

class TestGoldenZIPContents:
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

    def test_zip_contains_qa_report_md(self, tmp_path):
        assert "QA_Report.md" in self._zip_names(tmp_path)

    def test_zip_contains_qa_report_html(self, tmp_path):
        assert "QA_Report.html" in self._zip_names(tmp_path)

    def test_zip_contains_bug_report(self, tmp_path):
        assert "Bug_Report.md" in self._zip_names(tmp_path)

    def test_zip_contains_test_cases_csv(self, tmp_path):
        assert "Test_Cases.csv" in self._zip_names(tmp_path)

    def test_zip_contains_risk_matrix(self, tmp_path):
        assert "Risk_Matrix.md" in self._zip_names(tmp_path)

    def test_zip_contains_manifest(self, tmp_path):
        assert "client_delivery_manifest.json" in self._zip_names(tmp_path)

    def test_zip_excludes_itself(self, tmp_path):
        assert "client_delivery.zip" not in self._zip_names(tmp_path)

    def test_zip_excludes_storagestate(self, tmp_path):
        d = tmp_path / "delivery"
        d.mkdir(parents=True, exist_ok=True)
        (d / "storageState.json").write_text("{}", encoding="utf-8")
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(d))
        with zipfile.ZipFile(d / "client_delivery.zip") as zf:
            names = zf.namelist()
        assert "storageState.zip" not in names
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

    def test_zip_manifest_content_valid_json(self, tmp_path):
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(tmp_path / "delivery"))
        zp = tmp_path / "delivery" / "client_delivery.zip"
        with zipfile.ZipFile(zp) as zf:
            raw = zf.read("client_delivery_manifest.json").decode("utf-8")
        loaded = json.loads(raw)
        assert loaded["approved_for_client_delivery"] is False
        assert loaded["human_review_required"] is True


# ---------------------------------------------------------------------------
# TestGoldenManifest — manifest JSON correctness
# ---------------------------------------------------------------------------

class TestGoldenManifest:
    def _manifest_dict(self, tmp_path):
        pack = ClientDeliveryPack(outputs_root=str(_FIXTURES_ROOT))
        pack.build(_DEMO_ID, output_dir=str(tmp_path / "delivery"))
        raw = (tmp_path / "delivery" / "client_delivery_manifest.json").read_text(encoding="utf-8")
        return json.loads(raw)

    def test_manifest_project_id(self, tmp_path):
        assert self._manifest_dict(tmp_path)["project_id"] == _DEMO_ID

    def test_manifest_generated_at_not_empty(self, tmp_path):
        assert self._manifest_dict(tmp_path)["generated_at"] != ""

    def test_manifest_approved_false(self, tmp_path):
        assert self._manifest_dict(tmp_path)["approved_for_client_delivery"] is False

    def test_manifest_human_review_true(self, tmp_path):
        assert self._manifest_dict(tmp_path)["human_review_required"] is True

    def test_manifest_auto_send_false(self, tmp_path):
        assert self._manifest_dict(tmp_path)["auto_send_to_client"] is False

    def test_manifest_secret_scan_passed(self, tmp_path):
        d = self._manifest_dict(tmp_path)
        assert d["secret_scan"]["scan_passed"] is True

    def test_manifest_secret_scan_no_blocked(self, tmp_path):
        d = self._manifest_dict(tmp_path)
        assert d["secret_scan"]["issues_found"] == 0

    def test_manifest_raw_secrets_false(self, tmp_path):
        assert self._manifest_dict(tmp_path)["raw_secrets_included"] is False

    def test_manifest_json_round_trips(self, tmp_path):
        d = self._manifest_dict(tmp_path)
        assert json.loads(json.dumps(d))["project_id"] == _DEMO_ID

    def test_manifest_has_notes(self, tmp_path):
        d = self._manifest_dict(tmp_path)
        assert len(d.get("notes", [])) > 0

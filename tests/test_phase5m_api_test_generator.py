"""Phase 5M tests — APITestGenerator."""
from __future__ import annotations


from core.api_test_generator import APITestGenerator
from core.schemas.api_contract import (
    APIContractReport,
    APIEndpoint,
    GeneratedTestsReport,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_report(safe=2, approval=1, blocked=1) -> APIContractReport:
    endpoints = []
    for i in range(safe):
        endpoints.append(APIEndpoint(
            method="GET", path=f"/items/{i}",
            safety_classification="safe_readonly",
            safety_reason="method=GET read-only",
        ))
    for i in range(approval):
        endpoints.append(APIEndpoint(
            method="POST", path="/items",
            safety_classification="requires_approval",
            safety_reason="method=POST requires approval",
        ))
    for i in range(blocked):
        endpoints.append(APIEndpoint(
            method="POST", path="/payment/charge",
            safety_classification="blocked_by_default",
            safety_reason="method=POST path contains 'payment'",
        ))
    report = APIContractReport(
        project_id="test-proj",
        source_format="openapi_json",
        source_file="test.json",
        spec_title="Test API",
        base_url="https://api.example.com",
        endpoints=endpoints,
        total_endpoints=len(endpoints),
        safe_readonly_count=safe,
        requires_approval_count=approval,
        blocked_count=blocked,
    )
    return report


# ---------------------------------------------------------------------------
# Smoke spec generation
# ---------------------------------------------------------------------------

class TestGetSmokeContent:
    def test_smoke_contains_describe_block(self):
        gen = APITestGenerator()
        content = gen.get_smoke_content(_make_report())
        assert "test.describe" in content

    def test_smoke_contains_safe_endpoint(self):
        gen = APITestGenerator()
        content = gen.get_smoke_content(_make_report())
        assert "/items/0" in content

    def test_smoke_skips_blocked_endpoint(self):
        gen = APITestGenerator()
        content = gen.get_smoke_content(_make_report())
        # blocked endpoints are not active tests — they must not appear as test() calls
        assert "test('POST /payment/charge" not in content

    def test_smoke_contains_status_assertion(self):
        gen = APITestGenerator()
        content = gen.get_smoke_content(_make_report())
        assert "toBeLessThan(500)" in content

    def test_smoke_has_ts_reference(self):
        gen = APITestGenerator()
        content = gen.get_smoke_content(_make_report())
        assert "reference types" in content

    def test_smoke_has_playwright_import(self):
        gen = APITestGenerator()
        content = gen.get_smoke_content(_make_report())
        assert "@playwright/test" in content

    def test_smoke_shows_approval_required_comment(self):
        gen = APITestGenerator()
        content = gen.get_smoke_content(_make_report(approval=1))
        assert "requires_approval" in content.lower() or "SKIPPED" in content

    def test_smoke_base_url_used(self):
        gen = APITestGenerator()
        content = gen.get_smoke_content(_make_report())
        assert "BASE_URL" in content

    def test_smoke_empty_safe_endpoints(self):
        gen = APITestGenerator()
        content = gen.get_smoke_content(_make_report(safe=0, approval=0, blocked=0))
        assert "test.describe" in content  # still has outer shell


# ---------------------------------------------------------------------------
# Schema spec generation
# ---------------------------------------------------------------------------

class TestGetSchemaContent:
    def test_schema_contains_describe_block(self):
        gen = APITestGenerator()
        content = gen.get_schema_content(_make_report())
        assert "test.describe" in content

    def test_schema_contains_json_check(self):
        gen = APITestGenerator()
        content = gen.get_schema_content(_make_report())
        assert "json" in content.lower()

    def test_schema_safe_endpoints_present(self):
        gen = APITestGenerator()
        content = gen.get_schema_content(_make_report())
        assert "/items/0" in content


# ---------------------------------------------------------------------------
# Negative candidates
# ---------------------------------------------------------------------------

class TestGetNegativeContent:
    def test_negative_is_markdown(self):
        gen = APITestGenerator()
        content = gen.get_negative_content(_make_report())
        assert content.startswith("#")

    def test_negative_lists_safe_endpoints(self):
        gen = APITestGenerator()
        content = gen.get_negative_content(_make_report())
        assert "/items/0" in content

    def test_negative_has_blocked_section(self):
        gen = APITestGenerator()
        content = gen.get_negative_content(_make_report())
        assert "Blocked" in content

    def test_negative_has_approval_section(self):
        gen = APITestGenerator()
        content = gen.get_negative_content(_make_report())
        assert "approval" in content.lower()


# ---------------------------------------------------------------------------
# GeneratedTestsReport safety invariants
# ---------------------------------------------------------------------------

class TestGeneratedTestsReportSafetyInvariants:
    def test_executable_without_approval_false(self):
        gen = APITestGenerator()
        result = gen.generate(_make_report())
        assert result.executable_without_approval is False

    def test_raw_secrets_allowed_false(self):
        gen = APITestGenerator()
        result = gen.generate(_make_report())
        assert result.raw_secrets_allowed is False

    def test_human_review_required_true(self):
        gen = APITestGenerator()
        result = gen.generate(_make_report())
        assert result.human_review_required is True

    def test_client_delivery_allowed_false(self):
        gen = APITestGenerator()
        result = gen.generate(_make_report())
        assert result.client_delivery_allowed is False

    def test_invariants_survive_from_dict(self):
        gen = APITestGenerator()
        result = gen.generate(_make_report())
        d = result.to_dict()
        d["executable_without_approval"] = True
        d["human_review_required"] = False
        r2 = GeneratedTestsReport.from_dict(d)
        assert r2.executable_without_approval is False
        assert r2.human_review_required is True


# ---------------------------------------------------------------------------
# generate() method
# ---------------------------------------------------------------------------

class TestGenerateMethod:
    def test_generate_returns_report(self):
        gen = APITestGenerator()
        result = gen.generate(_make_report())
        assert isinstance(result, GeneratedTestsReport)

    def test_generate_counts_safe_endpoints(self):
        gen = APITestGenerator()
        result = gen.generate(_make_report(safe=3))
        assert result.safe_endpoints_covered == 3

    def test_generate_counts_blocked(self):
        gen = APITestGenerator()
        result = gen.generate(_make_report(blocked=2))
        assert result.skipped_blocked_endpoints == 2

    def test_generate_has_three_files(self):
        gen = APITestGenerator()
        result = gen.generate(_make_report())
        assert len(result.generated_files) == 3

    def test_generate_writes_files(self, tmp_path):
        gen = APITestGenerator()
        gen.generate(_make_report(), output_dir=str(tmp_path), write=True)
        assert (tmp_path / "api_smoke.generated.spec.ts").exists()
        assert (tmp_path / "api_schema.generated.spec.ts").exists()
        assert (tmp_path / "api_negative_candidates.md").exists()

    def test_generate_no_write_skips_files(self, tmp_path):
        gen = APITestGenerator()
        gen.generate(_make_report(), output_dir=str(tmp_path), write=False)
        assert not (tmp_path / "api_smoke.generated.spec.ts").exists()

    def test_project_id_preserved(self):
        gen = APITestGenerator()
        result = gen.generate(_make_report())
        assert result.project_id == "test-proj"

"""Phase 5M tests — APIContractImporter + classify_endpoint + safety invariants."""
from __future__ import annotations

import json
import textwrap

import pytest

from core.api_contract_importer import APIContractImporter, classify_endpoint
from core.schemas.api_contract import APIContractReport


# ---------------------------------------------------------------------------
# classify_endpoint
# ---------------------------------------------------------------------------

class TestClassifyEndpoint:
    def test_get_is_safe(self):
        level, _ = classify_endpoint("GET", "/users")
        assert level == "safe_readonly"

    def test_head_is_safe(self):
        level, _ = classify_endpoint("HEAD", "/health")
        assert level == "safe_readonly"

    def test_options_is_safe(self):
        level, _ = classify_endpoint("OPTIONS", "/api")
        assert level == "safe_readonly"

    def test_post_requires_approval(self):
        level, _ = classify_endpoint("POST", "/items")
        assert level == "requires_approval"

    def test_put_requires_approval(self):
        level, _ = classify_endpoint("PUT", "/items/1")
        assert level == "requires_approval"

    def test_patch_requires_approval(self):
        level, _ = classify_endpoint("PATCH", "/items/1")
        assert level == "requires_approval"

    def test_delete_method_payment_path_is_blocked(self):
        level, _ = classify_endpoint("DELETE", "/payment/cancel")
        assert level == "blocked_by_default"

    def test_post_payment_is_blocked(self):
        level, _ = classify_endpoint("POST", "/payment/charge")
        assert level == "blocked_by_default"

    def test_delete_admin_is_blocked(self):
        level, _ = classify_endpoint("DELETE", "/admin/users")
        assert level == "blocked_by_default"

    def test_post_refund_is_blocked(self):
        level, _ = classify_endpoint("POST", "/billing/refund")
        assert level == "blocked_by_default"

    def test_get_with_delete_in_path_requires_approval(self):
        level, _ = classify_endpoint("GET", "/delete-report")
        assert level == "requires_approval"

    def test_get_plain_health_is_safe(self):
        level, _ = classify_endpoint("GET", "/health")
        assert level == "safe_readonly"

    def test_get_plain_status_is_safe(self):
        level, _ = classify_endpoint("GET", "/api/v1/status")
        assert level == "safe_readonly"

    def test_post_users_requires_approval(self):
        level, _ = classify_endpoint("POST", "/users")
        assert level == "requires_approval"

    def test_reason_is_non_empty_string(self):
        _, reason = classify_endpoint("GET", "/products")
        assert isinstance(reason, str)
        assert len(reason) > 0

    def test_method_case_insensitive(self):
        level_lower, _ = classify_endpoint("get", "/products")
        level_upper, _ = classify_endpoint("GET", "/products")
        assert level_lower == level_upper


# ---------------------------------------------------------------------------
# APIContractImporter — OpenAPI JSON
# ---------------------------------------------------------------------------

_OPENAPI_JSON = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "servers": [{"url": "https://api.example.com/v1"}],
    "paths": {
        "/products": {
            "get": {"operationId": "listProducts", "summary": "List products", "tags": ["products"]},
            "post": {"operationId": "createProduct", "summary": "Create product"},
        },
        "/products/{id}": {
            "get": {"operationId": "getProduct", "summary": "Get product"},
            "delete": {"operationId": "deleteProduct", "summary": "Delete product"},
        },
        "/payment/charge": {
            "post": {"operationId": "chargePayment", "summary": "Charge"},
        },
    },
}


class TestAPIContractImporterOpenAPIJSON:
    def test_parses_title(self, tmp_path):
        spec = tmp_path / "api.json"
        spec.write_text(json.dumps(_OPENAPI_JSON), encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        assert report.spec_title == "Test API"

    def test_parses_version(self, tmp_path):
        spec = tmp_path / "api.json"
        spec.write_text(json.dumps(_OPENAPI_JSON), encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        assert report.spec_version == "1.0.0"

    def test_parses_base_url(self, tmp_path):
        spec = tmp_path / "api.json"
        spec.write_text(json.dumps(_OPENAPI_JSON), encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        assert "api.example.com" in report.base_url

    def test_total_endpoints(self, tmp_path):
        spec = tmp_path / "api.json"
        spec.write_text(json.dumps(_OPENAPI_JSON), encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        assert report.total_endpoints == 5

    def test_safe_count(self, tmp_path):
        spec = tmp_path / "api.json"
        spec.write_text(json.dumps(_OPENAPI_JSON), encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        assert report.safe_readonly_count == 2  # GET /products, GET /products/{id}

    def test_blocked_count(self, tmp_path):
        spec = tmp_path / "api.json"
        spec.write_text(json.dumps(_OPENAPI_JSON), encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        assert report.blocked_count >= 1  # POST /payment/charge

    def test_source_format_openapi_json(self, tmp_path):
        spec = tmp_path / "api.json"
        spec.write_text(json.dumps(_OPENAPI_JSON), encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        assert report.source_format == "openapi_json"

    def test_project_id_preserved(self, tmp_path):
        spec = tmp_path / "api.json"
        spec.write_text(json.dumps(_OPENAPI_JSON), encoding="utf-8")
        report = APIContractImporter().analyze("myproject", str(spec))
        assert report.project_id == "myproject"

    def test_endpoints_have_safety_classification(self, tmp_path):
        spec = tmp_path / "api.json"
        spec.write_text(json.dumps(_OPENAPI_JSON), encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        for ep in report.endpoints:
            assert ep.safety_classification in ("safe_readonly", "requires_approval", "blocked_by_default")

    def test_endpoints_have_method(self, tmp_path):
        spec = tmp_path / "api.json"
        spec.write_text(json.dumps(_OPENAPI_JSON), encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        for ep in report.endpoints:
            assert ep.method in ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS")


# ---------------------------------------------------------------------------
# APIContractImporter — OpenAPI YAML
# ---------------------------------------------------------------------------

_OPENAPI_YAML = textwrap.dedent("""\
    openapi: "3.0.0"
    info:
      title: YAML API
      version: "2.0"
    servers:
      - url: https://yaml.example.com
    paths:
      /items:
        get:
          summary: List items
        post:
          summary: Create item
      /admin/purge:
        delete:
          summary: Purge all
""")


class TestAPIContractImporterOpenAPIYAML:
    def test_parses_yaml_title(self, tmp_path):
        pytest.importorskip("yaml")
        spec = tmp_path / "api.yaml"
        spec.write_text(_OPENAPI_YAML, encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        assert report.spec_title == "YAML API"

    def test_yaml_format_detected(self, tmp_path):
        pytest.importorskip("yaml")
        spec = tmp_path / "api.yaml"
        spec.write_text(_OPENAPI_YAML, encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        assert report.source_format == "openapi_yaml"

    def test_yaml_blocked_purge(self, tmp_path):
        pytest.importorskip("yaml")
        spec = tmp_path / "api.yaml"
        spec.write_text(_OPENAPI_YAML, encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        blocked = [e for e in report.endpoints if e.safety_classification == "blocked_by_default"]
        assert len(blocked) >= 1


# ---------------------------------------------------------------------------
# APIContractImporter — Postman collection
# ---------------------------------------------------------------------------

_POSTMAN_COLLECTION = {
    "info": {
        "name": "Postman Suite",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json",
    },
    "item": [
        {
            "name": "Get Users",
            "request": {"method": "GET", "url": {"path": ["api", "users"]}},
        },
        {
            "name": "Create User",
            "request": {"method": "POST", "url": {"path": ["api", "users"]}},
        },
        {
            "name": "Delete User",
            "request": {"method": "DELETE", "url": {"path": ["api", "users", "1"]}},
        },
    ],
}


class TestAPIContractImporterPostman:
    def test_postman_format_detected(self, tmp_path):
        spec = tmp_path / "collection.json"
        spec.write_text(json.dumps(_POSTMAN_COLLECTION), encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        assert report.source_format == "postman_collection"

    def test_postman_total_endpoints(self, tmp_path):
        spec = tmp_path / "collection.json"
        spec.write_text(json.dumps(_POSTMAN_COLLECTION), encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        assert report.total_endpoints == 3

    def test_postman_get_is_safe(self, tmp_path):
        spec = tmp_path / "collection.json"
        spec.write_text(json.dumps(_POSTMAN_COLLECTION), encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        safe = [e for e in report.endpoints if e.safety_classification == "safe_readonly"]
        assert len(safe) == 1


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------

class TestAPIContractReportSafetyInvariants:
    def _make_report(self, tmp_path) -> APIContractReport:
        spec = tmp_path / "api.json"
        spec.write_text(json.dumps(_OPENAPI_JSON), encoding="utf-8")
        return APIContractImporter().analyze("proj", str(spec))

    def test_raw_secrets_allowed_false(self, tmp_path):
        r = self._make_report(tmp_path)
        assert r.raw_secrets_allowed is False

    def test_destructive_api_calls_allowed_false(self, tmp_path):
        r = self._make_report(tmp_path)
        assert r.destructive_api_calls_allowed is False

    def test_production_write_allowed_false(self, tmp_path):
        r = self._make_report(tmp_path)
        assert r.production_write_allowed is False

    def test_human_review_required_true(self, tmp_path):
        r = self._make_report(tmp_path)
        assert r.human_review_required is True

    def test_client_delivery_allowed_false(self, tmp_path):
        r = self._make_report(tmp_path)
        assert r.client_delivery_allowed is False

    def test_invariants_survive_from_dict(self, tmp_path):
        r = self._make_report(tmp_path)
        r2 = APIContractReport.from_dict(r.to_dict())
        assert r2.raw_secrets_allowed is False
        assert r2.destructive_api_calls_allowed is False
        assert r2.human_review_required is True

    def test_cannot_override_invariants_via_from_dict(self, tmp_path):
        r = self._make_report(tmp_path)
        d = r.to_dict()
        d["raw_secrets_allowed"] = True
        d["destructive_api_calls_allowed"] = True
        d["human_review_required"] = False
        r2 = APIContractReport.from_dict(d)
        assert r2.raw_secrets_allowed is False
        assert r2.destructive_api_calls_allowed is False
        assert r2.human_review_required is True


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------

class TestAPIContractImporterErrors:
    def test_missing_file_returns_error(self, tmp_path):
        report = APIContractImporter().analyze("proj", str(tmp_path / "missing.json"))
        assert len(report.parse_errors) > 0
        assert report.total_endpoints == 0

    def test_invalid_json_returns_error(self, tmp_path):
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json", encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(bad))
        assert len(report.parse_errors) > 0

    def test_empty_paths_returns_zero_endpoints(self, tmp_path):
        spec = tmp_path / "empty.json"
        spec.write_text(json.dumps({"openapi": "3.0.0", "info": {"title": "x", "version": "1"}, "paths": {}}), encoding="utf-8")
        report = APIContractImporter().analyze("proj", str(spec))
        assert report.total_endpoints == 0

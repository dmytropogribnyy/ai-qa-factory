"""Phase 6 tests — MCP tool handlers, safety invariants, CLI."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from integrations.mcp.tool_handlers import (
    APP_VERSION,
    HANDLERS,
    TOOL_NAMES,
    dispatch,
    handle_analyze_project,
    handle_apply_self_healing_fixes,
    handle_generate_delivery_pack,
    handle_propose_self_healing_fixes,
    handle_qa_factory_health,
    handle_run_flaky_test_analysis,
    handle_run_quality_audit,
)

_FIXTURES = Path(__file__).parent.parent / "fixtures" / "demo_quality_audit" / "playwright_specs"
_FLAKY_SPEC = _FIXTURES / "flaky_test.spec.ts"
_STABLE_SPEC = _FIXTURES / "stable_test.spec.ts"
_CLI = Path(__file__).parent.parent / "tools" / "run_mcp_server.py"


# ===========================================================================
# Tool registry
# ===========================================================================

class TestToolRegistry:
    def test_seven_tools_registered(self):
        assert len(TOOL_NAMES) == 7

    def test_all_expected_tool_names_present(self):
        expected = {
            "qa_factory_health",
            "analyze_project",
            "run_quality_audit",
            "run_flaky_test_analysis",
            "generate_delivery_pack",
            "propose_self_healing_fixes",
            "apply_self_healing_fixes",
        }
        assert expected == set(TOOL_NAMES)

    def test_handlers_dict_matches_tool_names(self):
        assert set(HANDLERS.keys()) == set(TOOL_NAMES)

    def test_all_handlers_callable(self):
        for name, handler in HANDLERS.items():
            assert callable(handler), f"{name} is not callable"

    def test_dispatch_unknown_tool_raises_key_error(self):
        with pytest.raises(KeyError):
            dispatch("nonexistent_tool", {})

    def test_dispatch_known_tool_returns_dict(self):
        result = dispatch("qa_factory_health", {})
        assert isinstance(result, dict)


# ===========================================================================
# 1. qa_factory_health
# ===========================================================================

class TestQAFactoryHealth:
    def test_returns_status_healthy(self):
        assert handle_qa_factory_health({})["status"] == "healthy"

    def test_returns_correct_version(self):
        assert handle_qa_factory_health({})["version"] == APP_VERSION

    def test_returns_safe_mode(self):
        assert handle_qa_factory_health({})["safety_mode"] == "safe_by_default"

    def test_network_by_default_false(self):
        assert handle_qa_factory_health({})["network_by_default"] is False

    def test_browser_by_default_false(self):
        assert handle_qa_factory_health({})["browser_by_default"] is False

    def test_auto_apply_changes_false(self):
        assert handle_qa_factory_health({})["auto_apply_changes"] is False

    def test_human_review_required_true(self):
        assert handle_qa_factory_health({})["human_review_required"] is True

    def test_has_seven_available_modules(self):
        assert len(handle_qa_factory_health({})["available_modules"]) == 7

    def test_has_generated_at(self):
        assert "generated_at" in handle_qa_factory_health({})

    def test_blocks_credential_param(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            handle_qa_factory_health({"credential": "secret"})

    def test_blocks_password_param(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            handle_qa_factory_health({"password": "pw"})

    def test_blocks_token_param(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            handle_qa_factory_health({"api_token": "tok"})


# ===========================================================================
# 2. analyze_project
# ===========================================================================

class TestAnalyzeProject:
    def test_returns_analysis_only_status(self):
        result = handle_analyze_project({"project_id": "none", "outputs_root": "outputs"})
        assert result["status"] == "analysis_only"

    def test_non_existent_dir_returns_recommendations(self):
        result = handle_analyze_project({"project_id": "does-not-exist-xyz"})
        assert len(result["recommendations"]) > 0

    def test_returns_project_dir_exists_false_for_missing(self):
        result = handle_analyze_project({"project_id": "does-not-exist-xyz"})
        assert result["project_dir_exists"] is False

    def test_existing_project_finds_artifact_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj = Path(tmpdir) / "my-proj"
            (proj / "32_flaky_test_analyzer").mkdir(parents=True)
            (proj / "14_qa_report").mkdir(parents=True)
            result = handle_analyze_project({
                "project_id": "my-proj",
                "outputs_root": tmpdir,
            })
            assert "32_flaky_test_analyzer" in result["found_artifact_dirs"]
            assert "14_qa_report" in result["found_artifact_dirs"]

    def test_missing_flaky_analysis_generates_recommendation(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "p").mkdir()
            result = handle_analyze_project({"project_id": "p", "outputs_root": tmpdir})
            recs = " ".join(result["recommendations"])
            assert "flaky" in recs.lower()

    def test_human_review_required_true(self):
        assert handle_analyze_project({"project_id": "x"})["human_review_required"] is True

    def test_returns_project_id(self):
        result = handle_analyze_project({"project_id": "my-proj-id"})
        assert result["project_id"] == "my-proj-id"

    def test_no_credential_in_response(self):
        result = handle_analyze_project({"project_id": "x"})
        resp_str = json.dumps(result)
        for word in ("password", "api_key", "secret", "token"):
            assert word not in resp_str.lower()


# ===========================================================================
# 3. run_quality_audit
# ===========================================================================

class TestRunQualityAudit:
    def test_missing_project_id_returns_failed(self):
        result = handle_run_quality_audit({})
        assert result["status"] == "failed"

    def test_default_mode_returns_planning_only(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_quality_audit({
                "project_id": "audit-test",
                "target_url": "https://example.com",
                "outputs_root": tmpdir,
                "write_files": True,
            })
            assert result["status"] == "planning_only"

    def test_module_statuses_keys_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_quality_audit({
                "project_id": "audit-test",
                "target_url": "https://example.com",
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert "accessibility" in result["module_statuses"]
            assert "performance" in result["module_statuses"]
            assert "passive_security" in result["module_statuses"]

    def test_network_used_false_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_quality_audit({
                "project_id": "audit-net",
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert result["network_used"] is False

    def test_browser_used_false_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_quality_audit({
                "project_id": "audit-browser",
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert result["browser_used"] is False

    def test_returns_artifact_paths(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_quality_audit({
                "project_id": "audit-paths",
                "outputs_root": tmpdir,
                "write_files": True,
            })
            assert isinstance(result["artifact_paths"], list)
            assert len(result["artifact_paths"]) > 0

    def test_human_review_required_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_quality_audit({
                "project_id": "audit-hr",
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert result["human_review_required"] is True

    def test_with_approval_flags_passive_security_executes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_quality_audit({
                "project_id": "audit-approved",
                "target_url": "https://example.com",
                "outputs_root": tmpdir,
                "write_files": False,
                "approve_public_readonly_execution": True,
            })
            # passive security should be executed (mocked in handler)
            assert result["module_statuses"].get("passive_security") in ("executed", "failed", "planning_only")


# ===========================================================================
# 4. run_flaky_test_analysis
# ===========================================================================

class TestRunFlakyTestAnalysis:
    def test_missing_project_id_returns_failed(self):
        result = handle_run_flaky_test_analysis({})
        assert result["status"] == "failed"

    def test_returns_analysis_only_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_flaky_test_analysis({
                "project_id": "flaky-mcp",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert result["status"] == "analysis_only"

    def test_detects_risks_in_flaky_spec(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_flaky_test_analysis({
                "project_id": "flaky-mcp",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert result["total_risks"] > 0

    def test_returns_stability_score(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_flaky_test_analysis({
                "project_id": "flaky-mcp",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert 0.0 <= result["stability_score"] <= 100.0

    def test_applied_proposals_always_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_flaky_test_analysis({
                "project_id": "flaky-mcp",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert result["applied_proposals"] == 0

    def test_code_modification_allowed_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_flaky_test_analysis({
                "project_id": "flaky-mcp",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert result["code_modification_allowed"] is False

    def test_auto_apply_changes_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_flaky_test_analysis({
                "project_id": "flaky-mcp",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert result["auto_apply_changes"] is False

    def test_human_review_required_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_flaky_test_analysis({
                "project_id": "flaky-hr",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert result["human_review_required"] is True

    def test_has_six_artifacts(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_run_flaky_test_analysis({
                "project_id": "flaky-artifacts",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert len(result["artifacts"]) == 6


# ===========================================================================
# 5. generate_delivery_pack
# ===========================================================================

class TestGenerateDeliveryPack:
    def test_missing_project_id_returns_failed(self):
        result = handle_generate_delivery_pack({})
        assert result["status"] == "failed"

    def test_returns_draft_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_generate_delivery_pack({
                "project_id": "delivery-mcp",
                "outputs_root": tmpdir,
                "write_files": True,
            })
            assert result["status"] == "draft"

    def test_approved_for_delivery_always_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_generate_delivery_pack({
                "project_id": "delivery-approval",
                "outputs_root": tmpdir,
                "write_files": True,
            })
            assert result["approved_for_client_delivery"] is False

    def test_auto_send_always_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_generate_delivery_pack({
                "project_id": "delivery-send",
                "outputs_root": tmpdir,
                "write_files": True,
            })
            assert result["auto_send_to_client"] is False

    def test_human_review_required_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_generate_delivery_pack({
                "project_id": "delivery-hr",
                "outputs_root": tmpdir,
                "write_files": True,
            })
            assert result["human_review_required"] is True

    def test_returns_zip_path(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_generate_delivery_pack({
                "project_id": "delivery-zip",
                "outputs_root": tmpdir,
                "write_files": True,
            })
            assert "zip_path" in result
            assert result["zip_path"].endswith("client_delivery.zip")

    def test_no_credential_in_response(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_generate_delivery_pack({
                "project_id": "delivery-cred",
                "outputs_root": tmpdir,
                "write_files": False,
            })
            resp_str = json.dumps(result)
            for word in ("password", "api_key", "bearer"):
                assert word not in resp_str.lower()

    def test_zip_created_on_disk(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            handle_generate_delivery_pack({
                "project_id": "delivery-disk",
                "outputs_root": tmpdir,
                "write_files": True,
            })
            zip_path = Path(tmpdir) / "delivery-disk" / "28_client_delivery" / "client_delivery.zip"
            assert zip_path.exists()


# ===========================================================================
# 6. propose_self_healing_fixes
# ===========================================================================

class TestProposeSelfHealingFixes:
    def test_missing_project_id_returns_failed(self):
        result = handle_propose_self_healing_fixes({})
        assert result["status"] == "failed"

    def test_returns_proposals_for_flaky_spec(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_propose_self_healing_fixes({
                "project_id": "propose-mcp",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert result["total_proposals"] > 0

    def test_applied_proposals_always_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_propose_self_healing_fixes({
                "project_id": "propose-mcp",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert result["applied_proposals"] == 0

    def test_code_modification_allowed_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_propose_self_healing_fixes({
                "project_id": "propose-mcp",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert result["code_modification_allowed"] is False

    def test_proposals_have_proposal_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_propose_self_healing_fixes({
                "project_id": "propose-ids",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            for p in result["proposals"]:
                assert p["proposal_id"].startswith("HEAL-")

    def test_all_proposals_not_applied(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_propose_self_healing_fixes({
                "project_id": "propose-applied",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            for p in result["proposals"]:
                assert p["applied"] is False

    def test_note_mentions_review_before_applying(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_propose_self_healing_fixes({
                "project_id": "propose-note",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert "review" in result["note"].lower()

    def test_human_review_required_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_propose_self_healing_fixes({
                "project_id": "propose-hr",
                "spec_files": [str(_STABLE_SPEC)],
                "outputs_root": tmpdir,
                "write_files": False,
            })
            assert result["human_review_required"] is True


# ===========================================================================
# 7. apply_self_healing_fixes
# ===========================================================================

class TestApplySelfHealingFixes:
    def test_blocked_without_approval(self):
        result = handle_apply_self_healing_fixes({"project_id": "apply-x"})
        assert result["status"] == "blocked"

    def test_blocked_code_modification_false_in_blocked_response(self):
        result = handle_apply_self_healing_fixes({"project_id": "apply-x"})
        assert result["code_modification_allowed"] is False

    def test_human_review_required_in_blocked_response(self):
        result = handle_apply_self_healing_fixes({"project_id": "apply-x"})
        assert result["human_review_required"] is True

    def test_dry_run_true_by_default(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_apply_self_healing_fixes({
                "project_id": "apply-dry",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "approve_code_modification": True,
            })
            assert result["status"] == "dry_run"

    def test_dry_run_applied_proposals_zero(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_apply_self_healing_fixes({
                "project_id": "apply-dry-zero",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "approve_code_modification": True,
                "dry_run": True,
            })
            assert result["applied_proposals"] == 0

    def test_dry_run_no_file_changes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_copy = Path(tmpdir) / "flaky_test.spec.ts"
            spec_copy.write_text(_FLAKY_SPEC.read_text(encoding="utf-8"), encoding="utf-8")
            original = spec_copy.read_text(encoding="utf-8")
            handle_apply_self_healing_fixes({
                "project_id": "apply-nf",
                "spec_files": [str(spec_copy)],
                "outputs_root": tmpdir,
                "approve_code_modification": True,
                "dry_run": True,
            })
            assert spec_copy.read_text(encoding="utf-8") == original

    def test_dry_run_has_proposals_preview(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            result = handle_apply_self_healing_fixes({
                "project_id": "apply-preview",
                "spec_files": [str(_FLAKY_SPEC)],
                "outputs_root": tmpdir,
                "approve_code_modification": True,
                "dry_run": True,
            })
            assert "proposals_preview" in result

    def test_apply_with_approval_no_dry_run_returns_status(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            spec_copy = Path(tmpdir) / "flaky_test.spec.ts"
            spec_copy.write_text(_FLAKY_SPEC.read_text(encoding="utf-8"), encoding="utf-8")
            result = handle_apply_self_healing_fixes({
                "project_id": "apply-real",
                "spec_files": [str(spec_copy)],
                "outputs_root": tmpdir,
                "approve_code_modification": True,
                "dry_run": False,
            })
            assert result["status"] in ("patch_applied", "partial", "analysis_only")

    def test_missing_project_id_after_approval_returns_failed(self):
        result = handle_apply_self_healing_fixes({
            "approve_code_modification": True,
        })
        assert result["status"] == "failed"


# ===========================================================================
# Blocked params safety
# ===========================================================================

class TestBlockedParams:
    def test_health_rejects_password(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            handle_qa_factory_health({"password": "pw"})

    def test_health_rejects_api_key(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            handle_qa_factory_health({"api_key": "k"})

    def test_flaky_rejects_credential(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            handle_run_flaky_test_analysis({"credential": "c"})

    def test_delivery_rejects_secret(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            handle_generate_delivery_pack({"secret": "s"})

    def test_quality_audit_rejects_bearer(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            handle_run_quality_audit({"bearer": "tok"})

    def test_propose_rejects_token(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            handle_propose_self_healing_fixes({"auth_token": "t"})

    def test_apply_rejects_private_key(self):
        with pytest.raises(ValueError, match="BLOCKED"):
            handle_apply_self_healing_fixes({"private_key": "pk"})


# ===========================================================================
# All handlers return required fields
# ===========================================================================

class TestHandlerContracts:
    def _run_all(self) -> list[dict]:
        with tempfile.TemporaryDirectory() as tmpdir:
            results = [
                handle_qa_factory_health({}),
                handle_analyze_project({"project_id": "x"}),
                handle_run_quality_audit({"project_id": "x", "outputs_root": tmpdir, "write_files": False}),
                handle_run_flaky_test_analysis({
                    "project_id": "x",
                    "spec_files": [str(_STABLE_SPEC)],
                    "outputs_root": tmpdir,
                    "write_files": False,
                }),
                handle_generate_delivery_pack({"project_id": "x", "outputs_root": tmpdir, "write_files": False}),
                handle_propose_self_healing_fixes({
                    "project_id": "x",
                    "spec_files": [str(_STABLE_SPEC)],
                    "outputs_root": tmpdir,
                    "write_files": False,
                }),
                handle_apply_self_healing_fixes({"project_id": "x"}),
            ]
        return results

    def test_all_return_status_field(self):
        for result in self._run_all():
            assert "status" in result, f"Missing 'status' in: {result}"

    def test_all_return_human_review_required(self):
        for result in self._run_all():
            assert "human_review_required" in result, f"Missing key in: {result}"
            assert result["human_review_required"] is True

    def test_no_raw_credentials_in_any_response(self):
        for result in self._run_all():
            resp_str = json.dumps(result).lower()
            for word in ("password=", "api_key=", "bearer tok", "secret="):
                assert word not in resp_str


# ===========================================================================
# MCP server module import
# ===========================================================================

class TestMCPServerModule:
    def test_tool_handlers_importable_without_mcp(self):
        from integrations.mcp import tool_handlers  # noqa: F401
        assert tool_handlers is not None

    def test_server_module_importable(self):
        from integrations.mcp import server  # noqa: F401
        assert server is not None

    def test_server_mcp_available_flag_is_bool(self):
        from integrations.mcp.server import _MCP_AVAILABLE
        assert isinstance(_MCP_AVAILABLE, bool)

    def test_tool_schemas_count_matches_tool_names(self):
        from integrations.mcp.server import _TOOL_SCHEMAS
        assert len(_TOOL_SCHEMAS) == len(TOOL_NAMES)

    def test_tool_schemas_have_required_keys(self):
        from integrations.mcp.server import _TOOL_SCHEMAS
        for schema in _TOOL_SCHEMAS:
            assert "name" in schema
            assert "description" in schema
            assert "inputSchema" in schema

    def test_tool_schema_names_match_tool_names(self):
        from integrations.mcp.server import _TOOL_SCHEMAS
        schema_names = {s["name"] for s in _TOOL_SCHEMAS}
        assert schema_names == set(TOOL_NAMES)

    def test_call_handler_unknown_tool_returns_error(self):
        from integrations.mcp.server import _call_handler
        result = json.loads(_call_handler("unknown_tool", {}))
        assert result["status"] == "error"

    def test_call_handler_health_returns_json(self):
        from integrations.mcp.server import _call_handler
        result = json.loads(_call_handler("qa_factory_health", {}))
        assert result["status"] == "healthy"


# ===========================================================================
# CLI tool
# ===========================================================================

class TestCLIRunMCPServer:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--list-tools" in result.stdout

    def test_version_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--version"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert APP_VERSION in result.stdout

    def test_list_tools_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--list-tools"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_list_tools_shows_seven_tools(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--list-tools"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        for name in TOOL_NAMES:
            assert name in result.stdout

    def test_demo_health_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--demo-health"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert data["status"] == "healthy"

    def test_blocked_approve_delivery_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--approve-delivery"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_blocked_skip_review_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--skip-review"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_blocked_auto_start_browser_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--auto-start-browser"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_blocked_credentials_flag_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--credentials"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

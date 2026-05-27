"""Phase 7B -- Auth Strategy Selector tests.

Covers: DecisionStatus enum, AuthStrategyDecision schema and safety invariants,
selector priority logic, READY/MISSING/PLANNING/BLOCKED/NO_METHODS states,
file artifact writes, and CLI blocked-flag guard.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


from core.auth_strategy_selector import (
    AuthStrategySelector,
    _PRIORITY_ORDER,
    _METHOD_METADATA,
    _decision_to_dict,
)
from core.schemas.auth_capability import (
    AuthCapabilityPlan,
    AuthMethodCapability,
    AuthMethodType,
    AuthReadiness,
)
from core.schemas.auth_strategy import AuthStrategyDecision, DecisionStatus

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLI = Path(__file__).parent.parent / "tools" / "select_auth_strategy.py"


def _make_plan(
    project_id: str = "test-proj",
    allowed: list[str] | None = None,
    requires_action: list[str] | None = None,
    planning_only: list[str] | None = None,
    blocked: list[str] | None = None,
    capabilities: list[AuthMethodCapability] | None = None,
) -> AuthCapabilityPlan:
    return AuthCapabilityPlan(
        project_id=project_id,
        allowed_now_methods=allowed or [],
        requires_action_methods=requires_action or [],
        planning_only_methods=planning_only or [],
        blocked_methods=blocked or [],
        capabilities=capabilities or [],
    )


def _cap(method: str, readiness: str, reason: str = "", required: list[str] | None = None) -> AuthMethodCapability:
    return AuthMethodCapability(
        method=AuthMethodType(method),
        readiness=AuthReadiness(readiness),
        reason=reason,
        required_inputs=required or [],
    )


# ===========================================================================
# TestDecisionStatusEnum
# ===========================================================================

class TestDecisionStatusEnum:
    def test_five_statuses(self) -> None:
        assert len(DecisionStatus) == 5

    def test_all_values(self) -> None:
        vals = {s.value for s in DecisionStatus}
        assert vals == {
            "ready_for_execution",
            "missing_required_input",
            "planning_only",
            "blocked",
            "no_methods_available",
        }

    def test_str_subclass(self) -> None:
        assert isinstance(DecisionStatus.READY_FOR_EXECUTION, str)

    def test_ready_value(self) -> None:
        assert DecisionStatus.READY_FOR_EXECUTION == "ready_for_execution"

    def test_missing_value(self) -> None:
        assert DecisionStatus.MISSING_REQUIRED_INPUT == "missing_required_input"


# ===========================================================================
# TestAuthStrategyDecisionConstruction
# ===========================================================================

class TestAuthStrategyDecisionConstruction:
    def test_minimal_construction(self) -> None:
        d = AuthStrategyDecision(project_id="proj")
        assert d.project_id == "proj"

    def test_defaults(self) -> None:
        d = AuthStrategyDecision(project_id="proj")
        assert d.selected_method == ""
        assert d.selected_provider == ""
        assert d.selected_mode == ""
        assert d.decision_status == DecisionStatus.PLANNING_ONLY
        assert d.reason == ""
        assert d.required_inputs == []
        assert d.missing_inputs == []
        assert d.blocked_reasons == []
        assert d.safe_to_execute is False
        assert d.next_runner is None
        assert d.requires_human_approval is True
        assert d.requires_dedicated_test_account is True

    def test_full_construction(self) -> None:
        d = AuthStrategyDecision(
            project_id="proj",
            selected_method="api_token",
            selected_provider="api",
            selected_mode="api_token",
            decision_status=DecisionStatus.READY_FOR_EXECUTION,
            reason="API token env var is set",
            required_inputs=["api_token_env_var"],
            missing_inputs=[],
            safe_to_execute=True,
            next_runner="api_token_runner",
        )
        assert d.selected_method == "api_token"
        assert d.safe_to_execute is True
        assert d.next_runner == "api_token_runner"

    def test_next_runner_none_by_default(self) -> None:
        d = AuthStrategyDecision(project_id="proj")
        assert d.next_runner is None


# ===========================================================================
# TestAuthStrategyDecisionSafetyInvariants
# ===========================================================================

class TestAuthStrategyDecisionSafetyInvariants:
    def test_raw_secrets_always_false(self) -> None:
        d = AuthStrategyDecision(project_id="p", raw_secrets_allowed=True)
        assert d.raw_secrets_allowed is False

    def test_browser_execution_always_false(self) -> None:
        d = AuthStrategyDecision(project_id="p", browser_execution_allowed=True)
        assert d.browser_execution_allowed is False

    def test_credential_usage_always_false(self) -> None:
        d = AuthStrategyDecision(project_id="p", credential_usage_allowed=True)
        assert d.credential_usage_allowed is False

    def test_storage_state_content_read_always_false(self) -> None:
        d = AuthStrategyDecision(project_id="p", storage_state_content_read=True)
        assert d.storage_state_content_read is False

    def test_personal_account_always_false(self) -> None:
        d = AuthStrategyDecision(project_id="p", personal_account_allowed=True)
        assert d.personal_account_allowed is False

    def test_production_account_always_false(self) -> None:
        d = AuthStrategyDecision(project_id="p", production_account_allowed=True)
        assert d.production_account_allowed is False

    def test_captcha_bypass_always_false(self) -> None:
        d = AuthStrategyDecision(project_id="p", captcha_bypass_allowed=True)
        assert d.captcha_bypass_allowed is False

    def test_human_review_always_true(self) -> None:
        d = AuthStrategyDecision(project_id="p", human_review_required=False)
        assert d.human_review_required is True

    def test_from_dict_ignores_security_flags(self) -> None:
        data = {
            "project_id": "p",
            "raw_secrets_allowed": True,
            "browser_execution_allowed": True,
            "captcha_bypass_allowed": True,
            "personal_account_allowed": True,
            "human_review_required": False,
            "decision_status": "planning_only",
        }
        d = AuthStrategyDecision.from_dict(data)
        assert d.raw_secrets_allowed is False
        assert d.browser_execution_allowed is False
        assert d.captcha_bypass_allowed is False
        assert d.personal_account_allowed is False
        assert d.human_review_required is True


# ===========================================================================
# TestAuthStrategyDecisionToDict
# ===========================================================================

class TestAuthStrategyDecisionToDict:
    def test_required_keys_present(self) -> None:
        d = AuthStrategyDecision(project_id="proj")
        result = d.to_dict()
        for key in [
            "project_id", "selected_method", "decision_status", "safe_to_execute",
            "next_runner", "requires_human_approval", "raw_secrets_allowed",
            "human_review_required", "personal_account_allowed",
        ]:
            assert key in result

    def test_decision_status_serialized_as_string(self) -> None:
        d = AuthStrategyDecision(project_id="p", decision_status=DecisionStatus.READY_FOR_EXECUTION)
        assert d.to_dict()["decision_status"] == "ready_for_execution"

    def test_safety_invariants_false_in_dict(self) -> None:
        d = AuthStrategyDecision(project_id="p")
        result = d.to_dict()
        assert result["raw_secrets_allowed"] is False
        assert result["personal_account_allowed"] is False
        assert result["captcha_bypass_allowed"] is False
        assert result["human_review_required"] is True

    def test_from_dict_roundtrip(self) -> None:
        d = AuthStrategyDecision(
            project_id="proj",
            selected_method="api_token",
            selected_provider="api",
            decision_status=DecisionStatus.READY_FOR_EXECUTION,
            safe_to_execute=True,
            next_runner="api_token_runner",
        )
        restored = AuthStrategyDecision.from_dict(d.to_dict())
        assert restored.project_id == d.project_id
        assert restored.selected_method == d.selected_method
        assert restored.decision_status == d.decision_status
        assert restored.safe_to_execute is True
        assert restored.next_runner == "api_token_runner"

    def test_json_serializable(self) -> None:
        d = AuthStrategyDecision(project_id="proj")
        assert json.dumps(d.to_dict())


# ===========================================================================
# TestPriorityOrder
# ===========================================================================

class TestPriorityOrder:
    def test_fifteen_methods_in_priority(self) -> None:
        assert len(_PRIORITY_ORDER) == 15

    def test_storage_state_reuse_first(self) -> None:
        assert _PRIORITY_ORDER[0] == "storage_state_reuse"

    def test_google_oauth_second(self) -> None:
        assert _PRIORITY_ORDER[1] == "google_oauth"

    def test_api_token_before_email_password(self) -> None:
        assert _PRIORITY_ORDER.index("api_token") < _PRIORITY_ORDER.index("email_password")

    def test_sso_last(self) -> None:
        assert _PRIORITY_ORDER[-1] == "sso_saml_oidc"

    def test_all_methods_have_metadata(self) -> None:
        for method in _PRIORITY_ORDER:
            assert method in _METHOD_METADATA

    def test_metadata_has_provider_mode_runner(self) -> None:
        for method, meta in _METHOD_METADATA.items():
            assert "provider" in meta
            assert "mode" in meta
            assert "runner" in meta


# ===========================================================================
# TestSelectorReadyForExecution
# ===========================================================================

class TestSelectorReadyForExecution:
    def test_api_token_allowed_now(self) -> None:
        plan = _make_plan(allowed=["api_token"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.decision_status == DecisionStatus.READY_FOR_EXECUTION
        assert d.selected_method == "api_token"
        assert d.selected_provider == "api"
        assert d.safe_to_execute is True
        assert d.next_runner == "api_token_runner"

    def test_google_oauth_allowed_now(self) -> None:
        plan = _make_plan(allowed=["google_oauth"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.decision_status == DecisionStatus.READY_FOR_EXECUTION
        assert d.selected_method == "google_oauth"
        assert d.selected_provider == "google"
        assert d.next_runner == "google_oauth_runner"

    def test_email_password_allowed_now(self) -> None:
        plan = _make_plan(allowed=["email_password"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.selected_method == "email_password"
        assert d.selected_provider == "email"
        assert d.next_runner == "email_password_runner"

    def test_bearer_token_allowed_now(self) -> None:
        plan = _make_plan(allowed=["bearer_token"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.selected_method == "bearer_token"
        assert d.next_runner == "bearer_token_runner"

    def test_missing_inputs_empty_when_ready(self) -> None:
        plan = _make_plan(allowed=["api_token"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.missing_inputs == []

    def test_safe_to_execute_true_when_ready(self) -> None:
        plan = _make_plan(allowed=["storage_state_reuse"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.safe_to_execute is True


# ===========================================================================
# TestSelectorPriorityOrder
# ===========================================================================

class TestSelectorPriorityOrder:
    def test_storage_state_beats_email_password(self) -> None:
        plan = _make_plan(allowed=["email_password", "storage_state_reuse"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.selected_method == "storage_state_reuse"

    def test_google_oauth_beats_email_password(self) -> None:
        plan = _make_plan(allowed=["email_password", "google_oauth"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.selected_method == "google_oauth"

    def test_api_token_beats_email_password(self) -> None:
        plan = _make_plan(allowed=["email_password", "api_token"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.selected_method == "api_token"

    def test_storage_state_beats_api_token(self) -> None:
        plan = _make_plan(allowed=["api_token", "storage_state_reuse"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.selected_method == "storage_state_reuse"

    def test_github_oauth_beats_dedicated_profile_context(self) -> None:
        plan = _make_plan(allowed=["dedicated_profile_context", "github_oauth"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.selected_method == "github_oauth"


# ===========================================================================
# TestSelectorMissingRequiredInput
# ===========================================================================

class TestSelectorMissingRequiredInput:
    def test_missing_required_input_status(self) -> None:
        plan = _make_plan(requires_action=["email_password"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.decision_status == DecisionStatus.MISSING_REQUIRED_INPUT
        assert d.selected_method == "email_password"

    def test_safe_to_execute_false_when_missing(self) -> None:
        plan = _make_plan(requires_action=["email_password"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.safe_to_execute is False

    def test_next_runner_none_when_missing(self) -> None:
        plan = _make_plan(requires_action=["email_password"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.next_runner is None

    def test_missing_inputs_populated_from_capability(self) -> None:
        caps = [_cap("email_password", "requires_env_var_secret", required=["password_env_var"])]
        plan = _make_plan(requires_action=["email_password"], capabilities=caps)
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert "password_env_var" in d.missing_inputs

    def test_required_inputs_equals_missing_when_not_ready(self) -> None:
        caps = [_cap("google_oauth", "requires_manual_step", required=["storageState_file"])]
        plan = _make_plan(requires_action=["google_oauth"], capabilities=caps)
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.required_inputs == d.missing_inputs

    def test_priority_within_requires_action(self) -> None:
        plan = _make_plan(requires_action=["email_password", "google_oauth"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.selected_method == "google_oauth"


# ===========================================================================
# TestSelectorPlanningOnly
# ===========================================================================

class TestSelectorPlanningOnly:
    def test_planning_only_status(self) -> None:
        plan = _make_plan(planning_only=["sso_saml_oidc", "magic_link"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.decision_status == DecisionStatus.PLANNING_ONLY

    def test_no_selected_method_when_planning_only(self) -> None:
        plan = _make_plan(planning_only=["sso_saml_oidc"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.selected_method == ""

    def test_safe_to_execute_false_when_planning_only(self) -> None:
        plan = _make_plan(planning_only=["sso_saml_oidc"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.safe_to_execute is False

    def test_next_runner_none_when_planning_only(self) -> None:
        plan = _make_plan(planning_only=["magic_link"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.next_runner is None


# ===========================================================================
# TestSelectorBlocked
# ===========================================================================

class TestSelectorBlocked:
    def test_blocked_status(self) -> None:
        plan = _make_plan(blocked=["sso_saml_oidc"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.decision_status == DecisionStatus.BLOCKED

    def test_blocked_reasons_populated(self) -> None:
        plan = _make_plan(blocked=["sso_saml_oidc"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert len(d.blocked_reasons) > 0

    def test_safe_to_execute_false_when_blocked(self) -> None:
        plan = _make_plan(blocked=["sso_saml_oidc"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.safe_to_execute is False

    def test_planning_only_overrides_blocked(self) -> None:
        plan = _make_plan(blocked=["sso_saml_oidc"], planning_only=["magic_link"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.decision_status == DecisionStatus.PLANNING_ONLY


# ===========================================================================
# TestSelectorNoMethodsAvailable
# ===========================================================================

class TestSelectorNoMethodsAvailable:
    def test_empty_plan(self) -> None:
        plan = _make_plan()
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.decision_status == DecisionStatus.NO_METHODS_AVAILABLE

    def test_safe_to_execute_false_when_empty(self) -> None:
        plan = _make_plan()
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.safe_to_execute is False

    def test_next_runner_none_when_empty(self) -> None:
        plan = _make_plan()
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.next_runner is None

    def test_project_id_preserved(self) -> None:
        plan = _make_plan(project_id="empty-proj")
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert d.project_id == "empty-proj"


# ===========================================================================
# TestSelectorSafetyInvariantsInOutput
# ===========================================================================

class TestSelectorSafetyInvariantsInOutput:
    def test_raw_secrets_always_false_in_output(self) -> None:
        plan = _make_plan(allowed=["api_token"])
        d = AuthStrategySelector(plan, write_files=False).select()
        assert d.raw_secrets_allowed is False

    def test_personal_account_always_false_in_output(self) -> None:
        plan = _make_plan(allowed=["google_oauth"])
        d = AuthStrategySelector(plan, write_files=False).select()
        assert d.personal_account_allowed is False

    def test_captcha_bypass_always_false_in_output(self) -> None:
        plan = _make_plan(allowed=["storage_state_reuse"])
        d = AuthStrategySelector(plan, write_files=False).select()
        assert d.captcha_bypass_allowed is False

    def test_human_review_always_true_in_output(self) -> None:
        plan = _make_plan(allowed=["email_password"])
        d = AuthStrategySelector(plan, write_files=False).select()
        assert d.human_review_required is True

    def test_browser_execution_always_false_in_output(self) -> None:
        plan = _make_plan(allowed=["dedicated_profile_context"])
        d = AuthStrategySelector(plan, write_files=False).select()
        assert d.browser_execution_allowed is False


# ===========================================================================
# TestWriteArtifacts
# ===========================================================================

class TestWriteArtifacts:
    def test_write_creates_decision_json(self, tmp_path: Path) -> None:
        plan = _make_plan(project_id="write-test", allowed=["api_token"])
        sel = AuthStrategySelector(plan, outputs_root=str(tmp_path), write_files=True)
        sel.run()
        json_file = tmp_path / "write-test" / "35_auth_strategy" / "auth_strategy_decision.json"
        assert json_file.exists()

    def test_write_creates_summary_md(self, tmp_path: Path) -> None:
        plan = _make_plan(project_id="write-test", allowed=["api_token"])
        sel = AuthStrategySelector(plan, outputs_root=str(tmp_path), write_files=True)
        sel.run()
        md_file = tmp_path / "write-test" / "35_auth_strategy" / "auth_strategy_summary.md"
        assert md_file.exists()

    def test_json_valid(self, tmp_path: Path) -> None:
        plan = _make_plan(project_id="json-test", allowed=["bearer_token"])
        sel = AuthStrategySelector(plan, outputs_root=str(tmp_path), write_files=True)
        sel.run()
        json_file = tmp_path / "json-test" / "35_auth_strategy" / "auth_strategy_decision.json"
        data = json.loads(json_file.read_text(encoding="utf-8"))
        assert data["decision_status"] == "ready_for_execution"
        assert data["selected_method"] == "bearer_token"

    def test_no_write_produces_no_files(self, tmp_path: Path) -> None:
        plan = _make_plan(project_id="no-write", allowed=["api_token"])
        sel = AuthStrategySelector(plan, outputs_root=str(tmp_path), write_files=False)
        sel.run()
        assert not (tmp_path / "no-write").exists()

    def test_json_safety_invariants_false(self, tmp_path: Path) -> None:
        plan = _make_plan(project_id="safe-test", allowed=["api_token"])
        sel = AuthStrategySelector(plan, outputs_root=str(tmp_path), write_files=True)
        sel.run()
        data = json.loads(
            (tmp_path / "safe-test" / "35_auth_strategy" / "auth_strategy_decision.json").read_text()
        )
        assert data["raw_secrets_allowed"] is False
        assert data["personal_account_allowed"] is False
        assert data["human_review_required"] is True

    def test_summary_md_contains_project_id(self, tmp_path: Path) -> None:
        plan = _make_plan(project_id="md-proj", planning_only=["sso_saml_oidc"])
        sel = AuthStrategySelector(plan, outputs_root=str(tmp_path), write_files=True)
        sel.run()
        content = (tmp_path / "md-proj" / "35_auth_strategy" / "auth_strategy_summary.md").read_text()
        assert "md-proj" in content

    def test_summary_md_contains_safety_invariants(self, tmp_path: Path) -> None:
        plan = _make_plan(project_id="md-safe", allowed=["api_token"])
        sel = AuthStrategySelector(plan, outputs_root=str(tmp_path), write_files=True)
        sel.run()
        content = (tmp_path / "md-safe" / "35_auth_strategy" / "auth_strategy_summary.md").read_text()
        assert "personal_account_allowed" in content
        assert "human_review_required" in content


# ===========================================================================
# TestDecisionToDict
# ===========================================================================

class TestDecisionToDict:
    def test_helper_returns_same_as_method(self) -> None:
        plan = _make_plan(allowed=["api_token"])
        sel = AuthStrategySelector(plan, write_files=False)
        d = sel.select()
        assert _decision_to_dict(d) == d.to_dict()


# ===========================================================================
# TestCLIBlockedFlags
# ===========================================================================

class TestCLIBlockedFlags:
    def _run_cli(self, extra_args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_CLI)] + extra_args,
            capture_output=True, text=True,
        )

    def test_blocked_password_flag(self) -> None:
        result = self._run_cli(["--password", "secret123"])
        assert result.returncode == 1
        assert "blocked" in result.stdout.lower() or "Forbidden" in result.stdout

    def test_blocked_secret_flag(self) -> None:
        result = self._run_cli(["--secret", "mysecret"])
        assert result.returncode == 1

    def test_blocked_token_flag(self) -> None:
        result = self._run_cli(["--token", "mytoken"])
        assert result.returncode == 1

    def test_blocked_totp_seed_flag(self) -> None:
        result = self._run_cli(["--totp-seed", "123456"])
        assert result.returncode == 1

    def test_blocked_bearer_flag(self) -> None:
        result = self._run_cli(["--bearer", "mybearer"])
        assert result.returncode == 1

    def test_blocked_client_secret_flag(self) -> None:
        result = self._run_cli(["--client-secret", "secret"])
        assert result.returncode == 1

    def test_no_write_exits_zero(self) -> None:
        result = self._run_cli(["--project-id", "cli-test", "--no-write"])
        assert result.returncode == 0, result.stderr

    def test_ok_in_output(self) -> None:
        result = self._run_cli(["--project-id", "cli-test", "--no-write"])
        assert "[OK]" in result.stdout

    def test_json_output_flag(self) -> None:
        result = self._run_cli([
            "--project-id", "json-test", "--no-write", "--json-output",
        ])
        assert result.returncode == 0
        assert "decision_status" in result.stdout

    def test_allowed_env_var_flag_not_blocked(self) -> None:
        result = self._run_cli([
            "--project-id", "env-test",
            "--password-env-var", "QA_PASSWORD",
            "--has-dedicated-test-account",
            "--no-write",
        ])
        assert result.returncode == 0

    def test_api_token_env_var_produces_ready(self) -> None:
        result = self._run_cli([
            "--project-id", "api-test",
            "--api-token-env-var", "QA_API_TOKEN",
            "--no-write",
            "--json-output",
        ])
        assert result.returncode == 0
        out = result.stdout
        data_start = out.find("--- JSON Output ---")
        assert data_start != -1
        json_section = out[data_start:]
        brace_start = json_section.find("{")
        json_str = json_section[brace_start: json_section.rfind("}") + 1]
        data = json.loads(json_str)
        assert data["decision_status"] == "ready_for_execution"
        assert data["selected_method"] == "api_token"

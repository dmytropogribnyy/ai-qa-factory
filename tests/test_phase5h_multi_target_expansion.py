"""
Phase 5H tests — Multi-Target Expansion + Readonly E-commerce + Task Source Integration.

Tests cover:
1. Amazon/Alza public readonly profiles in browser_execution_runner
2. Amazon/Alza routing in scenario_execution_matrix
3. Linear task source fetcher (gates, schema, artifact writing)
4. SauceDemo/practice site categories in dedicated_auth_runner
5. New API profiles (JSONPlaceholder, Reqres, DummyJSON, PetStore) + localhost fix
6. Phase 5G: cdp_attach + dedicated_profile_context now executable
7. CLI safety for fetch_task_source.py
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# 1. Amazon/Alza public readonly — browser_execution_runner
# ---------------------------------------------------------------------------

class TestEcommerceReadonlyProfiles:
    def test_amazon_readonly_profile_exists(self):
        from core.browser_execution_runner import _READONLY_PROFILES
        assert "amazon_public_readonly" in _READONLY_PROFILES

    def test_alza_readonly_profile_exists(self):
        from core.browser_execution_runner import _READONLY_PROFILES
        assert "alza_public_readonly" in _READONLY_PROFILES

    def test_amazon_profile_has_blocked_paths(self):
        from core.browser_execution_runner import _READONLY_PROFILES
        prof = _READONLY_PROFILES["amazon_public_readonly"]
        blocked = prof["blocked_url_paths"]
        assert "/signin" in blocked
        assert "/cart" in blocked
        assert "/checkout" in blocked
        assert "/account" in blocked
        assert "/order" in blocked
        assert "/payment" in blocked

    def test_alza_profile_has_blocked_paths(self):
        from core.browser_execution_runner import _READONLY_PROFILES
        prof = _READONLY_PROFILES["alza_public_readonly"]
        blocked = prof["blocked_url_paths"]
        assert "/prihlasit" in blocked
        assert "/kosik" in blocked
        assert "/platba" in blocked
        assert "/moj-ucet" in blocked

    def test_amazon_removed_from_always_blocked_domains(self):
        from core.browser_execution_runner import _ALWAYS_BLOCKED_DOMAINS
        assert not any("amazon" in d for d in _ALWAYS_BLOCKED_DOMAINS)

    def test_alza_removed_from_always_blocked_domains(self):
        from core.browser_execution_runner import _ALWAYS_BLOCKED_DOMAINS
        assert not any("alza" in d for d in _ALWAYS_BLOCKED_DOMAINS)

    def test_linear_still_always_blocked(self):
        from core.browser_execution_runner import _ALWAYS_BLOCKED_DOMAINS
        assert any("linear" in d for d in _ALWAYS_BLOCKED_DOMAINS)

    def test_amazon_blocked_without_readonly_approval(self, tmp_path):
        from core.browser_execution_runner import BrowserExecutionRunner
        runner = BrowserExecutionRunner(outputs_root=tmp_path)
        result = runner._check_hard_blocked_url(
            base_url="https://www.amazon.com/dp/B09HMKFDXC",
            approve_public_readonly=False,
            readonly_profile=None,
        )
        assert result is not None
        assert "amazon_public_readonly" in result

    def test_amazon_blocked_wrong_profile(self, tmp_path):
        from core.browser_execution_runner import BrowserExecutionRunner
        runner = BrowserExecutionRunner(outputs_root=tmp_path)
        result = runner._check_hard_blocked_url(
            base_url="https://www.amazon.com/dp/B09HMKFDXC",
            approve_public_readonly=True,
            readonly_profile="playwright_docs_readonly",  # wrong profile
        )
        assert result is not None

    def test_amazon_product_page_allowed_with_correct_profile(self, tmp_path):
        from core.browser_execution_runner import BrowserExecutionRunner
        runner = BrowserExecutionRunner(outputs_root=tmp_path)
        result = runner._check_hard_blocked_url(
            base_url="https://www.amazon.com/dp/B09HMKFDXC",
            approve_public_readonly=True,
            readonly_profile="amazon_public_readonly",
        )
        assert result is None  # allowed

    def test_amazon_signin_blocked_even_with_profile(self, tmp_path):
        from core.browser_execution_runner import BrowserExecutionRunner
        runner = BrowserExecutionRunner(outputs_root=tmp_path)
        result = runner._check_hard_blocked_url(
            base_url="https://www.amazon.com/signin",
            approve_public_readonly=True,
            readonly_profile="amazon_public_readonly",
        )
        assert result is not None
        assert "blocked" in result.lower()

    def test_amazon_cart_blocked_even_with_profile(self, tmp_path):
        from core.browser_execution_runner import BrowserExecutionRunner
        runner = BrowserExecutionRunner(outputs_root=tmp_path)
        result = runner._check_hard_blocked_url(
            base_url="https://www.amazon.com/gp/cart/view.html",
            approve_public_readonly=True,
            readonly_profile="amazon_public_readonly",
        )
        assert result is not None

    def test_alza_product_page_allowed_with_correct_profile(self, tmp_path):
        from core.browser_execution_runner import BrowserExecutionRunner
        runner = BrowserExecutionRunner(outputs_root=tmp_path)
        result = runner._check_hard_blocked_url(
            base_url="https://www.alza.sk/notebooky/",
            approve_public_readonly=True,
            readonly_profile="alza_public_readonly",
        )
        assert result is None  # allowed

    def test_alza_login_blocked_even_with_profile(self, tmp_path):
        from core.browser_execution_runner import BrowserExecutionRunner
        runner = BrowserExecutionRunner(outputs_root=tmp_path)
        result = runner._check_hard_blocked_url(
            base_url="https://www.alza.sk/prihlasit",
            approve_public_readonly=True,
            readonly_profile="alza_public_readonly",
        )
        assert result is not None

    def test_amazon_international_domains_included(self):
        from core.browser_execution_runner import _AMAZON_READONLY_DOMAINS
        assert "amazon.de" in _AMAZON_READONLY_DOMAINS
        assert "amazon.co.uk" in _AMAZON_READONLY_DOMAINS
        assert "amazon.fr" in _AMAZON_READONLY_DOMAINS

    def test_alza_international_domains_included(self):
        from core.browser_execution_runner import _ALZA_READONLY_DOMAINS
        assert "alza.cz" in _ALZA_READONLY_DOMAINS
        assert "alza.hu" in _ALZA_READONLY_DOMAINS
        assert "alza.de" in _ALZA_READONLY_DOMAINS


# ---------------------------------------------------------------------------
# 2. Amazon/Alza routing in scenario_execution_matrix
# ---------------------------------------------------------------------------

class TestEcommerceReadonlyMatrix:
    def test_amazon_product_page_routes_to_readonly_lane(self):
        from core.scenario_execution_matrix import ScenarioExecutionMatrixBuilder
        builder = ScenarioExecutionMatrixBuilder()
        dec = builder.decide_execution(
            project_id="p1",
            target_url="https://www.amazon.com/dp/B09HMKFDXC",
            scenario_type="page_load_smoke",
        )
        assert dec.execution_lane == "no_auth_public_readonly_smoke"
        assert dec.allowed_now is True
        assert dec.target_category == "ecommerce_public_readonly"

    def test_alza_category_page_routes_to_readonly_lane(self):
        from core.scenario_execution_matrix import ScenarioExecutionMatrixBuilder
        builder = ScenarioExecutionMatrixBuilder()
        dec = builder.decide_execution(
            project_id="p1",
            target_url="https://www.alza.sk/notebooky/",
            scenario_type="navigation_smoke",
        )
        assert dec.execution_lane == "no_auth_public_readonly_smoke"
        assert dec.allowed_now is True

    def test_amazon_auth_flow_always_blocked(self):
        from core.scenario_execution_matrix import ScenarioExecutionMatrixBuilder
        builder = ScenarioExecutionMatrixBuilder()
        dec = builder.decide_execution(
            project_id="p1",
            target_url="https://www.amazon.com/dp/B09HMKFDXC",
            scenario_type="login_smoke",
        )
        assert dec.execution_lane == "strictly_blocked"
        assert dec.allowed_now is False

    def test_amazon_checkout_always_blocked(self):
        from core.scenario_execution_matrix import ScenarioExecutionMatrixBuilder
        builder = ScenarioExecutionMatrixBuilder()
        dec = builder.decide_execution(
            project_id="p1",
            target_url="https://www.amazon.com/checkout",
            scenario_type="checkout_flow",
        )
        assert dec.allowed_now is False

    def test_amazon_ecommerce_readonly_profile_in_matrix(self):
        from core.scenario_execution_matrix import ScenarioExecutionMatrixBuilder
        builder = ScenarioExecutionMatrixBuilder()
        profiles = builder.build_target_profiles()
        ids = [p.id for p in profiles]
        assert "amazon_public_readonly" in ids
        assert "alza_public_readonly" in ids

    def test_amazon_readonly_profile_is_allowed_now(self):
        from core.scenario_execution_matrix import ScenarioExecutionMatrixBuilder
        builder = ScenarioExecutionMatrixBuilder()
        profiles = builder.build_target_profiles()
        amazon = next(p for p in profiles if p.id == "amazon_public_readonly")
        assert amazon.allowed_now is True
        assert amazon.requires_credentials is False

    def test_google_oauth_still_strictly_blocked(self):
        from core.scenario_execution_matrix import ScenarioExecutionMatrixBuilder
        builder = ScenarioExecutionMatrixBuilder()
        dec = builder.decide_execution(
            project_id="p1",
            target_url="https://accounts.google.com/signin",
            scenario_type="oauth_flow",
        )
        assert dec.execution_lane == "strictly_blocked"
        assert dec.allowed_now is False


# ---------------------------------------------------------------------------
# 3. Linear task source fetcher — gates and schema
# ---------------------------------------------------------------------------

class TestTaskSourceSchemaInvariants:
    def test_fetch_policy_writeback_hardcoded_false(self):
        from core.schemas.task_source import TaskSourceFetchPolicy
        p = TaskSourceFetchPolicy(provider="linear", writeback_allowed=True)
        assert p.writeback_allowed is False

    def test_fetch_policy_status_change_hardcoded_false(self):
        from core.schemas.task_source import TaskSourceFetchPolicy
        p = TaskSourceFetchPolicy(provider="linear", status_change_allowed=True)
        assert p.status_change_allowed is False

    def test_fetch_policy_from_dict_hardcoded_false(self):
        from core.schemas.task_source import TaskSourceFetchPolicy
        p = TaskSourceFetchPolicy.from_dict({"writeback_allowed": True, "comment_allowed": True})
        assert p.writeback_allowed is False
        assert p.comment_allowed is False

    def test_report_writeback_hardcoded_false(self):
        from core.schemas.task_source import TaskSourceFetchReport
        r = TaskSourceFetchReport(writeback_performed=True)
        assert r.writeback_performed is False

    def test_report_raw_token_hardcoded_false(self):
        from core.schemas.task_source import TaskSourceFetchReport
        r = TaskSourceFetchReport(raw_token_in_output=True)
        assert r.raw_token_in_output is False

    def test_report_client_delivery_hardcoded_false(self):
        from core.schemas.task_source import TaskSourceFetchReport
        r = TaskSourceFetchReport(client_delivery_allowed=True)
        assert r.client_delivery_allowed is False

    def test_issue_raw_data_logged_hardcoded_false(self):
        from core.schemas.task_source import TaskSourceIssue
        issue = TaskSourceIssue(raw_data_logged=True)
        assert issue.raw_data_logged is False


class TestTaskSourceFetcherGates:
    def test_blocked_without_approval(self, tmp_path):
        from core.task_source_fetcher import TaskSourceFetcher
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        report = fetcher.fetch(
            project_id="p1",
            provider="linear",
            token_env_var="LINEAR_API_TOKEN",
            team_key="ENG",
            approve_task_source_integration=False,
            write=False,
        )
        assert report.status == "blocked"
        assert any("approve" in b.lower() for b in report.blockers)

    def test_blocked_for_planning_only_provider(self, tmp_path):
        from core.task_source_fetcher import TaskSourceFetcher
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        report = fetcher.fetch(
            project_id="p1",
            provider="jira",
            token_env_var="JIRA_TOKEN",
            team_key="QA",
            approve_task_source_integration=True,
            write=False,
        )
        assert report.status == "blocked"
        assert any("planning-only" in b.lower() for b in report.blockers)

    def test_blocked_for_unknown_provider(self, tmp_path):
        from core.task_source_fetcher import TaskSourceFetcher
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        report = fetcher.fetch(
            project_id="p1",
            provider="trello",
            token_env_var="TRELLO_TOKEN",
            team_key="QA",
            approve_task_source_integration=True,
            write=False,
        )
        assert report.status == "blocked"

    def test_blocked_missing_token_env_var(self, tmp_path):
        from core.task_source_fetcher import TaskSourceFetcher
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        report = fetcher.fetch(
            project_id="p1",
            provider="linear",
            token_env_var="",
            team_key="ENG",
            approve_task_source_integration=True,
            write=False,
        )
        assert report.status == "blocked"
        assert any("token_env_var" in b.lower() for b in report.blockers)

    def test_blocked_invalid_env_var_format(self, tmp_path):
        from core.task_source_fetcher import TaskSourceFetcher
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        report = fetcher.fetch(
            project_id="p1",
            provider="linear",
            token_env_var="lower_case_var",
            team_key="ENG",
            approve_task_source_integration=True,
            write=False,
        )
        assert report.status == "blocked"

    def test_blocked_if_token_looks_like_raw_value(self, tmp_path):
        from core.task_source_fetcher import TaskSourceFetcher
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        report = fetcher.fetch(
            project_id="p1",
            provider="linear",
            token_env_var="LIN_API_MYTOKEN",
            team_key="ENG",
            approve_task_source_integration=True,
            write=False,
        )
        # "lin_api_" is a blocked substring
        assert report.status == "blocked"

    def test_blocked_if_env_var_not_set(self, tmp_path, monkeypatch):
        from core.task_source_fetcher import TaskSourceFetcher
        monkeypatch.delenv("LINEAR_API_TOKEN", raising=False)
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        report = fetcher.fetch(
            project_id="p1",
            provider="linear",
            token_env_var="LINEAR_API_TOKEN",
            team_key="ENG",
            approve_task_source_integration=True,
            write=False,
        )
        assert report.status == "blocked"
        assert any("not set" in b.lower() for b in report.blockers)

    def test_blocked_missing_team_key_and_issue_ids(self, tmp_path, monkeypatch):
        from core.task_source_fetcher import TaskSourceFetcher
        monkeypatch.setenv("LINEAR_API_TOKEN", "fake_token_value")
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        report = fetcher.fetch(
            project_id="p1",
            provider="linear",
            token_env_var="LINEAR_API_TOKEN",
            team_key="",
            issue_ids=None,
            approve_task_source_integration=True,
            write=False,
        )
        assert report.status == "blocked"
        assert any("team_key" in b.lower() for b in report.blockers)

    def test_no_api_call_when_blocked(self, tmp_path):
        from core.task_source_fetcher import TaskSourceFetcher
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        with patch.object(fetcher, "_fetch_linear_issues") as mock_fetch:
            fetcher.fetch(
                project_id="p1",
                provider="linear",
                token_env_var="LINEAR_API_TOKEN",
                team_key="ENG",
                approve_task_source_integration=False,
                write=False,
            )
            mock_fetch.assert_not_called()

    def test_successful_fetch_with_mocked_api(self, tmp_path, monkeypatch):
        from core.task_source_fetcher import TaskSourceFetcher
        monkeypatch.setenv("LINEAR_API_TOKEN", "fake_value_12345")
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        mock_issues = [
            {
                "id": "issue-1", "identifier": "QA-123",
                "title": "Login page should display error on bad credentials",
                "description": "Acceptance criteria:\n- Error message shown\n- No redirect",
                "state": {"name": "In Progress"}, "priority": 2,
                "labels": {"nodes": [{"name": "auth"}]},
                "assignee": {"name": "Test User"},
                "url": "https://linear.app/team/issue/QA-123",
                "team": {"name": "QA Team", "key": "QA"},
                "project": {"name": "Auth Sprint"},
            }
        ]
        with patch.object(fetcher, "_fetch_linear_issues", return_value=(mock_issues, "")):
            report = fetcher.fetch(
                project_id="p1",
                provider="linear",
                token_env_var="LINEAR_API_TOKEN",
                team_key="QA",
                approve_task_source_integration=True,
                write=True,
            )
        assert report.status == "success"
        assert report.issues_fetched == 1
        assert len(report.scenarios) == 1
        assert report.scenarios[0].issue_id == "QA-123"
        assert report.writeback_performed is False
        assert report.raw_token_in_output is False
        assert report.client_delivery_allowed is False

    def test_artifacts_written_on_success(self, tmp_path, monkeypatch):
        from core.task_source_fetcher import TaskSourceFetcher
        monkeypatch.setenv("LINEAR_API_TOKEN", "fake_value_12345")
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        with patch.object(fetcher, "_fetch_linear_issues", return_value=([], "")):
            fetcher.fetch(
                project_id="p1",
                provider="linear",
                token_env_var="LINEAR_API_TOKEN",
                team_key="QA",
                approve_task_source_integration=True,
                write=True,
            )
        out_dir = tmp_path / "p1" / "16_task_source"
        assert (out_dir / "task_source_report.json").exists()
        assert (out_dir / "derived_scenarios.json").exists()
        assert (out_dir / "task_source_summary.md").exists()

    def test_no_raw_token_in_artifacts(self, tmp_path, monkeypatch):
        from core.task_source_fetcher import TaskSourceFetcher
        fake_token = "lin_api_SUPERSECRET123456"
        monkeypatch.setenv("LINEAR_API_TOKEN", fake_token)
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        with patch.object(fetcher, "_fetch_linear_issues", return_value=([], "")):
            fetcher.fetch(
                project_id="p1",
                provider="linear",
                token_env_var="LINEAR_API_TOKEN",
                team_key="QA",
                approve_task_source_integration=True,
                write=True,
            )
        out_dir = tmp_path / "p1" / "16_task_source"
        for artifact in out_dir.iterdir():
            content = artifact.read_text(encoding="utf-8")
            assert fake_token not in content, f"Raw token found in {artifact.name}"

    def test_scenario_type_inference_auth(self, tmp_path):
        from core.task_source_fetcher import TaskSourceFetcher
        from core.schemas.task_source import TaskSourceIssue
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        issue = TaskSourceIssue(
            issue_id="QA-1", title="User login flow", description="Test the signin page"
        )
        scenario = fetcher._derive_scenario(issue)
        assert scenario.scenario_type == "auth_smoke"

    def test_scenario_type_inference_api(self, tmp_path):
        from core.task_source_fetcher import TaskSourceFetcher
        from core.schemas.task_source import TaskSourceIssue
        fetcher = TaskSourceFetcher(outputs_root=tmp_path)
        issue = TaskSourceIssue(
            issue_id="QA-2", title="REST API endpoint validation", description="Check /api/users"
        )
        scenario = fetcher._derive_scenario(issue)
        assert scenario.scenario_type == "api_smoke"


# ---------------------------------------------------------------------------
# 4. SauceDemo + practice sites in dedicated_auth_runner
# ---------------------------------------------------------------------------

class TestDedicatedAuthNewCategories:
    def test_saucedemo_in_allowed_categories(self):
        from core.dedicated_auth_runner import _ALLOWED_TARGET_CATEGORIES
        assert "saucedemo_demo_auth" in _ALLOWED_TARGET_CATEGORIES

    def test_practice_site_in_allowed_categories(self):
        from core.dedicated_auth_runner import _ALLOWED_TARGET_CATEGORIES
        assert "practice_site_demo_auth" in _ALLOWED_TARGET_CATEGORIES

    def test_staging_still_in_allowed_categories(self):
        from core.dedicated_auth_runner import _ALLOWED_TARGET_CATEGORIES
        assert "staging" in _ALLOWED_TARGET_CATEGORIES

    def test_orangehrm_still_in_allowed_categories(self):
        from core.dedicated_auth_runner import _ALLOWED_TARGET_CATEGORIES
        assert "orangehrm_demo_auth" in _ALLOWED_TARGET_CATEGORIES


# ---------------------------------------------------------------------------
# 5. API profiles — new profiles + localhost fix
# ---------------------------------------------------------------------------

class TestNewAPIProfiles:
    def test_jsonplaceholder_profile_exists(self):
        from core.api_auth_runner import _API_TARGET_PROFILES
        assert "jsonplaceholder_public_api" in _API_TARGET_PROFILES

    def test_reqres_profile_exists(self):
        from core.api_auth_runner import _API_TARGET_PROFILES
        assert "reqres_public_api" in _API_TARGET_PROFILES

    def test_dummyjson_profile_exists(self):
        from core.api_auth_runner import _API_TARGET_PROFILES
        assert "dummyjson_public_api" in _API_TARGET_PROFILES

    def test_petstore_profile_exists(self):
        from core.api_auth_runner import _API_TARGET_PROFILES
        assert "petstore_swagger_api" in _API_TARGET_PROFILES

    def test_jsonplaceholder_has_no_auth_endpoint(self):
        from core.api_auth_runner import _API_TARGET_PROFILES
        prof = _API_TARGET_PROFILES["jsonplaceholder_public_api"]
        assert prof.auth_endpoint == ""

    def test_petstore_has_no_auth_endpoint(self):
        from core.api_auth_runner import _API_TARGET_PROFILES
        prof = _API_TARGET_PROFILES["petstore_swagger_api"]
        assert prof.auth_endpoint == ""

    def test_reqres_has_auth_endpoint(self):
        from core.api_auth_runner import _API_TARGET_PROFILES
        prof = _API_TARGET_PROFILES["reqres_public_api"]
        assert prof.auth_endpoint != ""

    def test_localhost_not_in_blocked_patterns(self):
        from core.api_auth_runner import _STRICTLY_BLOCKED_URL_PATTERNS
        assert "127.0.0.1" not in _STRICTLY_BLOCKED_URL_PATTERNS
        assert "localhost" not in _STRICTLY_BLOCKED_URL_PATTERNS

    def test_no_auth_profile_skips_username_gate(self, tmp_path):
        from core.api_auth_runner import APIAuthRunner
        runner = APIAuthRunner(outputs_root=tmp_path)
        # jsonplaceholder doesn't need username_env_var
        report = runner.run_api_auth(
            project_id="p1",
            approve_api_auth_execution=True,
            target_profile="jsonplaceholder_public_api",
            username_env_var=None,
            password_env_var=None,
        )
        # Should not be blocked by "username_env_var is required"
        assert not any("username_env_var is required" in b for b in report.blockers)

    def test_auth_profile_still_requires_username(self, tmp_path):
        from core.api_auth_runner import APIAuthRunner
        runner = APIAuthRunner(outputs_root=tmp_path)
        report = runner.run_api_auth(
            project_id="p1",
            approve_api_auth_execution=True,
            target_profile="restful_booker_public_api",
            username_env_var=None,
        )
        assert any("username_env_var" in b for b in report.blockers)

    def test_no_auth_profile_has_skipped_step1(self, tmp_path, monkeypatch):
        from core.api_auth_runner import APIAuthRunner
        runner = APIAuthRunner(outputs_root=tmp_path)
        monkeypatch.setenv("DUMMY_USERNAME", "user")

        with patch("urllib.request.urlopen") as mock_url:
            mock_resp = MagicMock()
            mock_resp.__enter__ = lambda s: s
            mock_resp.__exit__ = MagicMock(return_value=False)
            mock_resp.status = 200
            mock_resp.read.return_value = b'[{"id":1}]'
            mock_url.return_value = mock_resp

            report = runner.run_api_auth(
                project_id="p1",
                approve_api_auth_execution=True,
                target_profile="jsonplaceholder_public_api",
                username_env_var=None,
                run_safe_read_check=True,
            )

        step1_cmds = [c for c in report.commands if "step1" in c.id]
        assert len(step1_cmds) == 1
        assert step1_cmds[0].status == "skipped"


# ---------------------------------------------------------------------------
# 6. Phase 5G: cdp_attach + dedicated_profile_context now executable
# ---------------------------------------------------------------------------

class TestPhase5HGoogleModes:
    def test_cdp_attach_in_executable_modes(self):
        from core.schemas.google_auth import GOOGLE_AUTH_MODES_EXECUTABLE_5G
        assert "cdp_attach" in GOOGLE_AUTH_MODES_EXECUTABLE_5G

    def test_dedicated_profile_context_in_executable_modes(self):
        from core.schemas.google_auth import GOOGLE_AUTH_MODES_EXECUTABLE_5G
        assert "dedicated_profile_context" in GOOGLE_AUTH_MODES_EXECUTABLE_5G

    def test_cdp_attach_not_in_planning_only(self):
        from core.schemas.google_auth import GOOGLE_AUTH_MODES_PLANNING_ONLY_5G
        assert "cdp_attach" not in GOOGLE_AUTH_MODES_PLANNING_ONLY_5G

    def test_dedicated_profile_not_in_planning_only(self):
        from core.schemas.google_auth import GOOGLE_AUTH_MODES_PLANNING_ONLY_5G
        assert "dedicated_profile_context" not in GOOGLE_AUTH_MODES_PLANNING_ONLY_5G

    def test_future_modes_still_planning_only(self):
        from core.schemas.google_auth import GOOGLE_AUTH_MODES_PLANNING_ONLY_5G
        assert "google_api_oauth_token_future" in GOOGLE_AUTH_MODES_PLANNING_ONLY_5G
        assert "totp_test_account_future" in GOOGLE_AUTH_MODES_PLANNING_ONLY_5G

    def test_cdp_attach_allowed_by_planner(self, tmp_path):
        from core.google_auth_capability import GoogleAuthCapabilityPlanner
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        dec = planner.decide_execution(
            project_id="p1",
            target_url="https://mail.google.com",
            target_kind="google_account_ui",
            auth_mode="cdp_attach",
            account_email_label="danrobinson_artist_gmail",
            approve_google_test_account=True,
            google_test_account_confirmed=True,
            dedicated_test_account_confirmed=True,
            personal_account_confirmed=False,
            production_account_confirmed=False,
            cdp_port=9222,
        )
        assert dec.allowed_now is True
        assert not any("planning-only" in b for b in dec.blockers)

    def test_cdp_attach_requires_valid_port(self, tmp_path):
        from core.google_auth_capability import GoogleAuthCapabilityPlanner
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        dec = planner.decide_execution(
            project_id="p1",
            target_url="https://mail.google.com",
            target_kind="google_account_ui",
            auth_mode="cdp_attach",
            account_email_label="danrobinson_artist_gmail",
            approve_google_test_account=True,
            google_test_account_confirmed=True,
            dedicated_test_account_confirmed=True,
            cdp_port=80,  # invalid: must be 1024-65535
        )
        assert dec.allowed_now is False
        assert any("cdp_port" in b for b in dec.blockers)

    def test_cdp_attach_requires_port(self, tmp_path):
        from core.google_auth_capability import GoogleAuthCapabilityPlanner
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        dec = planner.decide_execution(
            project_id="p1",
            target_url="https://mail.google.com",
            target_kind="google_account_ui",
            auth_mode="cdp_attach",
            account_email_label="danrobinson_artist_gmail",
            approve_google_test_account=True,
            google_test_account_confirmed=True,
            dedicated_test_account_confirmed=True,
            cdp_port=None,
        )
        assert dec.allowed_now is False

    def test_dedicated_profile_requires_user_data_dir(self, tmp_path):
        from core.google_auth_capability import GoogleAuthCapabilityPlanner
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        dec = planner.decide_execution(
            project_id="p1",
            target_url="https://mail.google.com",
            target_kind="google_account_ui",
            auth_mode="dedicated_profile_context",
            account_email_label="danrobinson_artist_gmail",
            approve_google_test_account=True,
            google_test_account_confirmed=True,
            dedicated_test_account_confirmed=True,
            user_data_dir="",
        )
        assert dec.allowed_now is False
        assert any("user-data-dir" in b or "user_data_dir" in b for b in dec.blockers)

    def test_dedicated_profile_path_must_be_internal(self, tmp_path):
        from core.google_auth_capability import GoogleAuthCapabilityPlanner
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        dec = planner.decide_execution(
            project_id="p1",
            target_url="https://mail.google.com",
            target_kind="google_account_ui",
            auth_mode="dedicated_profile_context",
            account_email_label="danrobinson_artist_gmail",
            approve_google_test_account=True,
            google_test_account_confirmed=True,
            dedicated_test_account_confirmed=True,
            user_data_dir="/home/user/.config/google-chrome",  # outside allowed dir
        )
        assert dec.allowed_now is False

    def test_runner_has_cdp_attach_method(self):
        from core.google_auth_runner import GoogleAuthRunner
        assert hasattr(GoogleAuthRunner, "run_cdp_attach_smoke")

    def test_runner_has_dedicated_profile_method(self):
        from core.google_auth_runner import GoogleAuthRunner
        assert hasattr(GoogleAuthRunner, "run_dedicated_profile_smoke")


# ---------------------------------------------------------------------------
# 7. CLI safety
# ---------------------------------------------------------------------------

class TestCLISafety:
    def test_fetch_task_source_blocked_flags_rejected(self):
        from tools.fetch_task_source import _check_blocked_flags
        with pytest.raises(SystemExit):
            _check_blocked_flags(["--token", "lin_api_secret123"])

    def test_fetch_task_source_api_key_rejected(self):
        from tools.fetch_task_source import _check_blocked_flags
        with pytest.raises(SystemExit):
            _check_blocked_flags(["--api-key", "somevalue"])

    def test_fetch_task_source_safe_flags_pass(self):
        from tools.fetch_task_source import _check_blocked_flags
        # Should not raise
        _check_blocked_flags([
            "--project-id", "p1",
            "--token-env-var", "LINEAR_API_TOKEN",
            "--team-key", "ENG",
            "--approve-task-source-integration",
        ])

    def test_raw_token_substring_blocked_in_env_var(self, tmp_path):
        from core.task_source_fetcher import _BLOCKED_TOKEN_PATTERNS
        # Verify patterns cover common raw token prefixes
        assert any("lin_api_" in p for p in _BLOCKED_TOKEN_PATTERNS)
        assert any("ghp_" in p for p in _BLOCKED_TOKEN_PATTERNS)
        assert any("eyJ" in p for p in _BLOCKED_TOKEN_PATTERNS)

    def test_task_source_providers_executable(self):
        from core.schemas.task_source import TASK_SOURCE_PROVIDERS_EXECUTABLE_5H
        assert "linear" in TASK_SOURCE_PROVIDERS_EXECUTABLE_5H

    def test_task_source_providers_planning_only(self):
        from core.schemas.task_source import TASK_SOURCE_PROVIDERS_PLANNING_ONLY_5H
        assert "jira" in TASK_SOURCE_PROVIDERS_PLANNING_ONLY_5H
        assert "clickup" in TASK_SOURCE_PROVIDERS_PLANNING_ONLY_5H


# ---------------------------------------------------------------------------
# 8. Schema exports
# ---------------------------------------------------------------------------

class TestPhase5HSchemaExports:
    def test_task_source_exports_in_init(self):
        from core.schemas import (
            TASK_SOURCE_PROVIDERS,
            TASK_SOURCE_PROVIDERS_EXECUTABLE_5H,
        )
        assert TASK_SOURCE_PROVIDERS
        assert "linear" in TASK_SOURCE_PROVIDERS_EXECUTABLE_5H

    def test_ecommerce_readonly_domains_exported(self):
        from core.browser_execution_runner import (
            _AMAZON_READONLY_DOMAINS,
            _ALZA_READONLY_DOMAINS,
            _ECOMMERCE_READONLY_DOMAINS,
        )
        assert len(_AMAZON_READONLY_DOMAINS) >= 5
        assert len(_ALZA_READONLY_DOMAINS) >= 5
        assert _ECOMMERCE_READONLY_DOMAINS == _AMAZON_READONLY_DOMAINS | _ALZA_READONLY_DOMAINS


# ---------------------------------------------------------------------------
# 9. Ecommerce readonly — dangerous selector scan (Phase 5H hardening)
# ---------------------------------------------------------------------------

class TestEcommerceReadonlySelectorScan:
    def test_dangerous_patterns_list_exists(self):
        from core.browser_execution_runner import _ECOMMERCE_READONLY_DANGEROUS_PATTERNS
        assert len(_ECOMMERCE_READONLY_DANGEROUS_PATTERNS) >= 10
        assert "add-to-cart" in _ECOMMERCE_READONLY_DANGEROUS_PATTERNS
        assert "/checkout" in _ECOMMERCE_READONLY_DANGEROUS_PATTERNS
        assert "password" in _ECOMMERCE_READONLY_DANGEROUS_PATTERNS

    def test_scan_returns_none_for_empty_dir(self, tmp_path):
        from core.browser_execution_runner import BrowserExecutionRunner
        runner = BrowserExecutionRunner()
        # No tests/ dir at all
        result = runner._scan_ecommerce_test_files(tmp_path)
        assert result is None

    def test_scan_returns_none_for_clean_test(self, tmp_path):
        from core.browser_execution_runner import BrowserExecutionRunner
        tests_dir = tmp_path / "tests" / "smoke"
        tests_dir.mkdir(parents=True)
        (tests_dir / "product.spec.ts").write_text(
            "test('product page loads', async ({ page }) => {\n"
            "  await page.goto('https://amazon.com/dp/B08N5W');\n"
            "  await expect(page.locator('h1')).toBeVisible();\n"
            "});\n",
            encoding="utf-8",
        )
        runner = BrowserExecutionRunner()
        result = runner._scan_ecommerce_test_files(tmp_path)
        assert result is None

    def test_scan_blocks_add_to_cart(self, tmp_path):
        from core.browser_execution_runner import BrowserExecutionRunner
        tests_dir = tmp_path / "tests" / "smoke"
        tests_dir.mkdir(parents=True)
        (tests_dir / "bad.spec.ts").write_text(
            "await page.click('[data-testid=\"add-to-cart\"]');\n",
            encoding="utf-8",
        )
        runner = BrowserExecutionRunner()
        result = runner._scan_ecommerce_test_files(tmp_path)
        assert result is not None
        assert "dangerous pattern" in result
        assert "add-to-cart" in result

    def test_scan_blocks_checkout_url(self, tmp_path):
        from core.browser_execution_runner import BrowserExecutionRunner
        tests_dir = tmp_path / "tests" / "smoke"
        tests_dir.mkdir(parents=True)
        (tests_dir / "bad.spec.ts").write_text(
            "await page.goto('https://amazon.com/checkout');\n",
            encoding="utf-8",
        )
        runner = BrowserExecutionRunner()
        result = runner._scan_ecommerce_test_files(tmp_path)
        assert result is not None
        assert "/checkout" in result

    def test_scan_blocks_password_fill(self, tmp_path):
        from core.browser_execution_runner import BrowserExecutionRunner
        tests_dir = tmp_path / "tests" / "smoke"
        tests_dir.mkdir(parents=True)
        (tests_dir / "bad.spec.ts").write_text(
            "await page.fill('#password', process.env.TEST_PASSWORD);\n",
            encoding="utf-8",
        )
        runner = BrowserExecutionRunner()
        result = runner._scan_ecommerce_test_files(tmp_path)
        assert result is not None
        assert "password" in result

    def test_scan_blocks_buy_now(self, tmp_path):
        from core.browser_execution_runner import BrowserExecutionRunner
        tests_dir = tmp_path / "tests" / "smoke"
        tests_dir.mkdir(parents=True)
        (tests_dir / "bad.spec.ts").write_text(
            "await page.locator('#buyNow').click();\n",
            encoding="utf-8",
        )
        runner = BrowserExecutionRunner()
        result = runner._scan_ecommerce_test_files(tmp_path)
        assert result is not None

    def test_scan_only_applies_to_ecommerce_profile(self):
        """The scan constant exists — profile routing decides when to apply it."""
        from core.browser_execution_runner import (
            _ECOMMERCE_READONLY_DANGEROUS_PATTERNS,
            _READONLY_PROFILES,
        )
        # ecommerce profiles exist
        assert "amazon_public_readonly" in _READONLY_PROFILES
        assert _READONLY_PROFILES["amazon_public_readonly"]["target_category"] == "ecommerce_public_readonly"
        # patterns list is non-empty
        assert _ECOMMERCE_READONLY_DANGEROUS_PATTERNS

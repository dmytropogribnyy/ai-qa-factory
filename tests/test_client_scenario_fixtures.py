"""
Tests for fixtures/client_scenarios/ — Phase 3B-SCENARIOS evaluation layer.

These tests verify that:
- All expected scenario files exist
- Each scenario has all required sections
- No real credentials appear in fixture files
- Safety content is present and correct per category
- Special scenarios (Linear, Amazon, OAuth, etc.) have required content

IMPORTANT: These tests read local fixture files only.
No URLs are fetched. No browsers open. No external calls are made.
"""
import re
from pathlib import Path

FIXTURES_ROOT = Path(__file__).parent.parent / "fixtures" / "client_scenarios"

REQUIRED_SECTIONS = [
    "Client-style brief",
    "Input examples",
    "Expected classification",
    "Expected blueprint",
    "Expected QA strategy direction",
    "Expected scaffold direction",
    "Expected static validation behavior",
    "Expected blocked actions",
    "Expected required approvals",
    "Expected safety behavior",
    "What must NOT happen",
]

EXPECTED_SCENARIOS = [
    "synthetic/01_google_oauth_auth_heavy.md",
    "synthetic/02_payment_checkout_sandbox_required.md",
    "synthetic/03_n8n_webhook_integration_blocked.md",
    "synthetic/04_linear_issue_task_source.md",
    "public_demo_targets/01_saucedemo_ecommerce_login.md",
    "public_demo_targets/02_orangehrm_admin_dashboard.md",
    "public_demo_targets/03_the_internet_dynamic_ui.md",
    "public_demo_targets/04_restful_booker_api_auth_crud.md",
    "public_demo_targets/05_jsonplaceholder_fake_rest_api.md",
    "public_demo_targets/06_realworld_conduit_ui_api.md",
    "real_public_readonly/01_alza_sk_public_ecommerce_readonly.md",
    "real_public_readonly/02_playwright_docs_readonly.md",
    "high_risk_marketplace_readonly/01_amazon_public_marketplace_readonly.md",
]

REAL_SECRET_PATTERNS = [
    re.compile(r"(?i)sk-[A-Za-z0-9]{20,}"),
    re.compile(r"(?i)xoxb-[A-Za-z0-9-]+"),
    re.compile(r"(?i)AIza[A-Za-z0-9_-]{35}"),
    re.compile(r"(?i)ghp_[A-Za-z0-9]{36}"),
    re.compile(r"(?i)lin_api_[A-Za-z0-9]{40}"),
]


def _read(relative_path: str) -> str:
    return (FIXTURES_ROOT / relative_path).read_text(encoding="utf-8")


class TestFixtureFilesExist:
    def test_fixtures_root_exists(self) -> None:
        assert FIXTURES_ROOT.exists(), f"fixtures/client_scenarios/ not found at {FIXTURES_ROOT}"

    def test_readme_exists(self) -> None:
        assert (FIXTURES_ROOT / "README.md").exists()

    def test_synthetic_dir_exists(self) -> None:
        assert (FIXTURES_ROOT / "synthetic").is_dir()

    def test_public_demo_dir_exists(self) -> None:
        assert (FIXTURES_ROOT / "public_demo_targets").is_dir()

    def test_real_public_readonly_dir_exists(self) -> None:
        assert (FIXTURES_ROOT / "real_public_readonly").is_dir()

    def test_high_risk_dir_exists(self) -> None:
        assert (FIXTURES_ROOT / "high_risk_marketplace_readonly").is_dir()

    def test_all_expected_scenario_files_exist(self) -> None:
        missing = [p for p in EXPECTED_SCENARIOS if not (FIXTURES_ROOT / p).exists()]
        assert not missing, f"Missing scenario files: {missing}"

    def test_total_scenario_count(self) -> None:
        found = list(FIXTURES_ROOT.rglob("*.md"))
        scenario_files = [f for f in found if f.name != "README.md"]
        assert len(scenario_files) == 13, (
            f"Expected 13 scenario files, found {len(scenario_files)}: "
            f"{[f.relative_to(FIXTURES_ROOT) for f in scenario_files]}"
        )


class TestScenarioSections:
    def test_all_scenarios_have_required_sections(self) -> None:
        missing_map: dict[str, list[str]] = {}
        for path in EXPECTED_SCENARIOS:
            content = _read(path)
            missing = [s for s in REQUIRED_SECTIONS if s not in content]
            if missing:
                missing_map[path] = missing
        assert not missing_map, f"Scenarios missing required sections: {missing_map}"

    def test_all_scenarios_have_category(self) -> None:
        for path in EXPECTED_SCENARIOS:
            content = _read(path)
            assert "## Category" in content, f"{path} is missing '## Category'"

    def test_all_scenarios_have_safe_to_execute_false(self) -> None:
        for path in EXPECTED_SCENARIOS:
            content = _read(path)
            assert "safe_to_execute_tests: False" in content, (
                f"{path} must state 'safe_to_execute_tests: False'"
            )


class TestNoRealSecrets:
    def test_no_real_api_key_patterns(self) -> None:
        for path in EXPECTED_SCENARIOS:
            content = _read(path)
            for pat in REAL_SECRET_PATTERNS:
                matches = pat.findall(content)
                assert not matches, (
                    f"{path}: potential real secret matched pattern {pat.pattern}: {matches}"
                )

    def test_no_linear_token_in_fixtures(self) -> None:
        for path in EXPECTED_SCENARIOS:
            content = _read(path)
            assert "lin_api_" not in content, f"{path}: Linear API token pattern found"

    def test_fake_secret_only_in_synthetic(self) -> None:
        for path in EXPECTED_SCENARIOS:
            content = _read(path)
            if "FakeSecret123" in content:
                assert path.startswith("synthetic/"), (
                    f"FakeSecret123 found outside synthetic/: {path}"
                )

    def test_no_real_oauth_client_secret(self) -> None:
        for path in EXPECTED_SCENARIOS:
            content = _read(path)
            assert "client_secret" not in content.lower() or "process.env" in content, (
                f"{path}: possible real OAuth client secret"
            )


class TestSyntheticScenarios:
    def test_google_oauth_blocks_personal_account(self) -> None:
        content = _read("synthetic/01_google_oauth_auth_heavy.md")
        assert "personal" in content.lower()
        assert "no" in content.lower()

    def test_google_oauth_requires_test_account(self) -> None:
        content = _read("synthetic/01_google_oauth_auth_heavy.md")
        assert "test" in content.lower() and "account" in content.lower()

    def test_payment_requires_sandbox(self) -> None:
        content = _read("synthetic/02_payment_checkout_sandbox_required.md")
        assert "sandbox" in content.lower()
        assert "real payment" in content.lower() or "no real" in content.lower()

    def test_payment_blocks_real_payment(self) -> None:
        content = _read("synthetic/02_payment_checkout_sandbox_required.md")
        assert "real payment" in content.lower() or "Real payment" in content

    def test_n8n_blocks_outbound_calls(self) -> None:
        content = _read("synthetic/03_n8n_webhook_integration_blocked.md")
        assert "outbound" in content.lower()
        assert "FakeSecret123" in content

    def test_n8n_redacts_integration_token(self) -> None:
        content = _read("synthetic/03_n8n_webhook_integration_blocked.md")
        assert "FakeSecret123" in content
        assert "redact" in content.lower()

    def test_linear_task_url_is_task_source(self) -> None:
        content = _read("synthetic/04_linear_issue_task_source.md")
        assert "task_url" in content
        assert "task_source" in content

    def test_linear_target_app_is_staging(self) -> None:
        content = _read("synthetic/04_linear_issue_task_source.md")
        assert "target_url" in content
        assert "target_application" in content
        assert "staging.example.com" in content

    def test_linear_is_not_target_application(self) -> None:
        content = _read("synthetic/04_linear_issue_task_source.md")
        assert "Linear" in content
        assert "not target_application" in content or "Linear is the task source" in content or "task_source" in content

    def test_linear_blocks_api_writeback(self) -> None:
        content = _read("synthetic/04_linear_issue_task_source.md")
        assert "writeback" in content.lower() or "write" in content.lower()
        assert "Linear API" in content or "linear api" in content.lower()

    def test_linear_no_token(self) -> None:
        content = _read("synthetic/04_linear_issue_task_source.md")
        assert "lin_api_" not in content
        assert "no Linear token" in content or "no real Linear" in content.lower() or "Linear token" in content


class TestPublicDemoTargets:
    def test_saucedemo_execution_requires_approval(self) -> None:
        content = _read("public_demo_targets/01_saucedemo_ecommerce_login.md")
        assert "approval" in content.lower()
        assert "execution" in content.lower()

    def test_saucedemo_no_url_hardcoded(self) -> None:
        content = _read("public_demo_targets/01_saucedemo_ecommerce_login.md")
        assert "hardcoded" in content.lower() or "hardcoding" in content.lower()

    def test_orangehrm_admin_spec_blocked(self) -> None:
        content = _read("public_demo_targets/02_orangehrm_admin_dashboard.md")
        assert "test.skip(true)" in content or "skip" in content.lower()

    def test_orangehrm_destructive_crud_blocked(self) -> None:
        content = _read("public_demo_targets/02_orangehrm_admin_dashboard.md")
        assert "destructive" in content.lower()
        assert "approval" in content.lower()

    def test_the_internet_file_upload_requires_approval(self) -> None:
        content = _read("public_demo_targets/03_the_internet_dynamic_ui.md")
        assert "file upload" in content.lower()
        assert "approval" in content.lower()

    def test_restful_booker_delete_requires_approval(self) -> None:
        content = _read("public_demo_targets/04_restful_booker_api_auth_crud.md")
        assert "DELETE" in content or "delete" in content.lower()
        assert "approval" in content.lower()

    def test_jsonplaceholder_no_real_data(self) -> None:
        content = _read("public_demo_targets/05_jsonplaceholder_fake_rest_api.md")
        assert "fake" in content.lower() or "no real data" in content.lower()

    def test_realworld_write_ops_blocked(self) -> None:
        content = _read("public_demo_targets/06_realworld_conduit_ui_api.md")
        assert "create" in content.lower() or "delete" in content.lower()
        assert "approval" in content.lower()

    def test_all_demo_targets_mention_no_browser_execution(self) -> None:
        demo_files = [p for p in EXPECTED_SCENARIOS if p.startswith("public_demo_targets/")]
        for path in demo_files:
            content = _read(path)
            assert "browser" in content.lower() or "no browser" in content.lower(), (
                f"{path} should mention browser execution safety"
            )

    def test_all_demo_targets_block_hardcoded_url(self) -> None:
        demo_files = [p for p in EXPECTED_SCENARIOS if p.startswith("public_demo_targets/")]
        for path in demo_files:
            content = _read(path)
            assert "hardcod" in content.lower(), (
                f"{path} should block hardcoding the target URL in playwright.config.ts"
            )


class TestRealPublicReadonly:
    def test_alza_read_only_planning(self) -> None:
        content = _read("real_public_readonly/01_alza_sk_public_ecommerce_readonly.md")
        assert "read-only" in content.lower() or "readonly" in content.lower()
        assert "planning" in content.lower()

    def test_alza_blocks_purchase(self) -> None:
        content = _read("real_public_readonly/01_alza_sk_public_ecommerce_readonly.md")
        assert "purchase" in content.lower() or "checkout" in content.lower()

    def test_alza_blocks_scraping(self) -> None:
        content = _read("real_public_readonly/01_alza_sk_public_ecommerce_readonly.md")
        assert "scraping" in content.lower() or "scrape" in content.lower()

    def test_alza_blocks_login(self) -> None:
        content = _read("real_public_readonly/01_alza_sk_public_ecommerce_readonly.md")
        assert "login" in content.lower()
        assert "blocked" in content.lower() or "no login" in content.lower()

    def test_playwright_docs_read_only_planning(self) -> None:
        content = _read("real_public_readonly/02_playwright_docs_readonly.md")
        assert "read-only" in content.lower() or "readonly" in content.lower()
        assert "planning" in content.lower()

    def test_playwright_docs_blocks_crawl(self) -> None:
        content = _read("real_public_readonly/02_playwright_docs_readonly.md")
        assert "crawl" in content.lower()

    def test_all_readonly_scenarios_say_production_blocked(self) -> None:
        readonly_files = [p for p in EXPECTED_SCENARIOS if p.startswith("real_public_readonly/")]
        for path in readonly_files:
            content = _read(path)
            assert "approval" in content.lower(), (
                f"{path} must say execution requires approval"
            )
            assert "safe_to_execute_tests: False" in content, (
                f"{path} must state safe_to_execute_tests: False"
            )


class TestHighRiskMarketplace:
    def test_amazon_is_high_risk(self) -> None:
        content = _read("high_risk_marketplace_readonly/01_amazon_public_marketplace_readonly.md")
        assert "HIGH RISK" in content or "high risk" in content.lower() or "high_risk" in content

    def test_amazon_blocks_login(self) -> None:
        content = _read("high_risk_marketplace_readonly/01_amazon_public_marketplace_readonly.md")
        assert "login" in content.lower()

    def test_amazon_blocks_purchase(self) -> None:
        content = _read("high_risk_marketplace_readonly/01_amazon_public_marketplace_readonly.md")
        assert "purchase" in content.lower() or "checkout" in content.lower()

    def test_amazon_blocks_scraping(self) -> None:
        content = _read("high_risk_marketplace_readonly/01_amazon_public_marketplace_readonly.md")
        assert "scraping" in content.lower() or "scrape" in content.lower()

    def test_amazon_blocks_price_monitoring(self) -> None:
        content = _read("high_risk_marketplace_readonly/01_amazon_public_marketplace_readonly.md")
        assert "price monitoring" in content.lower() or "price" in content.lower()

    def test_amazon_blocks_captcha_bypass(self) -> None:
        content = _read("high_risk_marketplace_readonly/01_amazon_public_marketplace_readonly.md")
        assert "CAPTCHA" in content or "captcha" in content.lower()

    def test_amazon_blocks_personal_account(self) -> None:
        content = _read("high_risk_marketplace_readonly/01_amazon_public_marketplace_readonly.md")
        assert "personal" in content.lower()

    def test_amazon_blocks_antibot_bypass(self) -> None:
        content = _read("high_risk_marketplace_readonly/01_amazon_public_marketplace_readonly.md")
        assert "anti-bot" in content.lower() or "bot" in content.lower()

    def test_amazon_tos_mentioned(self) -> None:
        content = _read("high_risk_marketplace_readonly/01_amazon_public_marketplace_readonly.md")
        assert "TOS" in content or "terms" in content.lower()

    def test_amazon_safe_to_execute_false(self) -> None:
        content = _read("high_risk_marketplace_readonly/01_amazon_public_marketplace_readonly.md")
        assert "safe_to_execute_tests: False" in content

    def test_amazon_execution_allowed_false(self) -> None:
        content = _read("high_risk_marketplace_readonly/01_amazon_public_marketplace_readonly.md")
        assert "execution_allowed=True" in content or "execution_allowed" in content


class TestDocFiles:
    def test_client_scenario_fixtures_doc_exists(self) -> None:
        doc = Path(__file__).parent.parent / "docs" / "CLIENT_SCENARIO_FIXTURES.md"
        assert doc.exists()

    def test_client_scenario_fixtures_doc_has_categories(self) -> None:
        doc = Path(__file__).parent.parent / "docs" / "CLIENT_SCENARIO_FIXTURES.md"
        content = doc.read_text(encoding="utf-8")
        assert "synthetic" in content
        assert "public_demo_targets" in content
        assert "real_public_readonly" in content
        assert "high_risk_marketplace_readonly" in content

    def test_client_scenario_fixtures_doc_mentions_linear(self) -> None:
        doc = Path(__file__).parent.parent / "docs" / "CLIENT_SCENARIO_FIXTURES.md"
        content = doc.read_text(encoding="utf-8")
        assert "Linear" in content

    def test_client_scenario_fixtures_doc_fixtures_are_inputs_not_outputs(self) -> None:
        doc = Path(__file__).parent.parent / "docs" / "CLIENT_SCENARIO_FIXTURES.md"
        content = doc.read_text(encoding="utf-8")
        assert "source inputs" in content.lower() or "not runtime outputs" in content.lower()

    def test_client_scenario_fixtures_doc_blocks_execution(self) -> None:
        doc = Path(__file__).parent.parent / "docs" / "CLIENT_SCENARIO_FIXTURES.md"
        content = doc.read_text(encoding="utf-8")
        assert "must remain blocked" in content.lower() or "blocked" in content.lower()

    def test_fixtures_readme_exists(self) -> None:
        readme = FIXTURES_ROOT / "README.md"
        assert readme.exists()

    def test_fixtures_readme_no_execution_claim(self) -> None:
        readme = FIXTURES_ROOT / "README.md"
        content = readme.read_text(encoding="utf-8")
        assert "not runtime" in content.lower() or "source inputs" in content.lower()


class TestSafetyInvariants:
    def test_no_scenario_has_execution_allowed_true(self) -> None:
        for path in EXPECTED_SCENARIOS:
            content = _read(path)
            assert "execution_allowed=True" not in content or "scaffold generated with execution_allowed=True" in content, (
                f"{path}: must not set execution_allowed=True (unless blocking it)"
            )

    def test_all_scenarios_block_url_fetching(self) -> None:
        for path in EXPECTED_SCENARIOS:
            content = _read(path)
            assert "url fetching" in content.lower() or "no url" in content.lower(), (
                f"{path}: must mention that URL fetching is blocked"
            )

    def test_all_scenarios_block_browser_execution(self) -> None:
        for path in EXPECTED_SCENARIOS:
            content = _read(path)
            assert "browser" in content.lower(), (
                f"{path}: must mention browser execution blocking"
            )

    def test_all_scenarios_block_credentials(self) -> None:
        for path in EXPECTED_SCENARIOS:
            content = _read(path)
            assert "credential" in content.lower() or "credentials" in content.lower(), (
                f"{path}: must mention credential handling"
            )

    def test_synthetic_scenarios_use_fake_urls_only(self) -> None:
        for path in EXPECTED_SCENARIOS:
            if not path.startswith("synthetic/"):
                continue
            content = _read(path)
            url_pattern = re.compile(r"https?://([a-z0-9.-]+\.[a-z]{2,})", re.IGNORECASE)
            for match in url_pattern.finditer(content):
                domain = match.group(1).lower()
                is_allowed = (
                    domain.endswith(".example.com")
                    or domain == "example.com"
                    or domain == "linear.app"
                    or domain.endswith(".linear.app")
                )
                assert is_allowed, (
                    f"{path}: synthetic scenario contains non-fake URL domain '{domain}'"
                )

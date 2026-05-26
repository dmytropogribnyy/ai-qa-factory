"""Scenario Execution Matrix Builder — Phase 4G.

Builds the canonical execution matrix: 9 lanes, target profiles, permission rules,
dedicated test-account plan, and per-URL/scenario routing decisions.

SAFETY:
- No execution. No subprocess. No credentials. No external calls.
- No browser launch. No Playwright. No npm/npx.
- No .env reading. No .auth reading. No storageState generation.
- This module is policy/routing/planning only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from core.schemas.scenario_execution_matrix import (
    CredentialProvisioningRoute,
    DedicatedTestAccountPlan,
    DedicatedTestAccountRequirement,
    ScenarioExecutionDecision,
    ScenarioExecutionLane,
    ScenarioExecutionMatrixReport,
    ScenarioPermissionRule,
    ScenarioTargetProfile,
)

_OUTPUTS_ROOT = Path("outputs")

# ---------------------------------------------------------------------------
# Domain/URL pattern classifiers (no fetching — pattern matching only)
# ---------------------------------------------------------------------------

_STRICTLY_BLOCKED_PATTERNS = [
    # Google OAuth — always blocked (use Phase 5G google_auth_runner instead)
    "accounts.google.com", "google.com/o/oauth2",
    # Professional platforms — auth always blocked, public readonly too unreliable
    "linkedin.com", "www.linkedin.com",
    "upwork.com", "www.upwork.com",
]

_PUBLIC_READONLY_PATTERNS = [
    "playwright.dev", "docs.playwright.dev",
]

# Amazon/Alza: allowed as public readonly targets (product/search/category pages only)
# Blocked for auth, cart, checkout, account, payment — enforced by browser_execution_runner path gates
_AMAZON_READONLY_PATTERNS = [
    "amazon.com", "amazon.de", "amazon.co.uk", "amazon.fr",
    "amazon.es", "amazon.it", "amazon.pl", "amazon.com.au",
]
_ALZA_READONLY_PATTERNS = [
    "alza.sk", "alza.cz", "alza.hu", "alza.at", "alza.de",
]
_ECOMMERCE_READONLY_PATTERNS = _AMAZON_READONLY_PATTERNS + _ALZA_READONLY_PATTERNS

_SAUCEDEMO_PATTERNS = [
    "saucedemo.com", "www.saucedemo.com",
]

_LOCAL_PATTERNS = [
    "localhost", "127.0.0.1", "0.0.0.0",
]

_AMAZON_PAY_PATTERNS = [
    "pay.amazon.com", "payments.amazon.com", "amazon-pay",
]

_LINEAR_PATTERNS = [
    "linear.app", "app.linear.app",
]

_JIRA_PATTERNS = [
    "atlassian.net/jira", "jira.", "atlassian.net",
]

_CLICKUP_ASANA_PATTERNS = [
    "app.clickup.com", "app.asana.com", "asana.com",
]


def _url_matches_any(url: str, patterns: List[str]) -> bool:
    url_lower = url.lower()
    return any(p in url_lower for p in patterns)


# ---------------------------------------------------------------------------
# ScenarioExecutionMatrixBuilder
# ---------------------------------------------------------------------------

class ScenarioExecutionMatrixBuilder:
    """Builds canonical execution matrix. No execution, no credentials, no calls."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_matrix(
        self,
        project_id: str,
        include_test_account_plan: bool = True,
        decision_url: Optional[str] = None,
        scenario_type: Optional[str] = None,
        target_category: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> ScenarioExecutionMatrixReport:
        """Build the full scenario execution matrix report."""
        lanes = self.build_lanes()
        target_profiles = self.build_target_profiles()
        permission_rules = self.build_permission_rules()

        decisions: List[ScenarioExecutionDecision] = []
        if decision_url or scenario_type:
            decision = self.decide_execution(
                project_id=project_id,
                target_url=decision_url,
                scenario_type=scenario_type or "",
                target_category=target_category,
                profile=profile,
            )
            decisions.append(decision)

        plan: Optional[DedicatedTestAccountPlan] = None
        if include_test_account_plan:
            plan = self.build_dedicated_test_account_plan(project_id)

        allowed_now = sum(1 for ln in lanes if ln.allowed_now)
        planned = sum(1 for ln in lanes if not ln.allowed_now and ln.status == "planned")
        blocked = sum(1 for ln in lanes if ln.status == "blocked")

        return ScenarioExecutionMatrixReport(
            project_id=project_id,
            matrix_version="1.0.0",
            lanes=lanes,
            permission_rules=permission_rules,
            target_profiles=target_profiles,
            decisions=decisions,
            dedicated_test_account_plan=plan,
            allowed_now_count=allowed_now,
            planned_count=planned,
            blocked_count=blocked,
            notes=[
                "Phase 4G: Scenario Execution Matrix and Dedicated Test Account Planning.",
                "No execution was performed in this phase.",
                "No credentials were used.",
                "No external calls were made.",
                "This is a routing/policy/planning layer only.",
                "Allowed-now lanes: no_auth_demo_smoke, no_auth_public_readonly_smoke, demo_auth_smoke.",
                "Phase 5H: Amazon/Alza public readonly enabled via readonly profile + path gates.",
                "Phase 5H: Linear added as task source integration (read-only API, not browser target).",
                "Future lanes require explicit future phase approval.",
                "Strictly blocked: Google OAuth, LinkedIn, Upwork, Amazon/Alza auth/cart/checkout.",
            ],
        )

    def build_lanes(self) -> List[ScenarioExecutionLane]:
        """Build all 9 canonical execution lanes."""
        return [
            self._lane_no_auth_demo_smoke(),
            self._lane_no_auth_public_readonly_smoke(),
            self._lane_demo_auth_smoke(),
            self._lane_dedicated_test_account_auth_future(),
            self._lane_staging_client_app_future(),
            self._lane_production_readonly_future(),
            self._lane_sandbox_payment_future(),
            self._lane_task_source_integration_future(),
            self._lane_strictly_blocked(),
        ]

    def build_target_profiles(self) -> List[ScenarioTargetProfile]:
        return [
            ScenarioTargetProfile(
                id="saucedemo_no_auth",
                label="SauceDemo — no-auth demo smoke",
                target_url_pattern="saucedemo.com",
                target_category="public_demo_target",
                scenario_type="no_auth_smoke",
                execution_lane="no_auth_demo_smoke",
                allowed_now=True,
                approved_profile=True,
                requires_credentials=False,
                allowed_credentials=[],
                blocked_actions=["auth", "payment", "checkout", "order_creation"],
                examples=["https://www.saucedemo.com"],
                notes=["Requires --approve-demo-execution."],
            ),
            ScenarioTargetProfile(
                id="the_internet_no_auth",
                label="The Internet — no-auth demo smoke",
                target_url_pattern="the-internet.herokuapp.com",
                target_category="public_demo_target",
                scenario_type="no_auth_smoke",
                execution_lane="no_auth_demo_smoke",
                allowed_now=True,
                approved_profile=True,
                requires_credentials=False,
                blocked_actions=["auth", "payment", "checkout"],
                examples=["https://the-internet.herokuapp.com"],
                notes=["Requires --approve-demo-execution."],
            ),
            ScenarioTargetProfile(
                id="localhost_no_auth",
                label="Localhost — local dev smoke",
                target_url_pattern="localhost",
                target_category="local",
                scenario_type="no_auth_smoke",
                execution_lane="no_auth_demo_smoke",
                allowed_now=True,
                approved_profile=True,
                requires_credentials=False,
                blocked_actions=["auth_with_personal_credentials", "payment"],
                examples=["http://localhost:3000", "http://127.0.0.1:8080"],
                notes=["Requires --approve-demo-execution."],
            ),
            ScenarioTargetProfile(
                id="playwright_dev_readonly",
                label="Playwright.dev — public readonly smoke",
                target_url_pattern="playwright.dev",
                target_category="real_public_readonly",
                scenario_type="readonly_smoke",
                execution_lane="no_auth_public_readonly_smoke",
                allowed_now=True,
                approved_profile=True,
                requires_credentials=False,
                blocked_actions=["auth", "forms", "login", "scraping", "crawling"],
                examples=["https://playwright.dev", "https://playwright.dev/docs/intro"],
                notes=["Requires --approve-public-readonly-execution. Read-only navigation only."],
            ),
            ScenarioTargetProfile(
                id="saucedemo_demo_auth",
                label="SauceDemo — demo auth smoke",
                target_url_pattern="saucedemo.com",
                target_category="public_demo_target",
                scenario_type="demo_auth",
                execution_lane="demo_auth_smoke",
                allowed_now=True,
                approved_profile=True,
                requires_credentials=True,
                allowed_credentials=["public_demo_profile"],
                blocked_actions=["personal_credentials", "production_credentials", "payment"],
                examples=["https://www.saucedemo.com (with demo auth)"],
                notes=["Requires --approve-demo-auth-execution. Public demo credentials only."],
            ),
            ScenarioTargetProfile(
                id="amazon_public_readonly",
                label="Amazon — public read-only navigation",
                target_url_pattern="amazon.com / amazon.de / amazon.co.uk / ...",
                target_category="ecommerce_public_readonly",
                scenario_type="public_readonly_navigation",
                execution_lane="no_auth_public_readonly_smoke",
                allowed_now=True,
                approved_profile=True,
                requires_credentials=False,
                blocked_actions=[
                    "signin", "cart", "checkout", "payment", "order_creation",
                    "account_access", "wishlist", "scraping",
                ],
                examples=[
                    "https://www.amazon.com/dp/<ASIN>",
                    "https://www.amazon.de/s?k=query",
                ],
                notes=[
                    "Requires --approve-public-readonly-execution --readonly-profile amazon_public_readonly.",
                    "Allowed: product pages (/dp/), search (/s?), category pages, homepage.",
                    "Path gates enforced: /signin /cart /checkout /account /order /payment always blocked.",
                    "CAPTCHA: if encountered, test fails gracefully. No bypass.",
                    "Auth/cart/checkout always blocked regardless of approval.",
                ],
            ),
            ScenarioTargetProfile(
                id="alza_public_readonly",
                label="Alza — public read-only navigation",
                target_url_pattern="alza.sk / alza.cz / alza.hu / alza.at / alza.de",
                target_category="ecommerce_public_readonly",
                scenario_type="public_readonly_navigation",
                execution_lane="no_auth_public_readonly_smoke",
                allowed_now=True,
                approved_profile=True,
                requires_credentials=False,
                blocked_actions=[
                    "prihlasit", "kosik", "platba", "objednavka", "moj-ucet",
                    "cart", "checkout", "payment", "order_creation", "scraping",
                ],
                examples=[
                    "https://www.alza.sk/notebooky/",
                    "https://www.alza.cz/hledat?q=query",
                ],
                notes=[
                    "Requires --approve-public-readonly-execution --readonly-profile alza_public_readonly.",
                    "Allowed: product detail, category, search pages.",
                    "Path gates enforced: /prihlasit /kosik /platba /objednavka /moj-ucet always blocked.",
                    "CAPTCHA: if encountered, test fails gracefully. No bypass.",
                    "Auth/cart/checkout always blocked regardless of approval.",
                ],
            ),
            ScenarioTargetProfile(
                id="google_oauth_blocked",
                label="Google personal OAuth — strictly blocked",
                target_url_pattern="accounts.google.com",
                target_category="personal_oauth",
                scenario_type="production_auth",
                execution_lane="strictly_blocked",
                allowed_now=False,
                approved_profile=False,
                requires_credentials=False,
                blocked_actions=["personal_account_login", "oauth", "gmail", "google_drive"],
                examples=["https://accounts.google.com"],
                notes=["Google personal OAuth is always blocked."],
            ),
            ScenarioTargetProfile(
                id="linkedin_blocked",
                label="LinkedIn — strictly blocked",
                target_url_pattern="linkedin.com",
                target_category="personal_oauth",
                scenario_type="production_auth",
                execution_lane="strictly_blocked",
                allowed_now=False,
                approved_profile=False,
                requires_credentials=False,
                blocked_actions=["login", "scraping", "profile_access"],
                examples=["https://www.linkedin.com"],
                notes=["LinkedIn login is always blocked."],
            ),
            ScenarioTargetProfile(
                id="upwork_blocked",
                label="Upwork — strictly blocked",
                target_url_pattern="upwork.com",
                target_category="personal_oauth",
                scenario_type="production_auth",
                execution_lane="strictly_blocked",
                allowed_now=False,
                approved_profile=False,
                requires_credentials=False,
                blocked_actions=["login", "scraping", "account_access"],
                examples=["https://www.upwork.com"],
                notes=["Upwork login is always blocked."],
            ),
            ScenarioTargetProfile(
                id="linear_task_source",
                label="Linear — task source (not app under test)",
                target_url_pattern="linear.app",
                target_category="task_source",
                scenario_type="task_source",
                execution_lane="task_source_integration_future",
                allowed_now=False,
                approved_profile=False,
                requires_credentials=False,
                blocked_actions=["login_as_app_under_test", "writeback_without_approval",
                                  "status_change_without_approval"],
                examples=["https://linear.app/acme/issue/QA-123/example"],
                notes=[
                    "Linear URLs are task sources — requirement references, not app-under-test.",
                    "Task source integration is planned for Phase 5D.",
                    "Read-only API token via vault reference only.",
                ],
            ),
            ScenarioTargetProfile(
                id="amazon_pay_sandbox_future",
                label="Amazon Pay Sandbox — future planned",
                target_url_pattern="pay.amazon.com",
                target_category="payment_sandbox",
                scenario_type="amazon_pay_sandbox",
                execution_lane="sandbox_payment_future",
                allowed_now=False,
                approved_profile=False,
                requires_credentials=True,
                allowed_credentials=["sandbox_buyer_account", "payment_sandbox"],
                blocked_actions=["real_payment", "real_order", "production_buyer_account"],
                examples=["https://pay.amazon.com (sandbox mode)"],
                notes=[
                    "Amazon Pay Sandbox is future Phase 5C only.",
                    "Requires sandbox buyer account and explicit approval.",
                    "Amazon.com retail checkout remains blocked.",
                ],
            ),
            ScenarioTargetProfile(
                id="staging_dedicated_test_account",
                label="Client staging — dedicated test account (future)",
                target_url_pattern="staging.*",
                target_category="staging",
                scenario_type="dedicated_test_account_auth",
                execution_lane="dedicated_test_account_auth_future",
                allowed_now=False,
                approved_profile=False,
                requires_credentials=True,
                allowed_credentials=["dedicated_test_account", "vault_reference"],
                blocked_actions=["personal_credentials", "production_credentials",
                                  "payment_without_sandbox"],
                examples=["https://staging.example.com", "https://qa.example.com"],
                notes=["Dedicated test-account auth is planned for Phase 5A."],
            ),
        ]

    def build_permission_rules(self) -> List[ScenarioPermissionRule]:
        return [
            ScenarioPermissionRule(
                id="rule_no_auth_demo",
                scenario_type="no_auth_smoke",
                target_pattern="saucedemo.com | the-internet.herokuapp.com | localhost",
                target_category="public_demo_target | local | localhost",
                execution_lane="no_auth_demo_smoke",
                allowed_now=True,
                requires_approval=True,
                approval_flags=["--approve-demo-execution"],
                credentials_allowed=False,
                credential_policy="No credentials. Public demo targets only.",
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                notes=["Allowed now with --approve-demo-execution."],
            ),
            ScenarioPermissionRule(
                id="rule_public_readonly",
                scenario_type="readonly_smoke",
                target_pattern="playwright.dev",
                target_category="real_public_readonly",
                execution_lane="no_auth_public_readonly_smoke",
                allowed_now=True,
                requires_approval=True,
                approval_flags=["--approve-public-readonly-execution"],
                credentials_allowed=False,
                credential_policy="No credentials. Read-only navigation only.",
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                notes=["Allowed now with --approve-public-readonly-execution."],
            ),
            ScenarioPermissionRule(
                id="rule_demo_auth",
                scenario_type="demo_auth",
                target_pattern="saucedemo.com",
                target_category="public_demo_target",
                execution_lane="demo_auth_smoke",
                allowed_now=True,
                requires_approval=True,
                approval_flags=["--approve-demo-auth-execution"],
                credentials_allowed=True,
                credential_policy="Public demo credentials only (SauceDemo — publicly published). Injected into env only.",
                storage_state_allowed=True,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                notes=[
                    "Allowed now with --approve-demo-auth-execution.",
                    "Only saucedemo_demo_auth profile allowed.",
                    "Credentials never appear in artifacts.",
                ],
            ),
            ScenarioPermissionRule(
                id="rule_dedicated_test_account_future",
                scenario_type="dedicated_test_account_auth",
                target_pattern="staging.* | qa.* | test.*",
                target_category="staging | client_test_environment",
                execution_lane="dedicated_test_account_auth_future",
                allowed_now=False,
                requires_approval=True,
                approval_flags=["--approve-dedicated-test-account-execution (future)"],
                credentials_allowed=False,
                credential_policy="Dedicated test account required. Vault/runtime reference only. Not allowed now.",
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                blocked_reason="Dedicated test-account execution requires Phase 5A approval.",
                notes=["Not allowed now. Future Phase 5A."],
            ),
            ScenarioPermissionRule(
                id="rule_staging_client_app_future",
                scenario_type="staging_client_app",
                target_pattern="staging.* | client staging URL",
                target_category="staging | client_test_environment",
                execution_lane="staging_client_app_future",
                allowed_now=False,
                requires_approval=True,
                approval_flags=["--approve-staging-execution (future)"],
                credentials_allowed=False,
                credential_policy="Client-provided staging account. Vault reference only. Not allowed now.",
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                blocked_reason="Staging client app execution requires Phase 5A approval.",
            ),
            ScenarioPermissionRule(
                id="rule_sandbox_payment_future",
                scenario_type="amazon_pay_sandbox",
                target_pattern="pay.amazon.com | stripe test mode",
                target_category="payment_sandbox",
                execution_lane="sandbox_payment_future",
                allowed_now=False,
                requires_approval=True,
                approval_flags=["--approve-sandbox-payment-execution (future)"],
                credentials_allowed=False,
                credential_policy="Sandbox buyer account only. Not allowed now.",
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                blocked_reason="Sandbox payment execution requires Phase 5C approval.",
            ),
            ScenarioPermissionRule(
                id="rule_task_source_future",
                scenario_type="task_source",
                target_pattern="linear.app | atlassian.net | app.clickup.com",
                target_category="task_source",
                execution_lane="task_source_integration_future",
                allowed_now=False,
                requires_approval=True,
                approval_flags=["--approve-task-source-integration (future)"],
                credentials_allowed=False,
                credential_policy="Read-only API token via vault reference only. Not allowed now.",
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                blocked_reason="Task source integration requires Phase 5D approval.",
                notes=["Task source URLs are requirement references, not app-under-test."],
            ),
            ScenarioPermissionRule(
                id="rule_amazon_retail_blocked",
                scenario_type="marketplace_checkout",
                target_pattern="amazon.com",
                target_category="high_risk_marketplace",
                execution_lane="strictly_blocked",
                allowed_now=False,
                requires_approval=False,
                approval_flags=[],
                credentials_allowed=False,
                credential_policy="No credentials accepted. Strictly blocked.",
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                blocked_reason="Amazon.com retail login/checkout is always blocked.",
            ),
            ScenarioPermissionRule(
                id="rule_alza_production_blocked",
                scenario_type="production_auth",
                target_pattern="alza.sk",
                target_category="high_risk_marketplace",
                execution_lane="strictly_blocked",
                allowed_now=False,
                requires_approval=False,
                approval_flags=[],
                credentials_allowed=False,
                credential_policy="No credentials accepted. Strictly blocked.",
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                blocked_reason="Alza.sk production login/checkout is always blocked.",
            ),
            ScenarioPermissionRule(
                id="rule_google_oauth_blocked",
                scenario_type="production_auth",
                target_pattern="accounts.google.com | google.com/o/oauth2",
                target_category="personal_oauth",
                execution_lane="strictly_blocked",
                allowed_now=False,
                requires_approval=False,
                approval_flags=[],
                credentials_allowed=False,
                credential_policy="No credentials accepted. Strictly blocked.",
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                blocked_reason="Google personal OAuth is always blocked.",
            ),
            ScenarioPermissionRule(
                id="rule_linkedin_upwork_blocked",
                scenario_type="production_auth",
                target_pattern="linkedin.com | upwork.com",
                target_category="personal_oauth",
                execution_lane="strictly_blocked",
                allowed_now=False,
                requires_approval=False,
                approval_flags=[],
                credentials_allowed=False,
                credential_policy="No credentials accepted. Strictly blocked.",
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                blocked_reason="LinkedIn and Upwork login is always blocked.",
            ),
            ScenarioPermissionRule(
                id="rule_scraping_blocked",
                scenario_type="scraping_crawling",
                target_pattern="any",
                target_category="any",
                execution_lane="strictly_blocked",
                allowed_now=False,
                requires_approval=False,
                approval_flags=[],
                credentials_allowed=False,
                credential_policy="No credentials accepted. Strictly blocked.",
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                blocked_reason="Scraping, crawling, price monitoring, and review scraping are always blocked.",
            ),
            ScenarioPermissionRule(
                id="rule_load_security_blocked",
                scenario_type="load_or_security_testing",
                target_pattern="any",
                target_category="any",
                execution_lane="strictly_blocked",
                allowed_now=False,
                requires_approval=False,
                approval_flags=[],
                credentials_allowed=False,
                credential_policy="No credentials accepted. Strictly blocked without explicit scope.",
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                blocked_reason="Load and security testing without explicit scope is always blocked.",
            ),
        ]

    def build_dedicated_test_account_plan(self, project_id: str) -> DedicatedTestAccountPlan:
        requirements = self._build_test_account_requirements()
        routes = self.build_credential_provisioning_routes()
        planned = sum(1 for r in requirements if r.approved_now is False and r.required)
        blocked = sum(1 for r in requirements if not r.acceptable_sources)

        return DedicatedTestAccountPlan(
            project_id=project_id,
            requirements=requirements,
            provisioning_routes=routes,
            allowed_now=False,
            planned_count=planned,
            blocked_count=blocked,
            blockers=[
                "Dedicated test-account execution is not approved now.",
                "All dedicated test-account lanes require future explicit phase approval.",
                "No personal/production credentials are acceptable regardless of user input.",
                "Repo-stored secrets are never acceptable.",
            ],
            warnings=[
                "When a future phase approves dedicated test-account auth, vault reference or runtime input is required.",
                "storageState for dedicated accounts must remain internal-only and gitignored.",
            ],
            notes=[
                "Phase 4G: Dedicated Test Account Planning — planning layer only.",
                "No execution. No credentials. No external calls.",
                "safe_for_execution_now=False always.",
                "personal_account_allowed=False always.",
                "production_account_allowed=False always.",
                "repo_storage_allowed=False always.",
            ],
        )

    def build_credential_provisioning_routes(self) -> List[CredentialProvisioningRoute]:
        return [
            CredentialProvisioningRoute(
                id="public_demo_profile_current",
                route_type="public_demo_profile",
                description="Hardcoded public demo profile metadata. Credential values injected into subprocess env only at runtime.",
                allowed_now=True,
                approved_now=True,
                secret_storage_location="hardcoded public demo profile metadata / runtime env injection only",
                requires_redaction=True,
                notes=[
                    "Allowed only for demo_auth_smoke lane with --approve-demo-auth-execution.",
                    "Credential values injected into subprocess env only — never logged or stored in artifacts.",
                    "Labels in artifacts do not contain raw credential values.",
                ],
            ),
            CredentialProvisioningRoute(
                id="vault_reference_future",
                route_type="vault_reference",
                description="External vault / future integration (e.g., HashiCorp Vault, AWS Secrets Manager).",
                allowed_now=False,
                approved_now=False,
                secret_storage_location="external vault / future integration",
                requires_redaction=True,
                notes=["Not allowed now. Required for dedicated test-account lanes in Phase 5A+."],
            ),
            CredentialProvisioningRoute(
                id="runtime_secret_input_future",
                route_type="runtime_secret_input",
                description="Runtime-only secret input, never persisted.",
                allowed_now=False,
                approved_now=False,
                secret_storage_location="runtime-only input, never persisted",
                requires_redaction=True,
                notes=["Not allowed now. Future optional route for Phase 5A+."],
            ),
            CredentialProvisioningRoute(
                id="client_provided_test_account_future",
                route_type="client_provided_test_account",
                description="Client-provided test account credentials via secure channel or vault reference.",
                allowed_now=False,
                approved_now=False,
                secret_storage_location="client-provided secure channel / future vault reference",
                requires_redaction=True,
                notes=["Not allowed now. Required for staging/dedicated-test-account lanes in Phase 5A+."],
            ),
            CredentialProvisioningRoute(
                id="repo_storage_blocked",
                route_type="repo_storage",
                description="Storing secrets in the repository. Always blocked.",
                allowed_now=False,
                approved_now=False,
                secret_storage_location="repository",
                requires_redaction=True,
                notes=["Repo-stored secrets are never allowed under any phase or approval."],
            ),
        ]

    def decide_execution(
        self,
        project_id: str,
        target_url: Optional[str],
        scenario_type: str,
        target_category: Optional[str] = None,
        profile: Optional[str] = None,
    ) -> ScenarioExecutionDecision:
        """Classify a URL/scenario into an execution lane and produce a decision."""
        url = (target_url or "").lower()
        stype = (scenario_type or "").lower()

        # --- Strictly blocked ---
        if _url_matches_any(url, _STRICTLY_BLOCKED_PATTERNS) and not _url_matches_any(url, _AMAZON_PAY_PATTERNS):
            return self._decision_blocked(project_id, target_url, stype, url)

        # --- E-commerce public readonly (Amazon / Alza) ---
        # Auth, cart, checkout, payment, orders are always blocked.
        # Public product/search/category navigation is allowed via readonly profile.
        if _url_matches_any(url, _ECOMMERCE_READONLY_PATTERNS) and not _url_matches_any(url, _AMAZON_PAY_PATTERNS):
            is_auth_flow = any(k in stype for k in (
                "login", "auth", "signin", "checkout", "cart", "payment",
                "order", "account", "wishlist", "register",
            ))
            if is_auth_flow:
                return ScenarioExecutionDecision(
                    project_id=project_id,
                    input_label=f"ecommerce_auth_blocked @ {target_url}",
                    target_url=target_url,
                    target_category="high_risk_marketplace",
                    scenario_type=stype,
                    execution_lane="strictly_blocked",
                    allowed_now=False,
                    implemented_now=False,
                    blockers=[
                        "Auth/cart/checkout/payment flows on Amazon/Alza are always blocked.",
                        "Use a dedicated test account on a staging/sandbox environment instead.",
                    ],
                )
            site = "amazon" if _url_matches_any(url, _AMAZON_READONLY_PATTERNS) else "alza"
            profile = f"{site}_public_readonly"
            return ScenarioExecutionDecision(
                project_id=project_id,
                input_label=f"ecommerce_readonly @ {target_url}",
                target_url=target_url,
                target_category="ecommerce_public_readonly",
                scenario_type="public_readonly_navigation",
                execution_lane="no_auth_public_readonly_smoke",
                allowed_now=True,
                implemented_now=True,
                required_approval_flags=[
                    "--approve-public-readonly-execution",
                    f"--readonly-profile {profile}",
                ],
                blockers=[],
                safe_next_steps=[
                    f"Run with --approve-public-readonly-execution --readonly-profile {profile}",
                    "Scaffold must only navigate to product/search/category pages.",
                    "Blocked paths: /signin /cart /checkout /account /order /payment",
                ],
                notes=[
                    "Public read-only navigation: product pages, search, categories only.",
                    "No auth. No form submission. No cookies set. No credentials.",
                    "CAPTCHA: if encountered, test fails gracefully — no bypass.",
                ],
            )

        # Load / security / scraping
        if any(k in stype for k in ("scrap", "crawl", "load_test", "security_test", "price_monitor")):
            return ScenarioExecutionDecision(
                project_id=project_id,
                input_label=f"{stype} @ {target_url}",
                target_url=target_url,
                target_category="any",
                scenario_type=stype,
                execution_lane="strictly_blocked",
                allowed_now=False,
                implemented_now=False,
                blockers=[
                    f"Scenario type '{stype}' is always blocked without explicit future scope approval."
                ],
                notes=["Scraping, crawling, load/security testing are strictly blocked."],
            )

        # Real payment / real order
        if any(k in stype for k in ("real_payment", "real_order", "marketplace_checkout")):
            if not _url_matches_any(url, _AMAZON_PAY_PATTERNS):
                return ScenarioExecutionDecision(
                    project_id=project_id,
                    input_label=f"{stype} @ {target_url}",
                    target_url=target_url,
                    target_category="high_risk_marketplace",
                    scenario_type=stype,
                    execution_lane="strictly_blocked",
                    allowed_now=False,
                    implemented_now=False,
                    blockers=[f"Real payment/order scenario '{stype}' is strictly blocked."],
                )

        # --- Amazon Pay Sandbox (future) ---
        if _url_matches_any(url, _AMAZON_PAY_PATTERNS) or "amazon_pay_sandbox" in stype:
            return ScenarioExecutionDecision(
                project_id=project_id,
                input_label=f"amazon_pay_sandbox @ {target_url}",
                target_url=target_url,
                target_category="payment_sandbox",
                scenario_type="amazon_pay_sandbox",
                execution_lane="sandbox_payment_future",
                allowed_now=False,
                implemented_now=False,
                required_approval_flags=["--approve-sandbox-payment-execution (future Phase 5C)"],
                blockers=["Amazon Pay Sandbox execution requires Phase 5C approval."],
                safe_next_steps=["Wait for Phase 5C approval before attempting sandbox payment testing."],
                notes=["Amazon Pay Sandbox is planned for Phase 5C. Amazon.com retail is always blocked."],
            )

        # --- Linear / Jira / ClickUp task source (future) ---
        if _url_matches_any(url, _LINEAR_PATTERNS + _JIRA_PATTERNS + _CLICKUP_ASANA_PATTERNS) or "task_source" in stype:
            return ScenarioExecutionDecision(
                project_id=project_id,
                input_label=f"task_source @ {target_url}",
                target_url=target_url,
                target_category="task_source",
                scenario_type="task_source",
                execution_lane="task_source_integration_future",
                allowed_now=False,
                implemented_now=False,
                required_approval_flags=["--approve-task-source-integration (future Phase 5D)"],
                blockers=["Task source integration requires Phase 5D approval."],
                safe_next_steps=[
                    "Use task URL as requirement reference in INPUT_MAP.json (task_source field).",
                    "Do not treat task URL as app-under-test target.",
                ],
                notes=[
                    "Linear/Jira/ClickUp URLs are requirement sources, not app-under-test.",
                    "Task source integration planned for Phase 5D with read-only API token.",
                ],
            )

        # --- Playwright.dev public readonly (allowed now) ---
        if _url_matches_any(url, _PUBLIC_READONLY_PATTERNS) or "readonly_smoke" in stype:
            return ScenarioExecutionDecision(
                project_id=project_id,
                input_label=f"readonly_smoke @ {target_url or 'playwright.dev'}",
                target_url=target_url or "https://playwright.dev",
                target_category="real_public_readonly",
                scenario_type="readonly_smoke",
                execution_lane="no_auth_public_readonly_smoke",
                allowed_now=True,
                implemented_now=True,
                required_approval_flags=["--approve-public-readonly-execution"],
                selected_tool="tools/run_demo_execution.py",
                credentials_required=False,
                credentials_allowed=False,
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                safe_next_steps=[
                    "Run: python tools/run_demo_execution.py --project-id <id> "
                    "--approve-public-readonly-execution --readonly-profile playwright_docs_readonly "
                    "--command-mode readonly_smoke"
                ],
                notes=["Read-only navigation only. No auth, no forms."],
            )

        # --- SauceDemo demo auth (allowed now) ---
        if _url_matches_any(url, _SAUCEDEMO_PATTERNS) and "demo_auth" in stype:
            return ScenarioExecutionDecision(
                project_id=project_id,
                input_label=f"demo_auth @ {target_url}",
                target_url=target_url,
                target_category="public_demo_target",
                scenario_type="demo_auth",
                execution_lane="demo_auth_smoke",
                allowed_now=True,
                implemented_now=True,
                required_approval_flags=["--approve-demo-auth-execution"],
                selected_tool="tools/run_demo_auth.py",
                credentials_required=True,
                credentials_allowed=True,
                storage_state_allowed=True,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                safe_next_steps=[
                    "Run: python tools/run_demo_auth.py --project-id <id> "
                    "--approve-demo-auth-execution --auth-profile saucedemo_demo_auth "
                    "--command-mode auth_smoke"
                ],
                notes=["Public demo credentials only. Injected into env — never in artifacts."],
            )

        # --- SauceDemo or local no-auth smoke (allowed now) ---
        if (
            _url_matches_any(url, _SAUCEDEMO_PATTERNS + _LOCAL_PATTERNS)
            or "no_auth_smoke" in stype
            or "no_auth" in stype
        ):
            cat = "local" if _url_matches_any(url, _LOCAL_PATTERNS) else "public_demo_target"
            return ScenarioExecutionDecision(
                project_id=project_id,
                input_label=f"no_auth_smoke @ {target_url}",
                target_url=target_url,
                target_category=cat,
                scenario_type="no_auth_smoke",
                execution_lane="no_auth_demo_smoke",
                allowed_now=True,
                implemented_now=True,
                required_approval_flags=["--approve-demo-execution"],
                selected_tool="tools/run_demo_execution.py",
                credentials_required=False,
                credentials_allowed=False,
                storage_state_allowed=False,
                evidence_internal_only=True,
                client_delivery_allowed=False,
                safe_next_steps=[
                    "Run: python tools/run_demo_execution.py --project-id <id> "
                    "--approve-demo-execution --demo-profile saucedemo_public_demo "
                    "--command-mode smoke"
                ],
                notes=["No credentials. No auth."],
            )

        # --- Dedicated test-account auth (future) ---
        if "dedicated_test_account_auth" in stype or "staging" in (target_category or "").lower():
            return ScenarioExecutionDecision(
                project_id=project_id,
                input_label=f"dedicated_test_account_auth @ {target_url}",
                target_url=target_url,
                target_category=target_category or "staging",
                scenario_type="dedicated_test_account_auth",
                execution_lane="dedicated_test_account_auth_future",
                allowed_now=False,
                implemented_now=False,
                required_approval_flags=["--approve-dedicated-test-account-execution (future Phase 5A)"],
                blockers=["Dedicated test-account execution requires Phase 5A approval."],
                safe_next_steps=[
                    "Document test account requirements in dedicated test-account plan.",
                    "Obtain explicit Phase 5A approval before execution.",
                ],
                notes=["Not allowed now. Future Phase 5A."],
            )

        # --- Unknown / fallback ---
        return ScenarioExecutionDecision(
            project_id=project_id,
            input_label=f"unknown @ {target_url}",
            target_url=target_url,
            target_category=target_category or "unknown",
            scenario_type=stype or "unknown",
            execution_lane="unknown",
            allowed_now=False,
            implemented_now=False,
            blockers=[f"Cannot classify scenario '{stype}' for target '{target_url}'."],
            warnings=["Check scenario_type and target_url. Consult SCENARIO_EXECUTION_MATRIX.md."],
            safe_next_steps=["Classify the target URL and scenario type before proceeding."],
        )

    # ------------------------------------------------------------------
    # Artifact rendering
    # ------------------------------------------------------------------

    def render_matrix_artifacts(
        self,
        report: ScenarioExecutionMatrixReport,
        project_id: str,
    ) -> Dict[str, Path]:
        out_dir = self._outputs_root / project_id / "10_execution_matrix"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: Dict[str, Path] = {}

        # Full matrix JSON
        p = out_dir / "SCENARIO_EXECUTION_MATRIX.json"
        p.write_text(json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8")
        paths["matrix_json"] = p

        # Full matrix MD
        p = out_dir / "SCENARIO_EXECUTION_MATRIX.md"
        p.write_text(self._render_matrix_md(report), encoding="utf-8")
        paths["matrix_md"] = p

        # Execution lanes
        p = out_dir / "EXECUTION_LANES.md"
        p.write_text(self._render_lanes_md(report), encoding="utf-8")
        paths["lanes_md"] = p

        # Target profiles
        p = out_dir / "TARGET_PROFILE_RULES.md"
        p.write_text(self._render_target_profiles_md(report), encoding="utf-8")
        paths["target_profiles_md"] = p

        # Permission routing table
        p = out_dir / "PERMISSION_ROUTING_TABLE.md"
        p.write_text(self._render_permission_routing_md(report), encoding="utf-8")
        paths["permission_routing_md"] = p

        # Blocked scenarios
        p = out_dir / "BLOCKED_SCENARIOS.md"
        p.write_text(self._render_blocked_md(report), encoding="utf-8")
        paths["blocked_md"] = p

        # Future scenarios
        p = out_dir / "FUTURE_SCENARIOS.md"
        p.write_text(self._render_future_md(report), encoding="utf-8")
        paths["future_md"] = p

        # Dedicated test-account plan JSON
        if report.dedicated_test_account_plan:
            p = out_dir / "DEDICATED_TEST_ACCOUNT_PLAN.json"
            p.write_text(
                json.dumps(report.dedicated_test_account_plan.to_dict(), indent=2, default=str),
                encoding="utf-8",
            )
            paths["test_account_plan_json"] = p

            p = out_dir / "DEDICATED_TEST_ACCOUNT_PLAN.md"
            p.write_text(
                self._render_test_account_plan_md(report.dedicated_test_account_plan),
                encoding="utf-8",
            )
            paths["test_account_plan_md"] = p

        # Credential provisioning routes
        p = out_dir / "CREDENTIAL_PROVISIONING_ROUTES.md"
        p.write_text(self._render_provisioning_routes_md(report), encoding="utf-8")
        paths["provisioning_routes_md"] = p

        return paths

    # ------------------------------------------------------------------
    # Private: lane builders
    # ------------------------------------------------------------------

    def _lane_no_auth_demo_smoke(self) -> ScenarioExecutionLane:
        return ScenarioExecutionLane(
            id="no_auth_demo_smoke",
            name="No-Auth Demo Smoke",
            status="implemented",
            description="Approval-gated demo smoke without authentication. SauceDemo, The Internet, localhost.",
            allowed_now=True,
            implemented=True,
            required_approval_flags=["--approve-demo-execution"],
            allowed_target_categories=["local", "localhost", "public_demo_target"],
            allowed_profiles=["saucedemo_public_demo", "the_internet_public_demo", "local"],
            allowed_credential_sources=[],
            blocked_actions=["auth", "payment", "checkout", "order_creation", "account_mutation",
                              "scraping", "crawling", "load_testing", "security_testing"],
            owner_tool="tools/run_demo_execution.py",
            evidence_root="outputs/<project_id>/07_execution/",
            notes=["Implemented. Requires --approve-demo-execution."],
        )

    def _lane_no_auth_public_readonly_smoke(self) -> ScenarioExecutionLane:
        return ScenarioExecutionLane(
            id="no_auth_public_readonly_smoke",
            name="No-Auth Public Readonly Smoke",
            status="implemented",
            description="Approval-gated read-only navigation of public pages. Playwright.dev only.",
            allowed_now=True,
            implemented=True,
            required_approval_flags=["--approve-public-readonly-execution"],
            allowed_target_categories=["real_public_readonly"],
            allowed_profiles=["playwright_docs_readonly"],
            allowed_credential_sources=[],
            blocked_actions=["auth", "forms", "login", "account_creation", "payment",
                              "checkout", "order_creation", "scraping", "crawling",
                              "link_spidering", "load_testing", "security_testing"],
            owner_tool="tools/run_demo_execution.py",
            evidence_root="outputs/<project_id>/07_execution/",
            notes=["Implemented. Requires --approve-public-readonly-execution. playwright_docs_readonly profile only."],
        )

    def _lane_demo_auth_smoke(self) -> ScenarioExecutionLane:
        return ScenarioExecutionLane(
            id="demo_auth_smoke",
            name="Demo Auth Smoke",
            status="implemented",
            description="Approval-gated auth smoke using public demo credentials. SauceDemo only.",
            allowed_now=True,
            implemented=True,
            required_approval_flags=["--approve-demo-auth-execution"],
            allowed_target_categories=["public_demo_target"],
            allowed_profiles=["saucedemo_demo_auth"],
            allowed_credential_sources=["public_demo_profile"],
            blocked_actions=["personal_credentials", "production_credentials", "client_credentials",
                              "payment", "checkout", "order_creation", "account_mutation",
                              "scraping", "crawling", "load_testing", "security_testing"],
            owner_tool="tools/run_demo_auth.py",
            evidence_root="outputs/<project_id>/09_auth/",
            notes=[
                "Implemented. Requires --approve-demo-auth-execution.",
                "Only saucedemo_demo_auth profile allowed.",
                "Public demo credentials injected into subprocess env only.",
            ],
        )

    def _lane_dedicated_test_account_auth_future(self) -> ScenarioExecutionLane:
        return ScenarioExecutionLane(
            id="dedicated_test_account_auth_future",
            name="Dedicated Test Account Auth (Future)",
            status="planned",
            description="Future: auth execution using dedicated test account. Requires Phase 5A approval.",
            allowed_now=False,
            implemented=False,
            future_phase="Phase 5A or later",
            required_approval_flags=["--approve-dedicated-test-account-execution (future)"],
            allowed_target_categories=["staging", "client_test_environment", "dedicated_test_environment"],
            allowed_profiles=[],
            allowed_credential_sources=["dedicated_test_account", "vault_reference", "user_supplied_runtime"],
            blocked_actions=["personal_credentials", "production_admin_credentials", "payment",
                              "destructive_actions", "client_delivery_without_redaction"],
            owner_tool="planned",
            evidence_root="planned",
            notes=["Not allowed now. Requires Phase 5A explicit approval, dedicated test account, and vault/runtime credential route."],
        )

    def _lane_staging_client_app_future(self) -> ScenarioExecutionLane:
        return ScenarioExecutionLane(
            id="staging_client_app_future",
            name="Staging Client App (Future)",
            status="planned",
            description="Future: execution against client staging environment. Requires Phase 5A.",
            allowed_now=False,
            implemented=False,
            future_phase="Phase 5A or later",
            required_approval_flags=["--approve-staging-execution (future)"],
            allowed_target_categories=["staging", "client_test_environment"],
            allowed_profiles=[],
            allowed_credential_sources=["dedicated_test_account", "vault_reference"],
            blocked_actions=["production_data_mutation", "destructive_actions_without_approval",
                              "payment_without_sandbox", "scraping",
                              "load_testing_without_scope", "security_testing_without_scope"],
            owner_tool="planned",
            evidence_root="planned",
            notes=["Not allowed now. Requires Phase 5A explicit approval and client-provided staging account."],
        )

    def _lane_production_readonly_future(self) -> ScenarioExecutionLane:
        return ScenarioExecutionLane(
            id="production_readonly_future",
            name="Production Readonly (Future)",
            status="planned",
            description="Future: read-only navigation of production URLs. Requires Phase 5B.",
            allowed_now=False,
            implemented=False,
            future_phase="Phase 5B or later",
            required_approval_flags=["--approve-production-readonly-execution (future)"],
            allowed_target_categories=["production_readonly", "real_public_readonly"],
            allowed_profiles=[],
            allowed_credential_sources=[],
            blocked_actions=["login", "account_creation", "cart", "checkout", "payment",
                              "order_creation", "scraping", "crawling", "load_testing", "security_testing"],
            owner_tool="planned",
            evidence_root="planned",
            notes=["Not allowed now. playwright.dev is already covered by no_auth_public_readonly_smoke."],
        )

    def _lane_sandbox_payment_future(self) -> ScenarioExecutionLane:
        return ScenarioExecutionLane(
            id="sandbox_payment_future",
            name="Sandbox Payment (Future)",
            status="planned",
            description="Future: sandbox payment flow testing. Amazon Pay Sandbox, Stripe test mode. Requires Phase 5C.",
            allowed_now=False,
            implemented=False,
            future_phase="Phase 5C or later",
            required_approval_flags=["--approve-sandbox-payment-execution (future)"],
            allowed_target_categories=["payment_sandbox", "sandbox_integration"],
            allowed_profiles=["amazon_pay_sandbox_future", "stripe_test_mode_future"],
            allowed_credential_sources=["sandbox_buyer_account", "payment_sandbox", "vault_reference"],
            blocked_actions=["real_payment", "real_order", "production_card",
                              "production_buyer_account", "marketplace_retail_checkout"],
            owner_tool="planned",
            evidence_root="planned",
            notes=[
                "Not allowed now. Requires Phase 5C explicit approval.",
                "Amazon.com retail checkout remains always blocked.",
                "Sandbox buyer account or payment provider test mode only.",
            ],
        )

    def _lane_task_source_integration_future(self) -> ScenarioExecutionLane:
        return ScenarioExecutionLane(
            id="task_source_integration_future",
            name="Task Source Integration (Future)",
            status="planned",
            description="Future: read-only task source integration (Linear, Jira, ClickUp). Requires Phase 5D.",
            allowed_now=False,
            implemented=False,
            future_phase="Phase 5D or later",
            required_approval_flags=["--approve-task-source-integration (future)"],
            allowed_target_categories=["task_source"],
            allowed_profiles=["linear_task_source_future", "jira_task_source_future",
                               "clickup_task_source_future"],
            allowed_credential_sources=["api_token_vault_reference", "oauth_app_future"],
            blocked_actions=["writeback_without_approval", "status_change_without_approval",
                              "comment_without_approval", "webhook_without_approval"],
            owner_tool="planned",
            evidence_root="planned",
            notes=[
                "Not allowed now. Requires Phase 5D explicit approval.",
                "Task source URLs are requirement references, not app-under-test.",
                "Read-only API token via vault reference only — never repo-stored.",
            ],
        )

    def _lane_strictly_blocked(self) -> ScenarioExecutionLane:
        return ScenarioExecutionLane(
            id="strictly_blocked",
            name="Strictly Blocked",
            status="blocked",
            description="Always blocked regardless of approval flags or user-provided credentials.",
            allowed_now=False,
            implemented=True,
            allowed_target_categories=[],
            allowed_profiles=[],
            allowed_credential_sources=[],
            blocked_actions=[
                "personal_account_login", "production_account_login",
                "amazon_retail_login", "alza_production_login",
                "google_personal_oauth", "linkedin_login", "upwork_login",
                "real_payment", "real_checkout", "real_order_creation",
                "scraping", "crawling", "price_monitoring", "review_scraping",
                "anti_bot_bypass", "captcha_bypass",
                "load_testing_without_scope", "security_testing_without_scope",
            ],
            owner_tool="policy",
            evidence_root=None,
            notes=[
                "Blocked at the policy level.",
                "User-provided credentials do not unblock these scenarios.",
                "Amazon.com retail, Alza production, Google OAuth, LinkedIn, Upwork are always blocked.",
            ],
        )

    # ------------------------------------------------------------------
    # Private: decision helpers
    # ------------------------------------------------------------------

    def _decision_blocked(
        self,
        project_id: str,
        target_url: Optional[str],
        stype: str,
        url: str,
    ) -> ScenarioExecutionDecision:
        if "alza" in url:
            reason = "Alza.sk production login/checkout is always blocked."
        elif "amazon" in url:
            reason = "Amazon.com retail login/checkout is always blocked."
        elif "google" in url or "accounts.google" in url:
            reason = "Google personal OAuth is always blocked."
        elif "linkedin" in url:
            reason = "LinkedIn login is always blocked."
        elif "upwork" in url:
            reason = "Upwork login is always blocked."
        else:
            reason = f"Target '{target_url}' is in the strictly blocked domain list."

        return ScenarioExecutionDecision(
            project_id=project_id,
            input_label=f"blocked @ {target_url}",
            target_url=target_url,
            target_category="strictly_blocked",
            scenario_type=stype,
            execution_lane="strictly_blocked",
            allowed_now=False,
            implemented_now=False,
            blockers=[reason],
            notes=["User-provided credentials do not unblock this scenario."],
        )

    # ------------------------------------------------------------------
    # Private: requirement builders
    # ------------------------------------------------------------------

    def _build_test_account_requirements(self) -> List[DedicatedTestAccountRequirement]:
        return [
            DedicatedTestAccountRequirement(
                id="req_dedicated_test_account_auth",
                scenario_lane="dedicated_test_account_auth_future",
                target_category="staging | client_test_environment",
                provider="client or project-created",
                account_type="dedicated_test_account",
                required=True,
                acceptable_sources=[
                    "client_provided_test_account",
                    "project_created_test_account",
                    "vault_reference",
                    "runtime_secret_input",
                ],
                forbidden_sources=[
                    "personal_account",
                    "production_account",
                    "admin_account",
                    "repo_stored_secret",
                    "chat_pasted_secret",
                ],
                requires_client_provided_account=True,
                requires_staging_environment=True,
                requires_vault_or_runtime_secret=True,
                storage_state_allowed_future=True,
                approved_now=False,
                future_phase="Phase 5A",
                blockers=["Not approved now. Requires Phase 5A explicit approval."],
                notes=["storageState internal-only and gitignored when future-allowed."],
            ),
            DedicatedTestAccountRequirement(
                id="req_staging_client_app",
                scenario_lane="staging_client_app_future",
                target_category="staging | client_test_environment",
                provider="client-provided",
                account_type="client_staging_account",
                required=True,
                acceptable_sources=[
                    "client_staging_account",
                    "dedicated_test_account",
                    "vault_reference",
                    "runtime_secret_input",
                ],
                forbidden_sources=[
                    "personal_account",
                    "production_admin_account",
                    "shared_team_account_without_scope",
                    "repo_stored_secret",
                ],
                requires_client_provided_account=True,
                requires_staging_environment=True,
                requires_vault_or_runtime_secret=True,
                storage_state_allowed_future=True,
                approved_now=False,
                future_phase="Phase 5A",
                blockers=["Not approved now. Requires Phase 5A explicit approval."],
            ),
            DedicatedTestAccountRequirement(
                id="req_sandbox_payment",
                scenario_lane="sandbox_payment_future",
                target_category="payment_sandbox",
                provider="payment provider sandbox",
                account_type="sandbox_buyer_account",
                required=True,
                acceptable_sources=[
                    "sandbox_buyer_account",
                    "sandbox_api_key_vault_reference",
                    "payment_provider_test_mode",
                ],
                forbidden_sources=[
                    "real_card",
                    "production_buyer_account",
                    "amazon_retail_account",
                    "real_order_account",
                    "repo_stored_secret",
                ],
                requires_client_provided_account=True,
                requires_staging_environment=True,
                requires_vault_or_runtime_secret=True,
                storage_state_allowed_future=False,
                approved_now=False,
                future_phase="Phase 5C",
                blockers=["Not approved now. Requires Phase 5C explicit approval."],
                notes=["Amazon.com retail checkout remains always blocked."],
            ),
            DedicatedTestAccountRequirement(
                id="req_task_source_integration",
                scenario_lane="task_source_integration_future",
                target_category="task_source",
                provider="Linear / Jira / ClickUp",
                account_type="read_only_api_token",
                required=True,
                acceptable_sources=[
                    "read_only_api_token_vault_reference",
                    "oauth_app_future",
                    "runtime_secret_input",
                ],
                forbidden_sources=[
                    "personal_token_in_repo",
                    "admin_token",
                    "write_scope_token_without_approval",
                    "webhook_secret_in_repo",
                ],
                requires_client_provided_account=True,
                requires_staging_environment=False,
                requires_vault_or_runtime_secret=True,
                storage_state_allowed_future=False,
                approved_now=False,
                future_phase="Phase 5D",
                blockers=["Not approved now. Requires Phase 5D explicit approval."],
                notes=["Read-only API token only. No writeback without explicit approval."],
            ),
            DedicatedTestAccountRequirement(
                id="req_strictly_blocked",
                scenario_lane="strictly_blocked",
                target_category="any",
                provider="none",
                account_type="none",
                required=False,
                acceptable_sources=[],
                forbidden_sources=[
                    "any_personal_account",
                    "any_production_account",
                    "any_real_payment_account",
                    "any_scraping_token",
                    "any_anti_bot_bypass_secret",
                    "any_repo_stored_secret",
                ],
                requires_client_provided_account=False,
                requires_staging_environment=False,
                requires_vault_or_runtime_secret=False,
                storage_state_allowed_future=False,
                approved_now=False,
                blockers=[
                    "Credentials cannot make a strictly blocked scenario executable.",
                    "Strictly blocked scenarios remain blocked regardless of user-provided credentials.",
                ],
            ),
        ]

    # ------------------------------------------------------------------
    # Private: markdown renderers
    # ------------------------------------------------------------------

    def _render_matrix_md(self, report: ScenarioExecutionMatrixReport) -> str:
        lines = [
            "# Scenario Execution Matrix — Phase 4G",
            "",
            "> **No execution was performed in Phase 4G.**",
            "> **No credentials were used.**",
            "> **No external calls were made.**",
            "> **This is a routing/policy/planning layer only.**",
            "",
            f"**Project:** `{report.project_id}`",
            f"**Matrix version:** `{report.matrix_version}`",
            f"**Allowed now:** {report.allowed_now_count} lanes",
            f"**Planned:** {report.planned_count} lanes",
            f"**Blocked:** {report.blocked_count} lanes",
            "",
            "## Lanes Summary",
            "",
            "| Lane | Status | Allowed Now | Approval Flag | Tool |",
            "|------|--------|-------------|---------------|------|",
        ]
        for lane in report.lanes:
            flags = ", ".join(lane.required_approval_flags) if lane.required_approval_flags else "—"
            tool = lane.owner_tool or "—"
            lines.append(
                f"| `{lane.id}` | `{lane.status}` | `{lane.allowed_now}` | {flags} | {tool} |"
            )
        lines.extend([
            "",
            "## Safety Statement",
            "",
            "- Real personal credentials remain **forbidden**.",
            "- Production credentials remain **forbidden**.",
            "- Repo-stored secrets remain **forbidden**.",
            "- Alza/Amazon production auth remains **blocked**.",
            "- Amazon Pay Sandbox is **future Phase 5C** — not allowed now.",
            "- Linear/Jira/ClickUp are **task sources** — not app-under-test.",
            "- Dedicated test accounts require **future explicit approval**.",
            "- Scraping/crawling/load/security testing remain **blocked** without explicit scope.",
            "- Real payment/order flows remain **blocked**.",
        ])
        return "\n".join(lines) + "\n"

    def _render_lanes_md(self, report: ScenarioExecutionMatrixReport) -> str:
        lines = [
            "# Execution Lanes — Phase 4G",
            "",
            "> Routing/policy reference. No execution in Phase 4G.",
            "",
        ]
        for lane in report.lanes:
            lines.extend([
                f"## {lane.id}",
                f"- **Status:** `{lane.status}`",
                f"- **Allowed now:** `{lane.allowed_now}`",
                f"- **Implemented:** `{lane.implemented}`",
            ])
            if lane.future_phase:
                lines.append(f"- **Future phase:** {lane.future_phase}")
            if lane.required_approval_flags:
                lines.append(f"- **Approval flags:** {', '.join(lane.required_approval_flags)}")
            if lane.allowed_target_categories:
                lines.append(f"- **Allowed categories:** {', '.join(lane.allowed_target_categories)}")
            if lane.owner_tool:
                lines.append(f"- **Owner tool:** `{lane.owner_tool}`")
            if lane.notes:
                lines.extend(["- **Notes:**"] + [f"  - {n}" for n in lane.notes])
            lines.append("")
        return "\n".join(lines) + "\n"

    def _render_target_profiles_md(self, report: ScenarioExecutionMatrixReport) -> str:
        lines = [
            "# Target Profile Rules — Phase 4G",
            "",
            "> Routing/policy reference. No execution in Phase 4G.",
            "",
        ]
        for p in report.target_profiles:
            lines.extend([
                f"## {p.label}",
                f"- **Lane:** `{p.execution_lane}`",
                f"- **Allowed now:** `{p.allowed_now}`",
                f"- **Target pattern:** `{p.target_url_pattern}`",
                f"- **Credentials required:** `{p.requires_credentials}`",
                f"- **Blocked actions:** {', '.join(p.blocked_actions) if p.blocked_actions else 'see lane'}",
            ])
            if p.examples:
                lines.append(f"- **Examples:** {', '.join(p.examples)}")
            lines.append("")
        return "\n".join(lines) + "\n"

    def _render_permission_routing_md(self, report: ScenarioExecutionMatrixReport) -> str:
        lines = [
            "# Permission Routing Table — Phase 4G",
            "",
            "| Rule | Scenario Type | Lane | Allowed Now | Approval Flag | Credentials | Client Delivery |",
            "|------|---------------|------|-------------|---------------|-------------|-----------------|",
        ]
        for r in report.permission_rules:
            flags = ", ".join(r.approval_flags) if r.approval_flags else "—"
            lines.append(
                f"| `{r.id}` | `{r.scenario_type}` | `{r.execution_lane}` | `{r.allowed_now}` "
                f"| {flags} | `{r.credentials_allowed}` | `{r.client_delivery_allowed}` |"
            )
        return "\n".join(lines) + "\n"

    def _render_blocked_md(self, _report: ScenarioExecutionMatrixReport) -> str:
        lines = [
            "# Blocked Scenarios — Phase 4G",
            "",
            "> These scenarios are always blocked regardless of approval flags or user-provided credentials.",
            "",
            "## Always Blocked",
            "",
            "- **Amazon.com retail** login, cart, checkout, order creation",
            "- **Alza.sk production** login, cart, checkout, order creation",
            "- **Google personal OAuth** — personal account login",
            "- **LinkedIn** login, scraping, profile access",
            "- **Upwork** login, scraping, account access",
            "- **Scraping / crawling** / price monitoring / review scraping (any target)",
            "- **Load testing** without explicit approved scope",
            "- **Security testing** without explicit approved scope",
            "- **Real payment / real order** creation",
            "- **Personal account credentials** of any kind",
            "- **Production admin credentials** of any kind",
            "- **Repo-stored secrets** of any kind",
            "",
            "## Why User-Provided Credentials Don't Unblock These",
            "",
            "The strictly_blocked lane is a policy block, not an authorization check.",
            "Providing credentials does not change the routing decision.",
        ]
        return "\n".join(lines) + "\n"

    def _render_future_md(self, report: ScenarioExecutionMatrixReport) -> str:
        lines = [
            "# Future Scenarios — Phase 4G",
            "",
            "> These lanes are planned but not implemented. Execution is not allowed now.",
            "",
        ]
        for lane in report.lanes:
            if lane.status == "planned":
                lines.extend([
                    f"## {lane.name}",
                    f"- **Lane ID:** `{lane.id}`",
                    f"- **Future phase:** {lane.future_phase}",
                    f"- **Allowed target categories:** {', '.join(lane.allowed_target_categories) if lane.allowed_target_categories else 'TBD'}",
                    f"- **Credential sources:** {', '.join(lane.allowed_credential_sources) if lane.allowed_credential_sources else 'none'}",
                    "",
                ])
        return "\n".join(lines) + "\n"

    def _render_test_account_plan_md(self, plan: DedicatedTestAccountPlan) -> str:
        lines = [
            "# Dedicated Test Account Plan — Phase 4G",
            "",
            "> **No execution. No credentials. Planning only.**",
            "> `safe_for_execution_now=False`",
            "> `personal_account_allowed=False`",
            "> `production_account_allowed=False`",
            "> `repo_storage_allowed=False`",
            "",
            f"**Project:** `{plan.project_id}`",
            f"**Allowed now:** `{plan.allowed_now}`",
            f"**Safe for execution now:** `{plan.safe_for_execution_now}`",
            "",
            "## Requirements",
            "",
        ]
        for req in plan.requirements:
            lines.extend([
                f"### {req.id}",
                f"- **Lane:** `{req.scenario_lane}`",
                f"- **Required:** `{req.required}`",
                f"- **Approved now:** `{req.approved_now}`",
                f"- **Future phase:** {req.future_phase or 'TBD'}",
                f"- **Personal account allowed:** `{req.personal_account_allowed}`",
                f"- **Production account allowed:** `{req.production_account_allowed}`",
                f"- **Acceptable sources:** {', '.join(req.acceptable_sources) if req.acceptable_sources else 'none'}",
                f"- **Forbidden sources:** {', '.join(req.forbidden_sources) if req.forbidden_sources else 'none'}",
                f"- **storageState (future):** `{req.storage_state_allowed_future}`",
            ])
            if req.blockers:
                lines.extend(["- **Blockers:**"] + [f"  - {b}" for b in req.blockers])
            lines.append("")
        return "\n".join(lines) + "\n"

    def _render_provisioning_routes_md(self, report: ScenarioExecutionMatrixReport) -> str:
        routes: List[CredentialProvisioningRoute] = []
        if report.dedicated_test_account_plan:
            routes = report.dedicated_test_account_plan.provisioning_routes
        lines = [
            "# Credential Provisioning Routes — Phase 4G",
            "",
            "> Routing/policy reference. No credentials used in Phase 4G.",
            "",
            "| Route | Allowed Now | Approved Now | Repo Storage | Logging | Client Visible |",
            "|-------|-------------|--------------|--------------|---------|----------------|",
        ]
        for r in routes:
            lines.append(
                f"| `{r.id}` | `{r.allowed_now}` | `{r.approved_now}` | `{r.repo_storage_allowed}` "
                f"| `{r.logging_allowed}` | `{r.client_visible_allowed}` |"
            )
        return "\n".join(lines) + "\n"

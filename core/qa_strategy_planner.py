"""QAStrategyPlanner — builds QA strategy and tactical planning foundation.

Phase 2C — planning only:
- No URL fetching.
- No browser execution.
- No Playwright execution.
- No credential use.
- No external calls.
- No test execution.
- No Playwright scaffold generation.
- No executable test generation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from core.schemas.project_blueprint import ProjectBlueprint
from core.schemas.project_status import ProjectStatus
from core.schemas.qa_strategy import (
    QAStrategy,
    QAStrategyArea,
    RiskMatrixItem,
    StrategyDecision,
    TacticalPlanningItem,
    TestLayerRecommendation,
)


# ---------------------------------------------------------------------------
# Signal tables (local — no imports from project_blueprint_builder)
# ---------------------------------------------------------------------------

_AUTH_SIGNALS = [
    "login", "authentication", "oauth", "sso", "magic link", "otp", "2fa",
    "two-factor", "mfa", "session", "protected route", "password reset",
    "logout", "auth flow", "sign in", "sign up", "register",
]
_API_SIGNALS = [
    "api", "endpoint", "rest", "restful", "openapi", "swagger", "postman",
    "backend", "service", "contract", "payload", "graphql", "request",
    "response schema", "status code", "rate limit",
]
_PAYMENT_SIGNALS = [
    "payment", "checkout", "stripe", "paypal", "billing", "credit card",
    "real money", "purchase", "order",
]
_MOBILE_SIGNALS = [
    "ios", "android", "react native", "flutter", "appium", "native app",
    "mobile app",
]
_INTEGRATION_SIGNALS = [
    "n8n", "make", "zapier", "webhook", "integration", "slack notify",
    "jira ticket",
]
_SECURITY_SIGNALS = [
    "security", "pentest", "owasp", "xss", "sql injection", "auth bypass",
    "vulnerability",
]
_PROD_SIGNALS = [
    "production", "live site", "real users", "real payment", "public app",
]


def _hits(text: str, signals: list) -> bool:
    lower = text.lower()
    return any(s in lower for s in signals)


# ---------------------------------------------------------------------------
# Strategy area definitions by project type
# ---------------------------------------------------------------------------

def _strategy_areas_for_type(
    project_type: str,
    text: str,
    blueprint: ProjectBlueprint,
) -> List[QAStrategyArea]:
    has_api = _hits(text, _API_SIGNALS)
    is_prod = blueprint.environment == "production"

    if project_type == "web_saas":
        areas = [
            QAStrategyArea(
                id="sa-01",
                name="Smoke / Critical Path",
                description="Verify auth, navigation, and dashboard load are working before any other testing.",
                priority="high",
                risk_level="high",
                recommended_approach="Login smoke test -> dashboard load -> primary navigation. Fail fast on critical path regressions.",
                related_surfaces=["authentication", "dashboard", "navigation"],
                blocked=False,
                notes=["First automation target — must pass before any regression suite runs."],
            ),
            QAStrategyArea(
                id="sa-02",
                name="Core User Workflows",
                description="Key user actions: forms, data operations, settings, primary feature flows.",
                priority="high",
                risk_level="medium",
                recommended_approach="Identify 3–5 critical user journeys and design happy-path tests first.",
                related_surfaces=["dashboard", "forms", "user settings"],
                blocked=False,
                notes=["Prioritize with client — not all workflows carry equal risk."],
            ),
            QAStrategyArea(
                id="sa-03",
                name="Auth and Session Management",
                description="Login, logout, session persistence, and protected route access.",
                priority="high",
                risk_level="high",
                recommended_approach="Test login -> protected page -> session timeout -> logout. Verify redirect on expired session.",
                related_surfaces=["authentication", "protected pages"],
                blocked=is_prod,
                blocked_reason="Production auth requires explicit read-only approval first." if is_prod else None,
                notes=["Requires dedicated test account — not a real user account."],
            ),
            QAStrategyArea(
                id="sa-04",
                name="Regression Coverage",
                description="Broader UI regression after smoke is stable. Prevent regressions on main flows.",
                priority="medium",
                risk_level="medium",
                recommended_approach="Build regression suite after critical path is stable. Run on every deploy via CI.",
                related_surfaces=["all covered surfaces"],
                blocked=False,
                notes=["Phase 3A / 3B — after scaffold is in place."],
            ),
            QAStrategyArea(
                id="sa-05",
                name="CI Integration Planning",
                description="Plan how tests will run in CI/CD pipeline.",
                priority="medium",
                risk_level="low",
                recommended_approach="Identify CI target (GitHub Actions, GitLab CI, etc.). Plan fast smoke gate + nightly regression.",
                related_surfaces=["ci/cd pipeline"],
                blocked=False,
                notes=["Phase 3B — framework must exist first."],
            ),
        ]
        if has_api:
            areas.insert(3, QAStrategyArea(
                id="sa-03b",
                name="API Layer",
                description="API endpoint checks where backend is accessible.",
                priority="medium",
                risk_level="medium",
                recommended_approach="Playwright API testing or pytest+requests for key endpoints. Auth header validation.",
                related_surfaces=["api endpoints"],
                blocked=False,
                notes=["Only after target URL and API access are approved."],
            ))
        return areas

    if project_type == "ecommerce":
        areas = [
            QAStrategyArea(
                id="sa-01",
                name="Catalog and Product Smoke",
                description="Browse, search, and product page loads correctly.",
                priority="high",
                risk_level="medium",
                recommended_approach="Navigate catalog -> search -> product detail page -> verify key data renders.",
                related_surfaces=["product catalog", "product page", "search"],
                blocked=False,
                notes=["Safe read-only smoke — no purchases, no account state."],
            ),
            QAStrategyArea(
                id="sa-02",
                name="Cart Operations",
                description="Add/remove/update cart items; verify persistence and totals.",
                priority="high",
                risk_level="medium",
                recommended_approach="Add item -> update quantity -> remove item -> verify price calculation.",
                related_surfaces=["cart", "product page"],
                blocked=is_prod,
                blocked_reason="Production cart operations require explicit approval." if is_prod else None,
                notes=["Use test accounts only. Verify no real orders are created."],
            ),
            QAStrategyArea(
                id="sa-03",
                name="Checkout Flow",
                description="Checkout happy path from cart to order confirmation.",
                priority="high",
                risk_level="high",
                recommended_approach="Full checkout flow with test data. Sandbox mode must be confirmed before testing payment step.",
                related_surfaces=["cart", "checkout", "order confirmation"],
                blocked=is_prod,
                blocked_reason="Production checkout blocked until read-only approval and sandbox confirmation." if is_prod else None,
                notes=["Do not use real payment methods. Sandbox credentials required."],
            ),
            QAStrategyArea(
                id="sa-04",
                name="Payment Flow Testing",
                description="Payment processing and confirmation. BLOCKED until sandbox confirmed.",
                priority="critical",
                risk_level="critical",
                recommended_approach="Use Stripe test cards or equivalent sandbox. Never test with real money. Sandbox confirmation must be in writing.",
                related_surfaces=["checkout", "payment/sandbox"],
                blocked=True,
                blocked_reason="Payment testing BLOCKED. Reason: sandbox mode not yet confirmed. Required: written client confirmation that payment sandbox (e.g. Stripe test keys) is available.",
                notes=["Approval required. Risk: payment_or_auth."],
            ),
            QAStrategyArea(
                id="sa-05",
                name="Account and Orders",
                description="Login, order history, account settings.",
                priority="medium",
                risk_level="medium",
                recommended_approach="Login -> order history -> order detail. Verify order status accuracy.",
                related_surfaces=["account/orders"],
                blocked=False,
                notes=["Test account required — not a real customer account."],
            ),
            QAStrategyArea(
                id="sa-06",
                name="Manual Exploratory",
                description="Coupons, shipping edge cases, promotional flows, error states.",
                priority="medium",
                risk_level="medium",
                recommended_approach="Structured exploratory sessions for coupons, special pricing, edge-case shipping.",
                related_surfaces=["cart", "checkout", "promotions"],
                blocked=False,
                notes=["Hard to automate fully — manual sessions provide coverage depth."],
            ),
        ]
        return areas

    if project_type == "api_backend":
        areas = [
            QAStrategyArea(
                id="sa-01",
                name="Endpoint Smoke",
                description="Happy path for each known endpoint — verify basic responses.",
                priority="high",
                risk_level="high",
                recommended_approach="GET/POST/PUT/DELETE happy paths per endpoint. Verify status codes and response shape.",
                related_surfaces=["endpoints", "request/response schemas"],
                blocked=False,
                notes=["Requires target URL approval before any API calls."],
            ),
            QAStrategyArea(
                id="sa-02",
                name="Auth and Header Validation",
                description="Token/API key behavior, unauthorized access, missing header scenarios.",
                priority="high",
                risk_level="high",
                recommended_approach="Test with valid/invalid/missing auth tokens. Verify 401/403 responses.",
                related_surfaces=["authentication", "endpoints"],
                blocked=True,
                blocked_reason="Auth testing requires test credentials to be confirmed and explicitly approved before use.",
                notes=["Credential use requires explicit approval. Use test tokens only."],
            ),
            QAStrategyArea(
                id="sa-03",
                name="Schema and Contract Testing",
                description="Validate request/response schemas match documented contract.",
                priority="high",
                risk_level="medium",
                recommended_approach="Compare API responses against OpenAPI/Swagger spec. Flag schema drift.",
                related_surfaces=["request/response schemas", "contract behavior"],
                blocked=False,
                notes=["OpenAPI spec needed for structured contract testing."],
            ),
            QAStrategyArea(
                id="sa-04",
                name="Error Handling Coverage",
                description="4xx/5xx responses, validation errors, malformed requests.",
                priority="medium",
                risk_level="medium",
                recommended_approach="Test invalid inputs, missing fields, wrong types. Verify meaningful error messages.",
                related_surfaces=["error handling", "endpoints"],
                blocked=False,
                notes=["Error handling quality is often overlooked — high value area."],
            ),
            QAStrategyArea(
                id="sa-05",
                name="Destructive Endpoint Guards",
                description="DELETE, irreversible writes, state-modifying endpoints.",
                priority="critical",
                risk_level="critical",
                recommended_approach="Map all destructive endpoints. Test only in staging/sandbox with rollback capability.",
                related_surfaces=["endpoints", "error handling"],
                blocked=True,
                blocked_reason="Destructive endpoints blocked until staging environment confirmed and rollback capability verified.",
                notes=["Risk: external_write. Never test destructive endpoints in production."],
            ),
        ]
        return areas

    if project_type == "ai_generated_app":
        areas = [
            QAStrategyArea(
                id="sa-01",
                name="Auth and Navigation Smoke",
                description="Login, navigation, and core page load. AI-generated apps often have fragile auth flows.",
                priority="high",
                risk_level="high",
                recommended_approach="Login -> navigate to key sections -> verify no broken redirects. Expect fragility.",
                related_surfaces=["auth", "navigation"],
                blocked=False,
                notes=["Generated apps may have incomplete auth — prioritize this first."],
            ),
            QAStrategyArea(
                id="sa-02",
                name="Form Submission and Data Persistence",
                description="Form validation, submission, and data save/retrieve accuracy.",
                priority="high",
                risk_level="medium",
                recommended_approach="Submit valid/invalid forms. Verify data persists and loads correctly on return.",
                related_surfaces=["forms", "data persistence"],
                blocked=False,
                notes=["Data persistence is a common failure point in generated apps."],
            ),
            QAStrategyArea(
                id="sa-03",
                name="Broken Route Detection",
                description="Identify 404s, dead links, and incomplete navigation paths.",
                priority="medium",
                risk_level="medium",
                recommended_approach="Manual crawl of all navigation links. Automated 404 detection later.",
                related_surfaces=["navigation", "broken routes"],
                blocked=False,
                notes=["Exploratory first — automation later once routes are stable."],
            ),
            QAStrategyArea(
                id="sa-04",
                name="Edge Case and Exploratory",
                description="Generated code fragility: unhandled errors, loading states, edge inputs.",
                priority="medium",
                risk_level="medium",
                recommended_approach="Structured exploratory sessions targeting error states, empty states, concurrent operations.",
                related_surfaces=["edge cases"],
                blocked=False,
                notes=["AI-generated apps often lack robust error handling — high-value manual area."],
            ),
        ]
        if has_api:
            areas.append(QAStrategyArea(
                id="sa-05",
                name="API/Backend Verification",
                description="Verify backend API calls if backend is accessible.",
                priority="medium",
                risk_level="medium",
                recommended_approach="Inspect network calls from UI. Verify API responses match UI state.",
                related_surfaces=["api endpoints"],
                blocked=True,
                blocked_reason="API testing requires target URL approval before any calls.",
                notes=["Lower priority than UI smoke for AI-generated apps."],
            ))
        return areas

    if project_type == "admin_panel":
        areas = [
            QAStrategyArea(
                id="sa-01",
                name="Role-Based Access Smoke",
                description="Login per role, verify appropriate access. Permission leaks are critical risks.",
                priority="critical",
                risk_level="critical",
                recommended_approach="Login as each role. Verify allowed/denied pages. Test unauthorized access attempts.",
                related_surfaces=["login", "admin dashboard", "role permissions"],
                blocked=True,
                blocked_reason="Requires confirmed test roles — not real admin accounts. Test role setup needed first.",
                notes=["Risk: permission leaks. Never use real admin credentials."],
            ),
            QAStrategyArea(
                id="sa-02",
                name="CRUD Operations",
                description="Create/Read/Update/Delete for core admin entities.",
                priority="high",
                risk_level="high",
                recommended_approach="CRUD happy path for each entity type. Verify validation, error messages, and audit trail.",
                related_surfaces=["CRUD screens", "filters/search"],
                blocked=True,
                blocked_reason="CRUD operations require staging environment and test data — blocked until confirmed.",
                notes=["Never run CRUD tests in production without explicit approval and rollback plan."],
            ),
            QAStrategyArea(
                id="sa-03",
                name="Destructive Action Guards",
                description="Delete/bulk-delete/irreversible actions: verify guards, confirmations, and audit.",
                priority="critical",
                risk_level="critical",
                recommended_approach="Test delete confirmation dialogs. Verify action requires explicit confirmation. Check audit log entry.",
                related_surfaces=["CRUD screens", "admin dashboard"],
                blocked=True,
                blocked_reason="Destructive actions blocked until staging environment confirmed with rollback capability.",
                notes=["Risk: external_write. Critical guard — must have confirmation dialog and audit trail."],
            ),
            QAStrategyArea(
                id="sa-04",
                name="Search and Filter Coverage",
                description="Search and filter functionality for admin data views.",
                priority="medium",
                risk_level="low",
                recommended_approach="Test with valid/invalid/empty search terms. Verify filter combinations.",
                related_surfaces=["filters/search", "admin dashboard"],
                blocked=False,
                notes=["Lower risk but high-usage area in admin panels."],
            ),
            QAStrategyArea(
                id="sa-05",
                name="Manual Exploratory — Permission Edge Cases",
                description="Exploratory testing of permission boundaries and admin-only functionality.",
                priority="high",
                risk_level="high",
                recommended_approach="Structured exploratory sessions targeting permission edge cases, session boundaries, data visibility.",
                related_surfaces=["role permissions", "admin dashboard"],
                blocked=False,
                notes=["Manual exploration is essential for permission testing — hard to automate comprehensively."],
            ),
        ]
        return areas

    if project_type == "auth_heavy":
        areas = [
            QAStrategyArea(
                id="sa-01",
                name="Login and Logout Smoke",
                description="Basic login/logout with valid test credentials. Protected page access.",
                priority="high",
                risk_level="high",
                recommended_approach="Login with test account -> verify session -> logout -> verify session cleared.",
                related_surfaces=["login", "logout", "session"],
                blocked=True,
                blocked_reason="Requires test account confirmation — no real user credentials permitted.",
                notes=["Test account must be synthetic — not a real user. Explicit approval required."],
            ),
            QAStrategyArea(
                id="sa-02",
                name="Session Management",
                description="Session persistence, timeout, concurrent sessions, session invalidation.",
                priority="high",
                risk_level="high",
                recommended_approach="Test session timeout, concurrent session behavior, remember-me functionality.",
                related_surfaces=["session", "protected pages"],
                blocked=True,
                blocked_reason="Session testing requires test account approval.",
                notes=["Session duration and timeout rules must be confirmed with client."],
            ),
            QAStrategyArea(
                id="sa-03",
                name="Protected Route Access",
                description="Unauthenticated access attempts, redirect behavior, role-scoped routes.",
                priority="high",
                risk_level="high",
                recommended_approach="Attempt access to protected pages without auth. Verify redirect to login. Test role boundaries.",
                related_surfaces=["protected pages", "login"],
                blocked=False,
                notes=["Read-only redirect testing may not require credentials."],
            ),
            QAStrategyArea(
                id="sa-04",
                name="Password Reset Flow",
                description="Password reset request, email link, reset completion.",
                priority="medium",
                risk_level="high",
                recommended_approach="Request password reset -> verify email sent (test mailbox) -> complete reset -> verify login.",
                related_surfaces=["password reset"],
                blocked=True,
                blocked_reason="Password reset requires test email mailbox setup. No real email accounts permitted.",
                notes=["Requires test email provider (Mailinator, Mailhog, or similar). Not real user email."],
            ),
            QAStrategyArea(
                id="sa-05",
                name="2FA / OTP Flow",
                description="Two-factor authentication, TOTP, SMS OTP, email OTP flows.",
                priority="high",
                risk_level="critical",
                recommended_approach="Use TOTP test seed for TOTP flows. SMS/email OTP require test provider setup.",
                related_surfaces=["2FA/OTP"],
                blocked=True,
                blocked_reason="2FA testing BLOCKED. Reason: requires test TOTP seed or test SMS/email provider — no real phone/email OTP permitted.",
                notes=["Risk: auth + credential. Requires explicit approval and test provider setup."],
            ),
            QAStrategyArea(
                id="sa-06",
                name="OAuth / SSO Redirect",
                description="OAuth2 / SSO redirect flows, callback handling, token exchange.",
                priority="medium",
                risk_level="high",
                recommended_approach="Map OAuth redirect flows. Verify callback URL handling. Use OAuth test apps where possible.",
                related_surfaces=["login"],
                blocked=True,
                blocked_reason="OAuth testing requires test OAuth app credentials — not production OAuth client.",
                notes=["Requires test OAuth application setup. Phase 2D prerequisite."],
            ),
        ]
        return areas

    if project_type == "mixed_ui_api":
        areas = [
            QAStrategyArea(
                id="sa-01",
                name="UI Smoke",
                description="Critical UI flows: auth, navigation, primary user actions.",
                priority="high",
                risk_level="high",
                recommended_approach="Login -> navigate critical flows -> verify key UI states.",
                related_surfaces=["UI critical flows", "auth/session"],
                blocked=False,
                notes=["UI smoke is the first layer — must pass before API testing."],
            ),
            QAStrategyArea(
                id="sa-02",
                name="API Contract Coverage",
                description="Endpoint contract testing: status codes, schema, auth headers.",
                priority="high",
                risk_level="high",
                recommended_approach="Test API endpoints independently. Compare contract to OpenAPI spec if available.",
                related_surfaces=["API endpoints"],
                blocked=True,
                blocked_reason="API calls require target URL approval and API access confirmation.",
                notes=["Requires approved API access. Auth tokens = test tokens only."],
            ),
            QAStrategyArea(
                id="sa-03",
                name="Auth and Session Management",
                description="Shared auth/session between UI and API layers.",
                priority="high",
                risk_level="high",
                recommended_approach="Verify UI session token reuse in API calls. Test session invalidation on both layers.",
                related_surfaces=["auth/session"],
                blocked=True,
                blocked_reason="Requires test account confirmation before auth testing.",
                notes=["Auth/session consistency between UI and API is a critical integration point."],
            ),
            QAStrategyArea(
                id="sa-04",
                name="UI/API Data Consistency",
                description="Verify data shown in UI matches API responses.",
                priority="medium",
                risk_level="medium",
                recommended_approach="Create data via API -> verify in UI. Create data via UI -> verify via API.",
                related_surfaces=["UI critical flows", "API endpoints", "data consistency"],
                blocked=True,
                blocked_reason="Data consistency tests require both UI and API access to be approved.",
                notes=["High value — catches UI/API divergence early."],
            ),
            QAStrategyArea(
                id="sa-05",
                name="CI Integration Planning",
                description="Plan CI pipeline split: fast API tests + slower UI tests.",
                priority="medium",
                risk_level="low",
                recommended_approach="Fast layer: API contract + smoke -> parallel. Slow layer: UI regression -> nightly.",
                related_surfaces=["ci/cd pipeline"],
                blocked=False,
                notes=["Phase 3B planning item — framework must exist first."],
            ),
        ]
        return areas

    # unknown (default)
    return [
        QAStrategyArea(
            id="sa-01",
            name="Scope Clarification Required",
            description="Project type and scope are unclear. No strategy can be built until scope is confirmed.",
            priority="critical",
            risk_level="critical",
            recommended_approach="Send clarification questions to client. Confirm project type, target, environment, and goals.",
            related_surfaces=["to be determined"],
            blocked=True,
            blocked_reason="All strategy areas blocked until project scope is confirmed.",
            notes=["Resolve missing information before building any strategy."],
        ),
        QAStrategyArea(
            id="sa-02",
            name="Manual Exploratory (Provisional)",
            description="If a target is available, a manual exploratory session may provide initial insights.",
            priority="low",
            risk_level="medium",
            recommended_approach="If target URL is approved, conduct a structured exploratory session to map the application.",
            related_surfaces=["to be determined"],
            blocked=True,
            blocked_reason="Blocked until target URL is approved and project scope is confirmed.",
            notes=["Not a substitute for proper scope confirmation."],
        ),
    ]


# ---------------------------------------------------------------------------
# Risk matrix builder
# ---------------------------------------------------------------------------

def _build_risk_matrix(
    project_type: str,
    blueprint: ProjectBlueprint,
    text: str,
) -> List[RiskMatrixItem]:
    has_target = bool(blueprint.target_application and blueprint.target_application != "Not yet provided")
    has_payment = _hits(text, _PAYMENT_SIGNALS)
    has_mobile = _hits(text, _MOBILE_SIGNALS)
    has_integration = _hits(text, _INTEGRATION_SIGNALS)
    has_security = _hits(text, _SECURITY_SIGNALS)
    is_prod = blueprint.environment == "production"
    has_auth = _hits(text, _AUTH_SIGNALS)

    items: List[RiskMatrixItem] = []
    idx = 1

    def add(risk_area, likelihood, impact, severity, mitigation, blocked=False, approval_required=False, notes=None):
        nonlocal idx
        items.append(RiskMatrixItem(
            id=f"risk-{idx:02d}",
            risk_area=risk_area,
            likelihood=likelihood,
            impact=impact,
            severity=severity,
            mitigation=mitigation,
            blocked=blocked,
            approval_required=approval_required,
            notes=notes or [],
        ))
        idx += 1

    # --- Universal risks ---
    if not has_target:
        add(
            "Missing target URL / no approved execution target",
            "high", "high", "high",
            "Obtain and confirm target application URL before any execution planning.",
            blocked=True,
            notes=["Blocks all execution-oriented strategy items."],
        )

    if blueprint.environment in ("unknown", ""):
        add(
            "Unknown / unconfirmed environment type",
            "medium", "medium", "medium",
            "Confirm whether target environment is staging, production, local, or none.",
            approval_required=True,
            notes=["Environment type affects which tests are safe to run."],
        )

    add(
        "Missing test credentials / test accounts",
        "high", "high", "high",
        "Confirm dedicated test accounts exist. Must be synthetic — not real user accounts.",
        blocked=True,
        approval_required=True,
        notes=["No credential use permitted until test accounts are confirmed and approved."],
    )

    add(
        "Missing acceptance criteria / definition of done",
        "medium", "medium", "medium",
        "Define QA coverage goals and acceptance criteria with client before execution.",
        notes=["Without acceptance criteria, strategy confidence is limited."],
    )

    # --- Production risk ---
    if is_prod:
        add(
            "Production environment interaction risk",
            "high", "critical", "critical",
            "Explicit read-only approval required before any production interaction. Default: no production access.",
            blocked=True,
            approval_required=True,
            notes=["Risk: production_read_only. Never write to production without explicit written approval."],
        )

    # --- Auth / credential risk ---
    if has_auth or project_type in ("auth_heavy", "web_saas", "admin_panel", "mixed_ui_api"):
        add(
            "Auth/session handling and credential safety",
            "high", "high", "high",
            "Use test accounts only. No real credentials. Explicit approval required for credential use.",
            blocked=True,
            approval_required=True,
            notes=["Risk: payment_or_auth. Credential safety is non-negotiable."],
        )

    # --- Project-type-specific risks ---
    if project_type == "web_saas":
        add("Role-based access control failures", "medium", "high", "high",
            "Map roles and test permission boundaries. Include unauthorized access attempts.")
        add("Form validation and data integrity failures", "medium", "medium", "medium",
            "Test all forms with valid, invalid, and edge-case inputs.")
        add("UI flakiness in Playwright automation", "medium", "medium", "medium",
            "Use stable selectors. Add retry logic for timing-sensitive interactions.")
        add("Critical workflow regression on deploy", "medium", "high", "high",
            "Run smoke suite on every deploy. Alert on critical path failures.")

    elif project_type == "ecommerce":
        add("Checkout flow breakage", "high", "critical", "critical",
            "Comprehensive checkout flow testing in sandbox mode. Never use real payment methods.",
            approval_required=True)
        if has_payment:
            add("Payment testing without sandbox confirmation", "high", "critical", "critical",
                "Payment testing BLOCKED until sandbox mode (e.g. Stripe test keys) confirmed in writing.",
                blocked=True, approval_required=True,
                notes=["Risk: payment_or_auth. Real money testing is absolutely forbidden."])
        add("Order data corruption / inventory drift", "medium", "high", "high",
            "Use isolated test data. Verify order state after each test. Clean up test orders.")
        add("Coupon/discount edge case failures", "medium", "medium", "medium",
            "Test coupon application, stacking rules, and expiry edge cases manually.")
        add("Production order creation risk", "high", "critical", "critical",
            "Never create real orders in production. Staging only with test payment methods.",
            blocked=is_prod, approval_required=True)

    elif project_type == "api_backend":
        add("Auth header validation failures", "high", "high", "high",
            "Test all auth header scenarios: valid/invalid/missing/expired tokens.",
            blocked=True, approval_required=True)
        add("API schema / contract mismatch", "medium", "high", "high",
            "Compare responses against OpenAPI spec. Alert on schema drift.")
        add("Destructive endpoint access", "high", "critical", "critical",
            "Map all DELETE/irreversible endpoints. Test only in staging with rollback capability.",
            blocked=True, approval_required=True)
        add("Rate limiting and availability surprises", "low", "medium", "medium",
            "Document rate limits. Test rate limit responses (429) without triggering abuse detection.")
        add("Missing or outdated API documentation", "medium", "medium", "medium",
            "Request OpenAPI/Swagger/Postman collection before structured test design.")

    elif project_type == "ai_generated_app":
        add("Broken or incomplete auth flows", "high", "high", "high",
            "Test auth flow end-to-end before any other testing. Generated auth is often fragile.")
        add("Generated code fragility and state inconsistency", "high", "high", "high",
            "Expect broken flows. Exploratory testing is essential before automation.")
        add("Unhandled error states and empty states", "medium", "high", "high",
            "Test error states explicitly. Check loading states and empty data scenarios.")
        add("Data persistence failures", "medium", "high", "high",
            "Verify created data survives page reload and session restart.")
        add("Rapid UI instability between versions", "high", "medium", "high",
            "AI-generated apps may change rapidly. Avoid brittle selectors.")

    elif project_type == "admin_panel":
        add("Permission leak / role bypass", "medium", "critical", "critical",
            "Test each role explicitly. Attempt access to unauthorized resources.",
            blocked=True, approval_required=True,
            notes=["Risk: security_sensitive. Permission leaks are a critical security risk."])
        add("Destructive CRUD without guard", "high", "critical", "critical",
            "Verify all destructive actions have confirmation dialogs and audit trail.",
            blocked=True, approval_required=True)
        add("Production data modification risk", "high", "critical", "critical",
            "Never modify production data. Staging only with test data and rollback.",
            blocked=is_prod, approval_required=True)
        add("Missing or inadequate audit trail", "medium", "high", "high",
            "Verify audit log entries for all admin actions.")

    elif project_type == "auth_heavy":
        add("Credential use without approved test account", "critical", "critical", "critical",
            "No real credentials permitted. Test accounts must be explicitly confirmed.",
            blocked=True, approval_required=True)
        add("Account state pollution across tests", "high", "high", "high",
            "Use isolated test accounts per test case. Clean up account state after each run.")
        add("2FA/OTP test execution without test provider", "high", "critical", "critical",
            "TOTP test seed or test SMS/email provider required. No real OTP codes.",
            blocked=True, approval_required=True)
        add("Production auth flow interaction", "high", "critical", "critical",
            "Production auth blocked until explicit read-only approval.",
            blocked=is_prod, approval_required=True)
        add("Password reset with real email accounts", "high", "critical", "critical",
            "Password reset testing requires test email mailbox (Mailhog, Mailinator, etc.).",
            blocked=True, approval_required=True)

    elif project_type == "mixed_ui_api":
        add("UI/API data mismatch", "medium", "high", "high",
            "Test data created via API against UI representation and vice versa.")
        add("Auth token reuse failure between UI and API", "medium", "high", "high",
            "Verify session token from UI is valid for API calls and vice versa.")
        add("Test data contamination across test runs", "medium", "medium", "medium",
            "Use isolated test data per test. Clean up after each run.")
        add("CI environment instability", "medium", "medium", "medium",
            "Ensure CI environment is stable and isolated. Use dedicated test database.")

    else:  # unknown
        add("Unclear project scope blocks all risk assessment", "critical", "critical", "critical",
            "Resolve scope clarification before any risk assessment can be meaningful.",
            blocked=True)
        add("Unknown environment and target application", "critical", "critical", "critical",
            "Confirm target application, environment type, and testing goals.",
            blocked=True, approval_required=True)

    # --- Signal-based additional risks ---
    if has_mobile:
        add("Mobile / native execution requirements", "medium", "high", "high",
            "Mobile/native execution is Phase 3+. Confirm mobile scope: mobile web vs native iOS/Android.",
            blocked=True, approval_required=True,
            notes=["Risk: external_write. Mobile native execution requires device/emulator setup."])

    if has_integration:
        add("External integration / webhook call risk", "medium", "high", "high",
            "External integration calls are disabled by default. IntegrationPolicy.allow_outbound_events=False.",
            blocked=True, approval_required=True,
            notes=["Risk: external_write. Never call external integrations without explicit approval."])

    if has_security:
        add("Security testing scope and blast radius", "medium", "critical", "critical",
            "Security testing requires explicit written scope from client. No injection/bypass without authorization.",
            blocked=True, approval_required=True,
            notes=["Risk: security_sensitive. Written client authorization required before any security testing."])

    return items


# ---------------------------------------------------------------------------
# Test layer recommendation builder
# ---------------------------------------------------------------------------

def _recommend_test_layers(
    project_type: str,
    blueprint: ProjectBlueprint,
    text: str,
) -> List[TestLayerRecommendation]:
    has_auth = _hits(text, _AUTH_SIGNALS)
    has_api = _hits(text, _API_SIGNALS)
    has_mobile = _hits(text, _MOBILE_SIGNALS)

    # Define recommended layers per project type
    _LAYERS: dict[str, dict] = {
        "web_saas": {
            "smoke": ("high", True, False, None, "Login + nav + dashboard load"),
            "ui": ("high", True, False, None, "Critical UI flows with Playwright"),
            "regression": ("medium", True, False, None, "Broader UI regression after smoke is stable"),
            "auth": ("high", has_auth, False, None if has_auth else "No explicit auth signals detected", "Session, protected routes, login/logout"),
            "api": ("medium", has_api, False, None if has_api else "No API signals — add if API is accessible", "Playwright API testing or pytest+requests"),
            "ci": ("medium", True, False, None, "Run smoke + regression in CI pipeline"),
            "manual_exploratory": ("medium", True, False, None, "Edge cases, UX issues, permission spot checks"),
            "visual": ("low", False, False, None, "Optional — future with Applitools or Playwright screenshot"),
            "mobile_web": ("low", has_mobile, has_mobile, None, "Responsive/mobile web emulation in Playwright"),
            "mobile_native": ("low", False, True, "Mobile native execution is Phase 3+. Requires device setup and explicit approval.", "Native iOS/Android — future phase"),
            "performance": ("low", False, False, None, "Optional future — Lighthouse or k6"),
            "security_light": ("low", False, False, None, "Optional — basic security smoke without pentest scope"),
        },
        "ecommerce": {
            "smoke": ("high", True, False, None, "Catalog browse + cart add + product page load"),
            "ui": ("high", True, False, None, "Checkout flow, cart operations, account login"),
            "regression": ("medium", True, False, None, "Cart + checkout regression after smoke is stable"),
            "manual_exploratory": ("high", True, False, None, "Coupons, shipping, promotions, edge-case orders"),
            "api": ("medium", has_api, False, None if has_api else "Add if backend API is accessible", "Order API, product API if available"),
            "monitoring": ("medium", False, False, None, "Synthetic monitoring for checkout — future phase"),
            "mobile_web": ("medium", has_mobile, False, None, "Mobile responsive checkout — important for ecommerce"),
            "mobile_native": ("low", False, True, "Mobile native is Phase 3+. Requires explicit approval and device setup.", "Native mobile — future phase"),
            "performance": ("low", False, False, None, "Page load performance — optional future"),
            "security_light": ("low", False, False, None, "Input validation, XSS basics — optional future"),
            "visual": ("low", False, False, None, "Product images, layout regression — optional future"),
        },
        "api_backend": {
            "api": ("high", True, False, None, "Endpoint happy paths, status codes, response shapes"),
            "contract": ("high", True, False, None, "Schema contract validation against OpenAPI spec"),
            "smoke": ("high", True, False, None, "Core endpoint smoke before full regression"),
            "regression": ("medium", True, False, None, "Regression suite for all endpoints after smoke"),
            "security_light": ("medium", True, False, None, "Auth bypass, input validation, rate limiting basics"),
            "ci": ("high", True, False, None, "API tests in CI — fast feedback on contract regressions"),
            "performance": ("low", False, False, None, "Load testing — optional future (k6 or Locust)"),
            "ui": ("low", False, False, None, "No UI layer for pure API backend"),
            "manual_exploratory": ("medium", True, False, None, "Exploratory API testing with Postman/Insomnia"),
            "mobile_native": ("low", False, True, "Mobile native is Phase 3+.", "Not applicable for API backend"),
        },
        "ai_generated_app": {
            "smoke": ("high", True, False, None, "Auth + nav + page load smoke — generated apps often fragile"),
            "ui": ("high", True, False, None, "Form submission, data persistence, critical flows"),
            "manual_exploratory": ("high", True, False, None, "Essential for generated apps — lots of unhandled edge cases"),
            "regression": ("medium", True, False, None, "After smoke is stable — expect frequent churn"),
            "auth": ("high", has_auth, False, None if has_auth else "No explicit auth signals", "Login/session/protected routes"),
            "api": ("medium", has_api, False, None if has_api else "No API signals detected", "Backend verification if API accessible"),
            "mobile_native": ("low", False, True, "Mobile native is Phase 3+.", "Not applicable unless mobile scope confirmed"),
            "visual": ("low", False, False, None, "Optional — useful to catch layout regressions in generated UI"),
        },
        "admin_panel": {
            "smoke": ("high", True, False, None, "Admin login, dashboard load, basic navigation"),
            "ui": ("high", True, False, None, "CRUD operations, form validation, admin flows"),
            "auth": ("high", True, False, None, "Role-based access, login per role, permission verification"),
            "regression": ("medium", True, False, None, "Admin flow regression after smoke is stable"),
            "manual_exploratory": ("high", True, False, None, "Permission edge cases — hard to automate comprehensively"),
            "security_light": ("medium", True, False, None, "Permission boundary checks, input validation"),
            "api": ("medium", has_api, False, None if has_api else "No API signals detected", "Admin API if accessible"),
            "mobile_native": ("low", False, True, "Mobile native is Phase 3+.", "Admin panels rarely need native mobile"),
            "performance": ("low", False, False, None, "Optional — only if performance is a concern"),
        },
        "auth_heavy": {
            "auth": ("high", True, False, None, "Login/logout/session/protected routes — primary focus"),
            "smoke": ("high", True, False, None, "Critical path smoke before full auth suite"),
            "ui": ("medium", True, False, None, "Auth UI flows, error states, form validation"),
            "security_light": ("high", True, False, None, "Auth bypass attempts, session fixation, token handling"),
            "manual_exploratory": ("high", True, False, None, "2FA flows, edge case auth scenarios"),
            "api": ("medium", has_api, False, None if has_api else "No API signals detected", "Auth API if accessible"),
            "mobile_native": ("low", False, True, "Mobile native is Phase 3+.", "Mobile auth — future phase"),
            "performance": ("low", False, False, None, "Auth performance — optional future"),
        },
        "mixed_ui_api": {
            "smoke": ("high", True, False, None, "UI + API smoke — verify both layers"),
            "ui": ("high", True, False, None, "UI critical flows with Playwright"),
            "api": ("high", True, False, None, "API contract coverage with Playwright or pytest"),
            "contract": ("high", True, False, None, "API schema validation against spec"),
            "auth": ("high", has_auth, False, None if has_auth else "No explicit auth signals", "Auth/session across UI and API layers"),
            "regression": ("medium", True, False, None, "Combined regression after smoke is stable"),
            "ci": ("high", True, False, None, "CI split: fast API + slower UI regression"),
            "mobile_native": ("low", False, True, "Mobile native is Phase 3+.", "Future phase if mobile scope confirmed"),
        },
        "unknown": {
            "manual_exploratory": ("high", True, False, None, "Only safe layer until scope is confirmed"),
            "smoke": ("medium", False, True, "Smoke blocked until target URL and project type are confirmed.", "To be planned after scope confirmation"),
            "ui": ("low", False, True, "UI testing blocked until scope is confirmed.", "Future — after scope clarification"),
            "api": ("low", False, True, "API testing blocked until scope is confirmed.", "Future — after scope clarification"),
            "mobile_native": ("low", False, True, "Mobile native is Phase 3+.", "Not applicable until scope known"),
        },
    }

    layer_defs = _LAYERS.get(project_type, _LAYERS["unknown"])

    result = []
    for layer_name, (priority, recommended, blocked, blocked_reason, purpose) in layer_defs.items():
        examples = _layer_examples(layer_name, project_type)
        result.append(TestLayerRecommendation(
            id=f"layer-{layer_name}",
            layer=layer_name,
            purpose=purpose,
            recommended=recommended,
            priority=priority,
            examples=examples,
            blocked=blocked,
            blocked_reason=blocked_reason,
        ))

    return result


def _layer_examples(layer: str, project_type: str) -> List[str]:
    _EXAMPLES = {
        "smoke": ["Login and dashboard load", "Critical navigation paths", "Key page renders without error"],
        "ui": ["Playwright TypeScript end-to-end test", "Form submit and verify result", "Button interaction and state change"],
        "api": ["GET /endpoint status 200", "POST with valid body -> 201 Created", "Invalid auth -> 401 Unauthorized"],
        "contract": ["OpenAPI schema validation", "Response field type checks", "Required field presence checks"],
        "auth": ["Login with valid credentials", "Access protected route without auth -> redirect", "Session timeout and re-login"],
        "regression": ["Full suite run on every deploy", "Critical flow regression after refactor", "CI nightly regression"],
        "manual_exploratory": ["Structured exploratory session charter", "Edge case discovery", "Usability and UX spot check"],
        "visual": ["Screenshot baseline comparison", "Layout regression after UI change", "Cross-browser visual check"],
        "accessibility": ["Screen reader compatibility check", "Keyboard navigation test", "Color contrast audit"],
        "performance": ["Page load time measurement", "Lighthouse score tracking", "k6 load test on critical endpoint"],
        "security_light": ["Auth bypass attempt (no injection)", "Input validation boundary check", "XSS basic test on form fields"],
        "mobile_web": ["Playwright mobile emulation (iPhone/Android viewport)", "Responsive layout check", "Touch interaction test"],
        "mobile_native": ["Appium native iOS/Android test", "Device farm execution", "Native gesture testing"],
        "ci": ["GitHub Actions smoke gate", "PR check with fast API suite", "Nightly regression run"],
        "monitoring": ["Synthetic checkout flow monitor", "Uptime check", "Alert on critical path failure"],
        "unknown": ["To be determined after scope confirmation"],
    }
    return _EXAMPLES.get(layer, ["To be determined"])


# ---------------------------------------------------------------------------
# Tactical planning outline builder
# ---------------------------------------------------------------------------

def _build_tactical_plan_outline(
    project_type: str,
    blueprint: ProjectBlueprint,
) -> List[TacticalPlanningItem]:
    items: List[TacticalPlanningItem] = [
        TacticalPlanningItem(
            id="tp-01",
            title="Resolve missing information with client",
            description="Send clarification questions to client before proceeding to Phase 2D. Cover: target URL, environment, test credentials, acceptance criteria.",
            phase="Phase 2C-R / Phase 2D prerequisite",
            priority="high",
            requires_approval=False,
            blocked=False,
            notes=["Do not proceed to test design until missing info is resolved."],
        ),
        TacticalPlanningItem(
            id="tp-02",
            title="Confirm project type and environment assumptions",
            description="Review blueprint inferences with client. Confirm project type, environment, and scope boundaries.",
            phase="Phase 2C-R",
            priority="high",
            requires_approval=False,
            blocked=False,
            notes=["Blueprint confidence may be low — client confirmation increases it."],
        ),
        TacticalPlanningItem(
            id="tp-03",
            title="Obtain dedicated test credentials / synthetic test accounts",
            description="Confirm test account availability. Must be synthetic — not real user accounts. Document account details (without raw passwords).",
            phase="Phase 2D prerequisite",
            priority="high",
            requires_approval=True,
            blocked=True,
            blocked_reason="No credential use permitted until test accounts are explicitly confirmed and approved.",
            future_artifact="outputs/<project_id>/01_approval/CREDENTIAL_APPROVAL.md",
            notes=["No real credentials. Explicit approval required before any auth testing."],
        ),
        TacticalPlanningItem(
            id="tp-04",
            title="Define acceptance criteria with client",
            description="Establish clear QA coverage goals: what passes, what fails, what is out of scope.",
            phase="Phase 2D prerequisite",
            priority="high",
            requires_approval=False,
            blocked=False,
            notes=["Without acceptance criteria, test completion is undefined."],
        ),
    ]

    # --- Type-specific tactical items ---
    if project_type == "web_saas":
        items += [
            TacticalPlanningItem(
                id="tp-05",
                title="Design Playwright test architecture",
                description="Plan folder structure, page object pattern, fixtures, and base test configuration for web_saas project.",
                phase="Phase 3A",
                priority="high",
                requires_approval=False,
                blocked=False,
                future_artifact="outputs/<project_id>/03_framework/playwright.config.ts",
                notes=["Framework generation — Phase 3A after strategy is reviewed."],
            ),
            TacticalPlanningItem(
                id="tp-06",
                title="Create test data strategy",
                description="Define synthetic test data requirements: user accounts, test content, test state.",
                phase="Phase 2D",
                priority="medium",
                requires_approval=False,
                blocked=False,
                notes=["Identify what data must exist before tests can run."],
            ),
            TacticalPlanningItem(
                id="tp-07",
                title="Plan CI pipeline integration",
                description="Identify CI target. Design: smoke gate on PR + nightly regression.",
                phase="Phase 3B",
                priority="medium",
                requires_approval=False,
                blocked=False,
                notes=["CI integration — after framework is in place."],
            ),
        ]

    elif project_type == "ecommerce":
        items += [
            TacticalPlanningItem(
                id="tp-05",
                title="Confirm sandbox payment mode with client",
                description="Obtain written confirmation that payment flows will use sandbox mode (e.g. Stripe test keys). Required before any checkout testing.",
                phase="Phase 2D prerequisite",
                priority="critical",
                requires_approval=True,
                blocked=True,
                blocked_reason="Payment testing BLOCKED until sandbox mode confirmed in writing.",
                future_artifact="outputs/<project_id>/01_approval/PAYMENT_SANDBOX_APPROVAL.md",
                notes=["Risk: payment_or_auth. Written confirmation required."],
            ),
            TacticalPlanningItem(
                id="tp-06",
                title="Design checkout flow test scenarios",
                description="Map full checkout journey: add to cart -> shipping -> payment -> confirmation. Design test cases for each step.",
                phase="Phase 3A",
                priority="high",
                requires_approval=True,
                blocked=False,
                notes=["Requires sandbox approval before execution. Design can proceed."],
            ),
            TacticalPlanningItem(
                id="tp-07",
                title="Plan test data for cart and order scenarios",
                description="Define test products, quantities, coupon codes, addresses for cart/checkout tests.",
                phase="Phase 2D",
                priority="medium",
                requires_approval=False,
                blocked=False,
                notes=["Test data planning does not require approval."],
            ),
        ]

    elif project_type == "api_backend":
        items += [
            TacticalPlanningItem(
                id="tp-05",
                title="Obtain API documentation",
                description="Request OpenAPI/Swagger spec or Postman collection. Required for structured contract testing.",
                phase="Phase 2D prerequisite",
                priority="high",
                requires_approval=False,
                blocked=False,
                notes=["Without API docs, contract testing relies on manual discovery."],
            ),
            TacticalPlanningItem(
                id="tp-06",
                title="Design endpoint coverage matrix",
                description="Map all known endpoints: method, path, auth requirement, risk level. Prioritize coverage.",
                phase="Phase 3A",
                priority="high",
                requires_approval=False,
                blocked=False,
                future_artifact="outputs/<project_id>/03_framework/API_COVERAGE_MATRIX.md",
                notes=["Coverage matrix drives test design priorities."],
            ),
            TacticalPlanningItem(
                id="tp-07",
                title="Plan contract testing approach",
                description="Decide: OpenAPI schema validation, Pact contract testing, or custom assertion approach.",
                phase="Phase 3A",
                priority="high",
                requires_approval=False,
                blocked=False,
                notes=["Contract testing is the highest ROI layer for API backends."],
            ),
        ]

    elif project_type == "ai_generated_app":
        items += [
            TacticalPlanningItem(
                id="tp-05",
                title="Map navigation flows and identify broken routes",
                description="Manual crawl of all navigation links. Document broken routes, 404s, dead-end pages.",
                phase="Phase 3A",
                priority="high",
                requires_approval=False,
                blocked=False,
                notes=["Navigation mapping is the first step for AI-generated apps."],
            ),
            TacticalPlanningItem(
                id="tp-06",
                title="Plan structured exploratory test sessions",
                description="Define exploratory session charters: focus area, time box, what to look for.",
                phase="Phase 3A",
                priority="high",
                requires_approval=False,
                blocked=False,
                notes=["Exploratory sessions are essential before automation for generated apps."],
            ),
        ]

    elif project_type == "admin_panel":
        items += [
            TacticalPlanningItem(
                id="tp-05",
                title="Define test roles and permissions matrix",
                description="Map all roles and their allowed/denied actions. Required before role-based access testing.",
                phase="Phase 2D prerequisite",
                priority="high",
                requires_approval=True,
                blocked=True,
                blocked_reason="Role-based testing requires test roles to be provisioned — not real admin accounts.",
                future_artifact="outputs/<project_id>/01_approval/ROLE_APPROVAL.md",
                notes=["Explicit approval required for admin role test accounts."],
            ),
            TacticalPlanningItem(
                id="tp-06",
                title="Design CRUD test scenarios",
                description="Map all entity types and CRUD operations. Design test cases for each with validation and error scenarios.",
                phase="Phase 3A",
                priority="high",
                requires_approval=True,
                blocked=False,
                notes=["CRUD tests require staging environment. Production CRUD is blocked."],
            ),
            TacticalPlanningItem(
                id="tp-07",
                title="Plan destructive action guard verification",
                description="Map all irreversible admin actions. Verify confirmation dialogs, audit trail, and rollback.",
                phase="Phase 3A",
                priority="critical",
                requires_approval=True,
                blocked=True,
                blocked_reason="Destructive action testing blocked until staging environment and rollback confirmed.",
                notes=["Risk: external_write. Highest risk area in admin panels."],
            ),
        ]

    elif project_type == "auth_heavy":
        items += [
            TacticalPlanningItem(
                id="tp-05",
                title="Identify test email/SMS provider for 2FA testing",
                description="Setup test email mailbox (Mailhog/Mailinator) or test SMS provider for OTP testing.",
                phase="Phase 2D prerequisite",
                priority="high",
                requires_approval=True,
                blocked=True,
                blocked_reason="2FA testing blocked until test provider is confirmed. No real phone/email OTP permitted.",
                future_artifact="outputs/<project_id>/01_approval/TWOFACTOR_PROVIDER_APPROVAL.md",
                notes=["Risk: auth. Test provider must be confirmed before any 2FA testing."],
            ),
            TacticalPlanningItem(
                id="tp-06",
                title="Design credential rotation strategy for test accounts",
                description="Plan how test account passwords are managed, rotated, and isolated between runs.",
                phase="Phase 2D",
                priority="high",
                requires_approval=True,
                blocked=False,
                notes=["Test credential management is critical for auth-heavy projects."],
            ),
            TacticalPlanningItem(
                id="tp-07",
                title="Plan session timeout test scenarios",
                description="Design test cases for session timeout, concurrent sessions, remember-me, and forced logout.",
                phase="Phase 3A",
                priority="medium",
                requires_approval=False,
                blocked=False,
                notes=["Session tests can be complex — plan carefully to avoid flakiness."],
            ),
        ]

    elif project_type == "mixed_ui_api":
        items += [
            TacticalPlanningItem(
                id="tp-05",
                title="Design UI + API consistency check strategy",
                description="Plan tests that create data via API and verify in UI, and vice versa.",
                phase="Phase 3A",
                priority="high",
                requires_approval=True,
                blocked=False,
                notes=["UI/API consistency is the unique value of mixed_ui_api strategy."],
            ),
            TacticalPlanningItem(
                id="tp-06",
                title="Plan test data seeding approach",
                description="Design how test data is created, reused, and cleaned up across UI and API tests.",
                phase="Phase 2D",
                priority="medium",
                requires_approval=False,
                blocked=False,
                notes=["Shared test data is a common source of test interference."],
            ),
        ]

    else:  # unknown
        items += [
            TacticalPlanningItem(
                id="tp-05",
                title="Send scope clarification questions to client",
                description="Prepare and send list of clarifying questions: What is the application? What is the testing goal? What is the environment?",
                phase="Phase 2C-R",
                priority="critical",
                requires_approval=False,
                blocked=False,
                notes=["All other tactical planning blocked until scope is confirmed."],
            ),
        ]

    # --- Universal trailing items ---
    items += [
        TacticalPlanningItem(
            id="tp-99a",
            title="Identify evidence collection requirements",
            description="Define what evidence is needed: test reports, screenshots, trace files, pass/fail counts.",
            phase="Phase 3A / 4A",
            priority="medium",
            requires_approval=False,
            blocked=False,
            future_artifact="outputs/<project_id>/05_evidence/",
            notes=["Evidence strategy should be designed before execution starts."],
        ),
        TacticalPlanningItem(
            id="tp-99b",
            title="Confirm client delivery format",
            description="Clarify: internal QA report only, or client-facing deliverable? Delivery triggers approval checklist.",
            phase="Phase 5A",
            priority="medium",
            requires_approval=True,
            blocked=False,
            future_artifact="outputs/<project_id>/06_client_draft/",
            notes=["Client delivery requires human review completion. Never auto-deliver."],
        ),
    ]

    return items


# ---------------------------------------------------------------------------
# Strategy decisions builder
# ---------------------------------------------------------------------------

def _build_strategy_decisions(project_type: str, blueprint: ProjectBlueprint) -> List[StrategyDecision]:
    decisions = [
        StrategyDecision(
            id="sd-01",
            decision="Playwright-first for web and mobile-web automation",
            rationale=(
                "Playwright provides cross-browser coverage (Chromium, Firefox, WebKit), "
                "built-in API testing, network interception, and mobile viewport emulation. "
                "It is the most capable tool for web automation without requiring additional licenses."
            ),
            alternatives_considered=["Selenium/WebDriver", "Cypress", "TestCafe"],
            impact="All future web and mobile-web automation scaffolds use Playwright TypeScript.",
            notes=["Playwright scaffold generation is Phase 3A — not this phase."],
        ),
        StrategyDecision(
            id="sd-02",
            decision="No execution in Phase 2C — planning and strategy only",
            rationale=(
                "Phase 2C is the strategy planning phase. No browser automation, "
                "no API calls, no credential use, and no test execution occur in this phase. "
                "Execution requires explicit approval and a confirmed target environment."
            ),
            alternatives_considered=["Run smoke tests immediately", "Generate and run Playwright scaffold now"],
            impact="All generated artifacts in this phase are plans and recommendations — not test results.",
            notes=["Execution starts in Phase 3A after full approval checklist is completed."],
        ),
        StrategyDecision(
            id="sd-03",
            decision="Credentials, auth execution, and payment testing are approval-gated",
            rationale=(
                "Any use of credentials, auth flows, or payment methods can cause account state changes, "
                "trigger real transactions, or expose sensitive data. "
                "Explicit written approval and test account confirmation are required before any execution."
            ),
            alternatives_considered=["Use credentials immediately", "Assume sandbox mode"],
            impact="Auth, credential, and payment strategy areas are marked blocked until approval is obtained.",
            notes=["Risk: payment_or_auth. Non-negotiable safety rule."],
        ),
        StrategyDecision(
            id="sd-04",
            decision="Strategy must precede framework generation",
            rationale=(
                "Building a Playwright scaffold without a confirmed strategy leads to rework. "
                "Phase 2C strategy defines the test layers, scope, and blocked areas that inform "
                "what the framework needs to support."
            ),
            alternatives_considered=["Generate framework immediately from brief", "Skip strategy phase"],
            impact="Framework generation (Phase 3A) begins only after Phase 2C strategy is reviewed and approved.",
            notes=["Phase 2C -> Phase 2C-R -> Phase 3A is the required sequence."],
        ),
        StrategyDecision(
            id="sd-05",
            decision="Native mobile testing is an optional future adapter (Phase 3+)",
            rationale=(
                "Native iOS/Android testing requires device setup (physical or emulator/simulator), "
                "platform-specific tooling (Appium, XCUITest, Espresso, Maestro), "
                "and explicit scope confirmation. It is not included in the current phase."
            ),
            alternatives_considered=["Add Appium now", "Use BrowserStack immediately", "Use Maestro"],
            impact="Mobile-web (Playwright viewport emulation) may be included. Native mobile is Phase 3+ only.",
            notes=["Optional adapters: Appium, Maestro, BrowserStack, Sauce Labs — not added until explicitly needed."],
        ),
        StrategyDecision(
            id="sd-06",
            decision="Client delivery is not ready until human review is complete",
            rationale=(
                "All generated artifacts in Phases 2C and earlier are internal planning documents. "
                "No artifact is client-facing until the HUMAN_REVIEW_REQUIRED.md checklist is completed "
                "by a senior QA reviewer."
            ),
            alternatives_considered=["Deliver strategy doc directly to client", "Auto-generate client report"],
            impact="client_ready=False for all Phase 2C artifacts. Phase 5A handles client delivery after review.",
            notes=["This is a non-negotiable governance rule. Do not deliver without human review."],
        ),
    ]

    if project_type in ("api_backend", "mixed_ui_api"):
        decisions.append(StrategyDecision(
            id="sd-07",
            decision="API layer recommended when API signals are present",
            rationale=(
                "When the project brief mentions API, endpoints, REST, GraphQL, or backend services, "
                "an API testing layer provides faster feedback than UI-only testing and enables contract validation."
            ),
            alternatives_considered=["UI-only testing", "Skip API layer"],
            impact="API test layer is included in recommended layers. Playwright request or pytest+requests as implementation options.",
            notes=["API calls require target URL and auth approval before execution."],
        ))

    return decisions


# ---------------------------------------------------------------------------
# Summary and confidence helpers
# ---------------------------------------------------------------------------

def _build_strategy_summary(blueprint: ProjectBlueprint, task_type: str) -> str:
    pt = blueprint.project_type
    env = blueprint.environment
    conf = blueprint.confidence_level
    n_missing = len(blueprint.missing_information)

    qualifier = ""
    if n_missing > 3:
        qualifier = f" Note: {n_missing} missing information items reduce strategy confidence — resolve before execution."
    elif conf == "low":
        qualifier = " Note: Strategy confidence is low — confirm project type and scope with client before proceeding."

    summaries = {
        "web_saas": f"QA strategy for a SaaS web application ({env} environment). Focus: auth/session smoke, core user workflows, UI regression, and CI integration. Playwright-first automation.{qualifier}",
        "ecommerce": f"QA strategy for an ecommerce application ({env} environment). Focus: catalog smoke, cart operations, checkout flow, and payment sandbox. Payment testing is blocked until sandbox is confirmed.{qualifier}",
        "api_backend": f"QA strategy for an API backend ({env} environment). Focus: endpoint contract testing, auth header validation, schema validation, and error handling. No remote API calls until target is approved.{qualifier}",
        "ai_generated_app": f"QA strategy for an AI-generated application ({env} environment). Focus: auth/navigation smoke, form persistence, broken route detection, and exploratory testing. Expect fragility.{qualifier}",
        "admin_panel": f"QA strategy for an admin panel ({env} environment). Focus: role-based access, CRUD operations, destructive action guards. High security risk — all execution blocked until test roles and staging are confirmed.{qualifier}",
        "auth_heavy": f"QA strategy for an auth-heavy application ({env} environment). Focus: login/logout, session management, protected routes, password reset, and 2FA flows. All credential use is blocked until test accounts are confirmed.{qualifier}",
        "mixed_ui_api": f"QA strategy for a mixed UI+API application ({env} environment). Focus: UI smoke, API contract testing, auth/session, and data consistency. Layered approach with CI split between fast API and slower UI layers.{qualifier}",
        "unknown": f"Project scope is unclear. Strategy is provisional. Resolve scope clarification before building a meaningful strategy.{qualifier}",
    }
    base = summaries.get(pt, f"QA strategy for project type '{pt}' ({env} environment).{qualifier}")
    if task_type == "proposal":
        return f"Proposal mode: {base} Focus on scope clarification and risk/fit assessment."
    return base


def _infer_primary_goal(blueprint: ProjectBlueprint) -> str:
    goal = blueprint.client_goal
    if not goal or goal == "Not specified — requires clarification.":
        pt = blueprint.project_type
        defaults = {
            "web_saas": "Ensure core SaaS application flows work correctly and reliably.",
            "ecommerce": "Validate the purchase journey and prevent checkout/payment failures.",
            "api_backend": "Verify API contract correctness and prevent regressions.",
            "ai_generated_app": "Identify fragile areas in the generated application and establish baseline quality.",
            "admin_panel": "Ensure admin panel is secure, role-appropriate, and does not expose destructive actions.",
            "auth_heavy": "Verify all auth flows are secure, reliable, and handle edge cases correctly.",
            "mixed_ui_api": "Ensure UI and API layers are consistent and correct end-to-end.",
            "unknown": "Clarify testing goals before building strategy.",
        }
        return defaults.get(pt, "Define QA coverage goals.")
    return goal[:300]


def _infer_strategy_confidence(blueprint: ProjectBlueprint) -> str:
    score = 0
    if blueprint.project_type != "unknown":
        score += 1
    if blueprint.environment not in ("unknown", ""):
        score += 1
    if blueprint.target_application and blueprint.target_application != "Not yet provided":
        score += 1
    if blueprint.confidence_level == "high":
        score += 1
    if score <= 1:
        return "low"
    if score <= 2:
        return "medium"
    return "high"


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: dict) -> str:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _write_text(path: Path, content: str) -> str:
    path.write_text(content, encoding="utf-8")
    return str(path)


def _render_qa_strategy_md(strategy: QAStrategy) -> str:
    lines = [
        f"# QA Strategy — {strategy.project_id}",
        "",
        "> **Planning artifact only. No execution has occurred. Not client-ready.**",
        "",
        "---",
        "",
        "## Overview",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Project ID | `{strategy.project_id}` |",
        f"| Project type | `{strategy.project_type}` |",
        f"| Environment | `{strategy.environment_type}` |",
        f"| Confidence | `{strategy.confidence_level}` |",
        f"| Client ready | `{strategy.client_ready}` |",
        f"| Created | {strategy.created_at} |",
        "",
        "## Primary goal",
        "",
        strategy.primary_goal or "_Not specified._",
        "",
        "## Strategy summary",
        "",
        strategy.strategy_summary or "_No summary generated._",
        "",
        "## Strategy areas",
        "",
    ]
    for area in strategy.strategy_areas:
        status = " **[BLOCKED]**" if area.blocked else ""
        lines += [
            f"### {area.name}{status}",
            "",
            f"**Priority:** {area.priority} | **Risk level:** {area.risk_level}",
            "",
            area.description,
            "",
            f"**Approach:** {area.recommended_approach}",
        ]
        if area.blocked_reason:
            lines += ["", f"> **Blocked:** {area.blocked_reason}"]
        if area.related_surfaces:
            lines += ["", f"**Surfaces:** {', '.join(area.related_surfaces)}"]
        if area.notes:
            for note in area.notes:
                lines.append(f"- _{note}_")
        lines.append("")

    if strategy.blocked_actions:
        lines += ["## Blocked actions (carried forward from blueprint)", ""]
        for ba in strategy.blocked_actions[:6]:
            short = ba.split(" — ")[0] if " — " in ba else ba[:120]
            lines.append(f"- {short}")
        if len(strategy.blocked_actions) > 6:
            lines.append(f"- _(+{len(strategy.blocked_actions) - 6} more — see PROJECT_BLUEPRINT.json)_")
        lines.append("")

    if strategy.required_approvals:
        lines += ["## Required approvals", ""]
        for ap in strategy.required_approvals:
            lines.append(f"- {ap}")
        lines.append("")

    lines += [
        "---",
        "",
        "_Generated by QAStrategyPlanner (Phase 2C — planning only). "
        "No tests have been executed. All URLs, credentials, and external resources "
        "require explicit approval before any access._",
        "",
    ]
    return "\n".join(lines)


def _render_test_scope_md(strategy: QAStrategy) -> str:
    recommended = [t for t in strategy.test_layers if t.recommended]
    deferred = [t for t in strategy.test_layers if not t.recommended and not t.blocked]
    blocked_layers = [t for t in strategy.test_layers if t.blocked]

    lines = [
        f"# Test Scope — {strategy.project_id}",
        "",
        "> **Planning artifact only. No tests have been executed.**",
        "",
        "---",
        "",
        f"**Project type:** `{strategy.project_type}` | **Environment:** `{strategy.environment_type}`",
        "",
        "## Recommended test layers",
        "",
        "| Layer | Priority | Purpose |",
        "|---|---|---|",
    ]
    for t in recommended:
        lines.append(f"| `{t.layer}` | {t.priority} | {t.purpose} |")
    lines += [
        "",
        "## Deferred / optional layers",
        "",
        "| Layer | Notes |",
        "|---|---|",
    ]
    for t in deferred:
        notes = t.notes[0] if t.notes else "Optional for this project type"
        lines.append(f"| `{t.layer}` | {notes} |")
    lines += [
        "",
        "## Blocked layers",
        "",
        "| Layer | Reason |",
        "|---|---|",
    ]
    for t in blocked_layers:
        reason = t.blocked_reason or "Blocked — see strategy for details"
        lines.append(f"| `{t.layer}` | {reason} |")
    lines += [
        "",
        "---",
        "",
        "_No execution has occurred. Scope is based on project type signals and blueprint analysis._",
        "",
    ]
    return "\n".join(lines)


def _render_risk_matrix_md(strategy: QAStrategy) -> str:
    lines = [
        f"# Risk Matrix — {strategy.project_id}",
        "",
        "> **Planning artifact only. Risk assessment is based on project type signals — not live testing.**",
        "",
        "---",
        "",
        f"**Project type:** `{strategy.project_type}` | **Environment:** `{strategy.environment_type}`",
        "",
        "| ID | Risk area | Likelihood | Impact | Severity | Blocked | Approval req. |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in strategy.risk_matrix:
        blocked_str = "YES" if r.blocked else "no"
        approval_str = "YES" if r.approval_required else "no"
        lines.append(
            f"| `{r.id}` | {r.risk_area[:60]} | {r.likelihood} | {r.impact} | {r.severity} | {blocked_str} | {approval_str} |"
        )
    lines += ["", "## Mitigations", ""]
    for r in strategy.risk_matrix:
        blocker_tag = " **[BLOCKED]**" if r.blocked else ""
        lines += [
            f"### `{r.id}` — {r.risk_area}{blocker_tag}",
            "",
            f"**Severity:** {r.severity} | **Likelihood:** {r.likelihood} | **Impact:** {r.impact}",
            "",
            f"**Mitigation:** {r.mitigation}",
        ]
        if r.notes:
            for note in r.notes:
                lines.append(f"- _{note}_")
        lines.append("")
    lines += [
        "---",
        "",
        "_Risk assessment is preliminary. Risks are based on project type, environment signals, and input classification._",
        "",
    ]
    return "\n".join(lines)


def _render_test_layers_md(strategy: QAStrategy) -> str:
    lines = [
        f"# Test Layers — {strategy.project_id}",
        "",
        "> **Planning artifact only. No automation has been generated.**",
        "",
        "---",
        "",
        f"**Project type:** `{strategy.project_type}`",
        "",
        "Playwright remains the primary future automation direction for web and mobile-web layers.",
        "API tests may use Playwright request context or pytest+requests.",
        "Native mobile and optional adapters (Appium, Maestro, BrowserStack, Applitools, etc.) are future phases — not yet implemented.",
        "",
    ]
    for t in strategy.test_layers:
        status = " **[BLOCKED]**" if t.blocked else (" _(deferred)_" if not t.recommended else "")
        rec_label = "Recommended" if t.recommended else ("Blocked" if t.blocked else "Deferred")
        lines += [
            f"## {t.layer.upper()} {status}",
            "",
            f"**Status:** {rec_label} | **Priority:** {t.priority}",
            "",
            f"**Purpose:** {t.purpose}",
        ]
        if t.blocked_reason:
            lines += ["", f"> **Blocked:** {t.blocked_reason}"]
        if t.examples:
            lines += ["", "**Examples:**"]
            for ex in t.examples:
                lines.append(f"- {ex}")
        lines.append("")
    lines += [
        "---",
        "",
        "_Test layer recommendations are based on project type. "
        "Adjust after reviewing strategy with client._",
        "",
    ]
    return "\n".join(lines)


def _render_tactical_plan_outline_md(strategy: QAStrategy) -> str:
    lines = [
        f"# Tactical Plan Outline — {strategy.project_id}",
        "",
        "> **Planning artifact only. This is not a detailed test plan — it prepares Phase 2D/3A.**",
        "> **No tests have been created. No execution has occurred.**",
        "",
        "---",
        "",
        f"**Project type:** `{strategy.project_type}` | **Environment:** `{strategy.environment_type}`",
        "",
        "## Tactical planning items",
        "",
    ]
    for item in strategy.tactical_plan_outline:
        blocked_tag = " **[BLOCKED]**" if item.blocked else ""
        approval_tag = " _(requires approval)_" if item.requires_approval else ""
        lines += [
            f"### {item.title}{blocked_tag}{approval_tag}",
            "",
            f"**Phase:** {item.phase} | **Priority:** {item.priority}",
            "",
            item.description,
        ]
        if item.blocked_reason:
            lines += ["", f"> **Blocked:** {item.blocked_reason}"]
        if item.future_artifact:
            lines += ["", f"**Future artifact:** `{item.future_artifact}`"]
        if item.notes:
            for note in item.notes:
                lines.append(f"- _{note}_")
        lines.append("")

    lines += [
        "## What happens in Phase 2D / 3A",
        "",
        "- Phase 2D: Resolve missing information, confirm approvals, establish test credentials.",
        "- Phase 3A: Generate Playwright scaffold architecture based on confirmed strategy.",
        "- Phase 3B: CI integration — smoke gate on PR + nightly regression.",
        "- Phase 4A: Execute tests, collect evidence.",
        "- Phase 5A: Human review -> client delivery preparation.",
        "",
        "---",
        "",
        "_Tactical planning does not include step-by-step test cases or executable test files. "
        "Those are generated in Phase 3A after strategy review._",
        "",
    ]
    return "\n".join(lines)


def _render_quality_rubric_md(strategy: QAStrategy) -> str:
    lines = [
        f"# Quality Rubric — {strategy.project_id}",
        "",
        "> **This rubric defines how future strategy, tactical, framework, and report outputs should be judged.**",
        "> **Phase 2C outputs are not yet client-ready. client_ready=False.**",
        "",
        "---",
        "",
        "| Criterion | Description | Phase 2C status |",
        "|---|---|---|",
        "| technically_correct | Strategy is technically sound for the project type | Provisional — based on signals |",
        "| specific | Strategy is specific to this project, not generic | Partial — needs client confirmation |",
        "| actionable | Recommendations are actionable with clear next steps | Yes |",
        "| evidence_based | Recommendations based on available signals | Yes — blueprint-derived |",
        "| honest_scope | Limitations and unknowns are stated explicitly | Yes |",
        "| no_overclaiming | No false claims about execution or test results | Yes |",
        "| client_ready | Reviewed and approved for client delivery | **No — human review required** |",
        "| human_readable | Output is readable without technical jargon | Yes |",
        "| no_internal_notes | No internal planning notes in client-facing text | Review required |",
        "| approval_checked | Blocked items are clearly marked with approval requirements | Yes |",
        "| safe_to_deliver | No raw secrets, no execution claims, no misleading statements | Yes |",
        "",
        "## How to use this rubric",
        "",
        "1. Review each criterion before advancing to the next phase.",
        "2. A failing criterion blocks client delivery.",
        "3. `client_ready` can only be set to `True` by a human reviewer completing the HUMAN_REVIEW_REQUIRED checklist.",
        "4. Strategy artifacts must pass all criteria before being included in a client report.",
        "",
        "---",
        "",
        f"_Generated by QAStrategyPlanner (Phase 2C). client_ready={strategy.client_ready}_",
        "",
    ]
    return "\n".join(lines)


def _render_strategy_decisions_md(strategy: QAStrategy) -> str:
    lines = [
        f"# Strategy Decisions — {strategy.project_id}",
        "",
        "> **Records key strategy decisions and their rationale.**",
        "",
        "---",
        "",
    ]
    for d in strategy.strategy_decisions:
        lines += [
            f"## {d.id}: {d.decision}",
            "",
            f"**Rationale:** {d.rationale}",
            "",
        ]
        if d.alternatives_considered:
            lines += ["**Alternatives considered:**", ""]
            for alt in d.alternatives_considered:
                lines.append(f"- {alt}")
            lines.append("")
        lines += [
            f"**Impact:** {d.impact}",
        ]
        if d.notes:
            lines.append("")
            for note in d.notes:
                lines.append(f"- _{note}_")
        lines.append("")
    lines += [
        "---",
        "",
        "_Decisions are recorded for traceability. They can be revisited after client review._",
        "",
    ]
    return "\n".join(lines)


def _render_updated_status_md(status: ProjectStatus) -> str:
    lines = [
        f"# Updated Project Status — {status.project_id}",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Phase | `{status.phase}` |",
        f"| Status | `{status.overall_status}` |",
        f"| Updated | {status.updated_at} |",
        "",
        "## Next action",
        "",
        status.next_action or "_none_",
        "",
    ]
    if status.notes:
        lines += ["## Notes", "", status.notes, ""]
    if status.completed_phases:
        lines += ["## Completed phases", ""]
        for ph in status.completed_phases:
            lines.append(f"- {ph}")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main planner class
# ---------------------------------------------------------------------------

class QAStrategyPlanner:
    """Builds QA strategy and tactical planning foundation from ProjectBlueprint.

    Phase 2C — no URL fetching, no browser, no credential use, no external calls.
    """

    def build_strategy(
        self,
        blueprint: ProjectBlueprint,
        input_map=None,
        work_request=None,
        task_classification=None,
    ) -> QAStrategy:
        """Build a QAStrategy from a ProjectBlueprint and optional Phase 2A context."""
        # Build searchable text from blueprint fields + optional work_request
        text_parts = [
            blueprint.client_goal,
            blueprint.scope_notes,
            blueprint.recommended_strategy,
            " ".join(blueprint.risk_areas),
            " ".join(blueprint.application_surfaces),
            " ".join(blueprint.tech_stack),
        ]
        if work_request is not None:
            text_parts += [
                getattr(work_request, "request_summary", ""),
                getattr(work_request, "raw_brief", ""),
                getattr(work_request, "request_title", ""),
            ]
        text = " ".join(t for t in text_parts if t)

        task_type = "qa_automation"
        if task_classification is not None:
            task_type = getattr(task_classification, "task_type", "qa_automation")

        project_type = blueprint.project_type
        environment_type = blueprint.environment

        strategy_areas = _strategy_areas_for_type(project_type, text, blueprint)
        risk_matrix = _build_risk_matrix(project_type, blueprint, text)
        test_layers = _recommend_test_layers(project_type, blueprint, text)
        tactical_plan = _build_tactical_plan_outline(project_type, blueprint)
        strategy_decisions = _build_strategy_decisions(project_type, blueprint)

        summary = _build_strategy_summary(blueprint, task_type)
        primary_goal = _infer_primary_goal(blueprint)
        confidence = _infer_strategy_confidence(blueprint)

        return QAStrategy(
            project_id=blueprint.project_id,
            strategy_summary=summary,
            project_type=project_type,
            environment_type=environment_type,
            primary_goal=primary_goal,
            strategy_areas=strategy_areas,
            risk_matrix=risk_matrix,
            test_layers=test_layers,
            tactical_plan_outline=tactical_plan,
            strategy_decisions=strategy_decisions,
            blocked_actions=list(blueprint.blocked_actions),
            required_approvals=list(blueprint.required_approvals),
            missing_information=list(blueprint.missing_information),
            confidence_level=confidence,
            client_ready=False,
            notes=[
                "Phase 2C planning artifact only.",
                "No execution has occurred.",
                "All blocked actions and required approvals are carried forward from the project blueprint.",
                "client_ready=False — human review required before any delivery.",
            ],
        )

    def render_strategy_artifacts(
        self,
        strategy: QAStrategy,
        out_dir: Path,
        updated_status: Optional[ProjectStatus] = None,
    ) -> dict:
        """Write all Phase 2C strategy artifacts to out_dir. Returns {name: path} dict."""
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        paths = {}

        paths["qa_strategy_json"] = _write_json(
            out / "QA_STRATEGY.json", strategy.to_dict()
        )
        paths["qa_strategy_md"] = _write_text(
            out / "QA_STRATEGY.md", _render_qa_strategy_md(strategy)
        )
        paths["test_scope_md"] = _write_text(
            out / "TEST_SCOPE.md", _render_test_scope_md(strategy)
        )
        paths["risk_matrix_md"] = _write_text(
            out / "RISK_MATRIX.md", _render_risk_matrix_md(strategy)
        )
        paths["test_layers_md"] = _write_text(
            out / "TEST_LAYERS.md", _render_test_layers_md(strategy)
        )
        paths["tactical_plan_outline_md"] = _write_text(
            out / "TACTICAL_PLAN_OUTLINE.md", _render_tactical_plan_outline_md(strategy)
        )
        paths["quality_rubric_md"] = _write_text(
            out / "QUALITY_RUBRIC.md", _render_quality_rubric_md(strategy)
        )
        paths["strategy_decisions_md"] = _write_text(
            out / "STRATEGY_DECISIONS.md", _render_strategy_decisions_md(strategy)
        )

        if updated_status is not None:
            paths["updated_project_status_json"] = _write_json(
                out / "UPDATED_PROJECT_STATUS.json", updated_status.to_dict()
            )
            paths["updated_project_status_md"] = _write_text(
                out / "UPDATED_PROJECT_STATUS.md", _render_updated_status_md(updated_status)
            )

        return paths

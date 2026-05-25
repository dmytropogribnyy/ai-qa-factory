"""ProjectBlueprintBuilder — builds the project source-of-truth from Phase 2A context.

Phase 2B — planning/context only:
- No URL fetching.
- No browser execution.
- No credential use.
- No external calls.
- No test execution.
- No Playwright scaffold.
"""
from __future__ import annotations

from typing import List

from core.schemas.input_map import InputMap
from core.schemas.project_blueprint import ProjectBlueprint
from core.schemas.task_classification import TaskClassification
from core.schemas.work_request import WorkRequest


# ---------------------------------------------------------------------------
# Project-type signal tables
# ---------------------------------------------------------------------------

_SAAS_SIGNALS = [
    "saas", "dashboard", "user account", "subscription", "settings",
    "admin area", "crm", "portal", "web app", "multi-user", "multi tenant",
    "tenant", "workspace", "organization settings",
]
_ECOMMERCE_SIGNALS = [
    "shop", "cart", "checkout", "product catalog", "product listing", "payment",
    "order", "coupon", "shipping", "inventory", "e-commerce", "ecommerce",
    "add to cart", "purchase", "refund",
]
_API_SIGNALS = [
    "api", "endpoint", "rest", "restful", "openapi", "swagger", "postman",
    "backend", "service", "contract", "payload", "graphql", "request",
    "response schema", "status code", "rate limit",
]
_AI_APP_SIGNALS = [
    "lovable", "bolt.new", "bolt", "v0", "cursor", "ai-generated", "ai generated",
    "mvp generated", "vibe coded", "generated app", "ai app", "quick prototype",
    "ai prototype",
]
_ADMIN_SIGNALS = [
    "admin", "backoffice", "back office", "management panel", "roles",
    "permissions", "crud", "internal tool", "cms", "content management",
    "data management", "manage users",
]
_AUTH_SIGNALS = [
    "login", "authentication", "oauth2", "oauth", "sso", "magic link",
    "email otp", "sms otp", "totp", "2fa", "two-factor", "mfa",
    "session", "protected route", "password reset", "logout", "auth flow",
    "sign in", "sign up", "register",
]

_ENV_STAGING_SIGNALS = ["staging", "stage", "test env", "qa env", "demo", "sandbox", "preprod", "pre-prod"]
_ENV_PROD_SIGNALS = ["production", "live site", "real users", "real payment", "public app"]
_ENV_LOCAL_SIGNALS = ["localhost", "127.0.0.1", "local dev", "local environment", "local project"]
_ENV_NONE_SIGNALS = ["proposal", "cover letter", "bid", "write a", "write up"]

_PAYMENT_SIGNALS = ["payment", "checkout", "stripe", "paypal", "billing", "credit card", "real money"]
_MOBILE_SIGNALS = ["ios", "android", "react native", "flutter", "appium", "native app", "mobile app"]
_INTEGRATION_SIGNALS = ["n8n", "make", "zapier", "webhook", "integration", "slack notify", "jira ticket"]
_SECURITY_SIGNALS = ["security", "pentest", "owasp", "xss", "sql injection", "auth bypass", "vulnerability"]


def _hits(text: str, signals: list[str]) -> bool:
    lower = text.lower()
    return any(s in lower for s in signals)


def _count(text: str, signals: list[str]) -> int:
    lower = text.lower()
    return sum(1 for s in signals if s in lower)


# ---------------------------------------------------------------------------
# Inference helpers
# ---------------------------------------------------------------------------

def _infer_project_type(text: str, task_type: str, preset: str = "unknown") -> str:
    """Infer project type from text signals. Falls back to preset when nothing is inferred."""
    scores = {
        "web_saas":        _count(text, _SAAS_SIGNALS),
        "ecommerce":       _count(text, _ECOMMERCE_SIGNALS),
        "api_backend":     _count(text, _API_SIGNALS),
        "ai_generated_app": _count(text, _AI_APP_SIGNALS),
        "admin_panel":     _count(text, _ADMIN_SIGNALS),
        "auth_heavy":      _count(text, _AUTH_SIGNALS),
    }

    # Mixed UI+API: both UI and API signals clearly present
    if _count(text, _API_SIGNALS) >= 2 and _count(text, _SAAS_SIGNALS + _ADMIN_SIGNALS) >= 2:
        scores["mixed_ui_api"] = scores["api_backend"] + 1

    best = max(scores, key=lambda k: scores[k])
    inferred = best if scores[best] > 0 else "unknown"

    # Classifier result wins if it agrees or if inferred is unknown
    if preset not in ("unknown", "") and inferred == "unknown":
        return preset
    return inferred


def _infer_environment(text: str, sources: list) -> str:
    lower = text.lower()
    # None first — writing/proposal tasks have no environment
    if _hits(text, _ENV_NONE_SIGNALS) and not _hits(text, _SAAS_SIGNALS + _ECOMMERCE_SIGNALS):
        return "none"
    if any(s in lower for s in _ENV_LOCAL_SIGNALS):
        return "local"
    if any(s in lower for s in _ENV_STAGING_SIGNALS):
        return "staging"
    if any(s in lower for s in _ENV_PROD_SIGNALS):
        return "production"
    # Check URL sources — if we have a target_url but no env signal, it's unknown
    if any(s.input_type == "target_url" for s in sources):
        return "unknown"
    return "unknown"


def _surfaces_for_type(project_type: str, text: str) -> List[str]:
    base = {
        "web_saas": ["public pages", "authentication", "dashboard", "user settings", "forms", "navigation"],
        "ecommerce": ["product catalog", "product page", "cart", "checkout", "payment/sandbox", "account/orders"],
        "api_backend": ["endpoints", "authentication", "request/response schemas", "error handling", "contract behavior"],
        "ai_generated_app": ["auth", "navigation", "forms", "data persistence", "broken routes", "edge cases"],
        "admin_panel": ["login", "admin dashboard", "CRUD screens", "filters/search", "role permissions"],
        "auth_heavy": ["login", "logout", "session", "protected pages", "password reset", "2FA/OTP"],
        "mixed_ui_api": ["UI critical flows", "API endpoints", "auth/session", "data consistency"],
        "unknown": ["to be determined after client clarification"],
    }.get(project_type, ["to be determined"])

    extra = []
    if "api" in text.lower() and project_type not in ("api_backend", "mixed_ui_api"):
        extra.append("API endpoints (mentioned)")
    if _hits(text, _MOBILE_SIGNALS) and "mobile" not in project_type:
        extra.append("mobile (mentioned — execution blocked until approved)")

    return base + extra


def _risks_for_type(project_type: str, text: str) -> List[str]:
    base = {
        "web_saas": ["auth/session handling", "role-based access", "form validation", "data consistency", "critical workflows", "flaky UI interactions"],
        "ecommerce": ["checkout flow integrity", "payment flow (sandbox required)", "order creation", "inventory/price correctness", "coupon/discount edge cases"],
        "api_backend": ["auth header validation", "input validation", "status codes", "data contracts", "rate limiting", "destructive endpoints"],
        "ai_generated_app": ["broken auth flows", "incomplete user flows", "state inconsistency", "unhandled errors", "missing validation", "fragile generated code"],
        "admin_panel": ["permission leaks", "destructive CRUD actions", "input validation", "production data modification risk", "role-based access"],
        "auth_heavy": ["credential safety", "account state changes", "session handling", "production auth risk", "2FA/email dependency", "destructive account actions"],
        "mixed_ui_api": ["UI/API data mismatch", "auth/session reuse", "test data setup", "environment stability"],
        "unknown": ["risks unclear until project type is confirmed"],
    }.get(project_type, ["to be determined"])

    extra = []
    if _hits(text, _PAYMENT_SIGNALS):
        extra.append("payment flow — sandbox confirmation required before testing")
    if _hits(text, _SECURITY_SIGNALS):
        extra.append("security testing scope — explicit approval required")
    if _hits(text, _MOBILE_SIGNALS):
        extra.append("mobile/native execution — future phase, explicit approval required")
    if _hits(text, _INTEGRATION_SIGNALS):
        extra.append("external integration calls — approval required, currently blocked")

    return base + extra


def _infer_client_goal(work_request: WorkRequest, project_type: str) -> str:
    summary = work_request.request_summary or work_request.request_title
    if not summary:
        return "Not specified — requires clarification."
    truncated = summary[:200]
    if project_type == "unknown":
        return f"Inferred goal: {truncated} (project type unclear — needs confirmation)"
    return truncated


def _infer_task_source(input_map: InputMap, work_request: WorkRequest) -> str:
    for src in input_map.sources:
        if src.input_type == "task_url":
            return f"task_url: {src.label}"
    if work_request.source_platform not in ("unknown", ""):
        return f"pasted_brief via {work_request.source_platform}"
    return "pasted_brief"


def _infer_target_application(input_map: InputMap) -> str:
    for src in input_map.sources:
        if src.input_type == "target_url":
            # Never expose a raw URL — use the label (already truncated, not a secret)
            return src.label
    return ""


def _build_assumptions(project_type: str, environment: str, input_map: InputMap) -> List[str]:
    a = [
        "No live execution has been performed — this is a planning artifact only.",
        "URLs were classified by string patterns only, not by fetching or browsing.",
        "Credentials, if detected, were redacted and not used.",
        f"Project type '{project_type}' is inferred from available text and may need confirmation.",
        f"Environment '{environment}' is inferred and may need confirmation.",
        "Automation recommendations are preliminary until target scope is confirmed.",
        "Application surfaces are typical for this project type — confirm with client.",
    ]
    has_creds = any(s.input_type == "credentials_reference" for s in input_map.sources)
    if has_creds:
        a.append("Credential references were detected and redacted. No credential value is stored.")
    return a


def _build_missing_info(
    project_type: str,
    environment: str,
    input_map: InputMap,
    text: str,
) -> List[str]:
    m = []
    has_target = any(s.input_type == "target_url" for s in input_map.sources)
    has_creds = any(s.input_type == "credentials_reference" for s in input_map.sources)

    if not has_target:
        m.append("Target application URL — required before any execution can be approved.")
    if environment == "unknown":
        m.append("Confirm whether the target environment is staging, production, or local.")
    if environment == "production":
        m.append("Production environment detected — explicit read-only approval required before any interaction.")

    m += [
        "Test credentials / test account availability — must be synthetic, not real user accounts.",
        "Acceptance criteria or definition of done for QA coverage.",
        "Critical user flows to prioritize in testing.",
        "Supported browsers and/or devices.",
    ]

    if _hits(text, _PAYMENT_SIGNALS):
        m.append("Confirm payment flows use sandbox mode (e.g. Stripe test keys) — never real money.")
    if _hits(text, _AUTH_SIGNALS) or has_creds:
        m.append("Confirm credentials are for a dedicated test account, not a real user account.")
    if _hits(text, _MOBILE_SIGNALS):
        m.append("Confirm mobile scope: mobile web (responsive), Android native, iOS native, or all?")
    if _hits(text, _INTEGRATION_SIGNALS):
        m.append("Confirm whether n8n/webhook/integration is only a reference or should be executed in a later phase.")
    if project_type in ("api_backend", "mixed_ui_api"):
        m.append("API documentation (OpenAPI/Swagger/Postman) — if available, share for structured test design.")
    if project_type == "unknown":
        m.append("Project type is unclear — provide more context about the application and testing goals.")

    m += [
        "CI/CD target — is there a pipeline where tests should run?",
        "Client delivery expectations — internal QA report only, or client-facing deliverable?",
    ]
    return m


def _build_safe_next_steps(
    project_type: str,
    task_type: str,
    environment: str,
    input_map: InputMap,
) -> List[str]:
    steps = []
    has_target = any(s.input_type == "target_url" for s in input_map.sources)
    has_creds = any(s.input_type == "credentials_reference" for s in input_map.sources)
    has_api_docs = any(s.input_type in ("api_docs_url", "api_docs_file") for s in input_map.sources)

    steps.append("Clarify missing information listed above with the client before proceeding.")
    steps.append("Review and confirm project type and environment assumptions.")

    if task_type in ("qa_automation", "test_strategy", "manual_qa"):
        steps.append("Build detailed QA strategy based on confirmed project type and scope.")
        steps.append("Design tactical test plan with prioritized test cases.")
    if task_type == "proposal":
        steps.append("Prepare client questions covering scope, environment, credentials, and delivery expectations.")
        steps.append("Draft proposal outline with risk/fit notes and delivery approach.")
    if has_api_docs:
        steps.append("Inspect API documentation (if a local file) to identify endpoint coverage areas — remote API docs require approval first.")
    if not has_target:
        steps.append("Obtain and confirm target application URL before any execution planning.")
    if has_creds:
        steps.append("Obtain explicit credential approval before any auth-related planning proceeds.")
    if project_type not in ("unknown", ""):
        steps.append(f"Plan Playwright scaffold architecture for {project_type} project (Phase 2C+).")
        steps.append("Identify test data strategy and synthetic account requirements.")

    return steps


def _build_blocked_actions(input_map: InputMap, text: str) -> List[str]:
    blocked = []

    has_target = any(s.input_type == "target_url" for s in input_map.sources)
    has_task_url = any(s.input_type == "task_url" for s in input_map.sources)
    has_creds = any(s.input_type == "credentials_reference" for s in input_map.sources)
    has_repo = any(s.input_type == "repo_url" for s in input_map.sources)
    has_api_docs_url = any(s.input_type == "api_docs_url" for s in input_map.sources)

    if has_target:
        blocked.append(
            "Open / fetch target URL — BLOCKED. "
            "Reason: target URL requires approval before any access. "
            "Required: explicit URL approval + environment confirmation. "
            "Risk: external_read_only → production_read_only."
        )
    if has_task_url:
        blocked.append(
            "Fetch task URL (Jira/Linear/Notion/etc.) — BLOCKED. "
            "Reason: remote task fetch not implemented in Phase 2B. "
            "Required: Phase 3 remote fetch capability + approval. "
            "Risk: external_read_only."
        )
    if has_repo:
        blocked.append(
            "Clone repository — BLOCKED. "
            "Reason: repo access not implemented. "
            "Required: repo access approval + Phase 3 capability. "
            "Risk: external_read_only."
        )
    if has_api_docs_url:
        blocked.append(
            "Fetch remote API docs — BLOCKED. "
            "Reason: remote API doc fetch not implemented. "
            "Required: approval + Phase 3 capability. "
            "Risk: external_read_only."
        )
    if has_creds:
        blocked.append(
            "Use credentials / execute auth flow — BLOCKED. "
            "Reason: credentials detected and redacted; no credential use in Phase 2A/2B. "
            "Required: explicit credential use approval + test account confirmation. "
            "Risk: payment_or_auth."
        )

    blocked += [
        "Execute browser tests (Playwright/Selenium) — BLOCKED. "
        "Reason: no execution in Phase 2A/2B. "
        "Required: full approval checklist + approved target URL. "
        "Risk: external_read_only.",

        "Run mobile/native tests — BLOCKED. "
        "Reason: mobile execution is Phase 3+. "
        "Required: mobile platform confirmation + device/emulator setup + approval. "
        "Risk: external_write.",

        "Send client-facing report — BLOCKED. "
        "Reason: no delivery until human review is complete. "
        "Required: HUMAN_REVIEW_REQUIRED.md checklist completion. "
        "Risk: client_delivery.",
    ]

    if _hits(text, _PAYMENT_SIGNALS):
        blocked.append(
            "Test payment flows — BLOCKED. "
            "Reason: payment testing requires sandbox confirmation in writing. "
            "Required: sandbox mode confirmed + test card numbers + written client authorization. "
            "Risk: payment_or_auth."
        )
    if _hits(text, _INTEGRATION_SIGNALS):
        blocked.append(
            "Call external integrations (n8n/webhook/Slack/Jira) — BLOCKED. "
            "Reason: integration calls disabled by default (IntegrationPolicy.allow_outbound_events=False). "
            "Required: explicit integration approval + IntegrationPolicy update. "
            "Risk: external_write."
        )
    if _hits(text, _SECURITY_SIGNALS):
        blocked.append(
            "Security testing actions (injection/auth bypass/pentest) — BLOCKED. "
            "Reason: destructive/security testing requires explicit written scope. "
            "Required: client written authorization + destructive-scope approval. "
            "Risk: security_sensitive."
        )

    return blocked


def _build_required_approvals(input_map: InputMap, text: str, environment: str) -> List[str]:
    approvals = []
    if any(s.input_type == "target_url" for s in input_map.sources):
        approvals.append("Target URL approval — before any fetch or browser execution.")
    if environment == "production":
        approvals.append("Production read-only approval — before any production interaction.")
    if any(s.input_type == "credentials_reference" for s in input_map.sources):
        approvals.append("Credential use approval — before any auth flow execution.")
    if _hits(text, _PAYMENT_SIGNALS):
        approvals.append("Sandbox payment confirmation — before any payment flow testing.")
    if _hits(text, _MOBILE_SIGNALS):
        approvals.append("Mobile platform confirmation and device/emulator approval — before mobile execution.")
    if _hits(text, _INTEGRATION_SIGNALS):
        approvals.append("Integration call approval — before any external webhook/n8n/Slack call.")
    if _hits(text, _SECURITY_SIGNALS):
        approvals.append("Security testing scope — written client authorization required.")
    if not approvals:
        approvals.append("Standard staging execution approval (via --approve flag + checklist) when target URL is confirmed.")
    return approvals


def _build_recommended_strategy(project_type: str, task_type: str, text: str) -> str:
    if task_type == "proposal":
        return (
            "Proposal mode: prepare scoping questions, risk/fit assessment, and delivery approach outline. "
            "No test execution in this phase."
        )
    if project_type == "web_saas":
        return (
            "Focus on: auth/session smoke, critical user flows (dashboard, settings, core features), "
            "form validation, role-based access. "
            "Automate with Playwright TypeScript. "
            "API layer if endpoints are accessible."
        )
    if project_type == "ecommerce":
        return (
            "Focus on: checkout happy path, cart operations, payment sandbox flow, "
            "order creation, account/orders. "
            "Automate with Playwright TypeScript. "
            "Validate payment flow only in confirmed sandbox mode."
        )
    if project_type == "api_backend":
        return (
            "Focus on: endpoint contract testing, auth header validation, "
            "happy path + error scenarios, status codes, data schema validation. "
            "Use Playwright API testing or pytest + requests. "
            "Document OpenAPI coverage if spec is available."
        )
    if project_type == "ai_generated_app":
        return (
            "Focus on: auth completeness, navigation stability, form submission, "
            "data persistence, broken/incomplete flows, edge case handling. "
            "Expect fragile areas — exploratory approach first."
        )
    if project_type == "admin_panel":
        return (
            "Focus on: role-based login, CRUD operations, permission boundaries, "
            "destructive action guards, search/filter. "
            "Automate critical admin flows. Manual exploratory for permission edge cases."
        )
    if project_type == "auth_heavy":
        return (
            "Focus on: login/logout, protected route access, session persistence, "
            "password reset, 2FA/OTP flow (test seed only), OAuth redirect. "
            "All credential use requires explicit approval and test accounts only."
        )
    if project_type == "mixed_ui_api":
        return (
            "Focus on: UI critical flows + API contract alignment, auth/session sharing, "
            "data consistency between UI and API, end-to-end integration scenarios."
        )
    return (
        "Project type unclear. Recommended: clarify scope first, then build strategy. "
        "Generic QA approach: smoke → auth → critical flows → regression."
    )


def _build_tactical_focus(project_type: str, task_type: str) -> List[str]:
    base = {
        "web_saas": ["auth/login smoke", "dashboard load", "key user actions", "form submission", "navigation", "API calls if accessible"],
        "ecommerce": ["add to cart", "checkout flow", "payment sandbox", "order confirmation", "account login"],
        "api_backend": ["endpoint happy paths", "auth header checks", "validation errors", "schema contracts", "error codes"],
        "ai_generated_app": ["login/auth", "navigation flow", "form submit", "data save/load", "broken route detection"],
        "admin_panel": ["admin login", "create/read/update/delete", "role permission check", "search/filter", "destructive action guard"],
        "auth_heavy": ["login", "logout", "session timeout", "password reset", "protected route redirect", "2FA smoke"],
        "mixed_ui_api": ["UI flow + API consistency check", "auth token reuse", "end-to-end scenario"],
        "unknown": ["to be defined after scope confirmation"],
    }.get(project_type, ["to be determined"])
    if task_type == "proposal":
        return ["client scoping questions", "risk/fit notes", "delivery outline"]
    return base


def _infer_confidence(
    project_type: str,
    environment: str,
    has_target: bool,
    text_length: int,
) -> str:
    score = 0
    if project_type != "unknown":
        score += 1
    if environment not in ("unknown", ""):
        score += 1
    if has_target:
        score += 1
    if text_length > 100:
        score += 1
    if score <= 1:
        return "low"
    if score <= 2:
        return "medium"
    return "high"


def _strategy_outline_md(
    blueprint: ProjectBlueprint,
    task_type: str,
) -> str:
    lines = [
        "# Initial QA Strategy Outline",
        "",
        "> **Planning only — no execution has occurred.**",
        f"> Project type: `{blueprint.project_type}` | Task type: `{task_type}` | Confidence: `{blueprint.confidence_level}`",
        "",
        "---",
        "",
        "## Likely test layers",
        "",
    ]
    for focus in blueprint.tactical_test_focus:
        lines.append(f"- {focus}")
    lines += [
        "",
        "## Likely first automation candidates",
        "",
        f"Based on project type `{blueprint.project_type}`:",
    ]
    first_candidates = blueprint.tactical_test_focus[:3] if blueprint.tactical_test_focus else ["To be determined"]
    for c in first_candidates:
        lines.append(f"- {c}")
    lines += [
        "",
        "## Likely manual / exploratory areas",
        "",
        "- Edge cases and error states",
        "- Accessibility / usability spot checks",
        "- Permission boundary verification",
        "- Areas with missing or unclear acceptance criteria",
        "",
        "## Likely blocked areas",
        "",
    ]
    for ba in blueprint.blocked_actions[:4]:
        short = ba.split(" — ")[0]
        lines.append(f"- {short}")
    lines += [
        "",
        "## Evidence needed later",
        "",
        "- Playwright HTML test report",
        "- Screenshots / traces from execution run",
        "- Pass/fail counts per test suite",
        "- Environment details (URL, browser version, test account)",
        "",
        "## Recommended next planning phase",
        "",
        blueprint.recommended_strategy or "Confirm scope, then build full QA strategy.",
        "",
        "---",
        "",
        "_This outline is preliminary. No tests have been executed. "
        "All URLs, credentials, and external resources require explicit approval before any access._",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

class ProjectBlueprintBuilder:
    """Builds ProjectBlueprint and planning artifacts from Phase 2A context.

    Phase 2B — no URL fetching, no browser, no credential use, no external calls.
    """

    def build(
        self,
        input_map: InputMap,
        work_request: WorkRequest,
        task_classification: TaskClassification,
    ) -> ProjectBlueprint:
        text = " ".join([
            work_request.request_title,
            work_request.request_summary,
            work_request.raw_brief,
        ])

        project_type = _infer_project_type(
            text, task_classification.task_type, task_classification.project_type
        )
        environment = _infer_environment(text, input_map.sources)
        task_source = _infer_task_source(input_map, work_request)
        target_application = _infer_target_application(input_map)
        has_target = bool(target_application)

        surfaces = _surfaces_for_type(project_type, text)
        risks = _risks_for_type(project_type, text)
        assumptions = _build_assumptions(project_type, environment, input_map)
        missing_info = _build_missing_info(project_type, environment, input_map, text)
        safe_steps = _build_safe_next_steps(
            project_type, task_classification.task_type, environment, input_map
        )
        blocked = _build_blocked_actions(input_map, text)
        approvals = _build_required_approvals(input_map, text, environment)
        strategy = _build_recommended_strategy(project_type, task_classification.task_type, text)
        focus = _build_tactical_focus(project_type, task_classification.task_type)
        confidence = _infer_confidence(project_type, environment, has_target, len(text))

        return ProjectBlueprint(
            project_id=input_map.project_id,
            project_name=work_request.request_title[:80] or "Unnamed project",
            project_type=project_type,
            client_goal=_infer_client_goal(work_request, project_type),
            task_source=task_source,
            target_application=target_application or "Not yet provided",
            target_urls=[s.raw_value for s in input_map.sources if s.input_type == "target_url"],
            input_sources=[s.input_type for s in input_map.sources],
            environment=environment,
            application_surfaces=surfaces,
            risk_areas=risks,
            assumptions=assumptions,
            missing_information=missing_info,
            safe_next_steps=safe_steps,
            blocked_actions=blocked,
            required_approvals=approvals,
            recommended_strategy=strategy,
            tactical_test_focus=focus,
            confidence_level=confidence,
            phase="blueprint",
        )

    def render_artifacts(
        self,
        blueprint: ProjectBlueprint,
        task_type: str,
        out_dir,
    ) -> dict:
        """Write all Phase 2B planning artifacts. Returns {name: path} dict."""
        from pathlib import Path
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        paths = {}

        paths["blueprint_json"] = _write_json(out / "PROJECT_BLUEPRINT.json", blueprint.to_dict())
        paths["blueprint_md"] = _write_text(out / "PROJECT_BLUEPRINT.md", _blueprint_md(blueprint))
        paths["assumptions_md"] = _write_text(out / "ASSUMPTIONS.md", _assumptions_md(blueprint))
        paths["missing_info_md"] = _write_text(out / "MISSING_INFO.md", _missing_info_md(blueprint))
        paths["safe_next_steps_md"] = _write_text(out / "SAFE_NEXT_STEPS.md", _safe_next_steps_md(blueprint))
        paths["blocked_actions_md"] = _write_text(out / "BLOCKED_ACTIONS.md", _blocked_actions_md(blueprint))
        paths["strategy_outline_md"] = _write_text(
            out / "INITIAL_QA_STRATEGY_OUTLINE.md",
            _strategy_outline_md(blueprint, task_type),
        )

        return paths


# ---------------------------------------------------------------------------
# Markdown renderers
# ---------------------------------------------------------------------------

def _blueprint_md(bp: ProjectBlueprint) -> str:
    lines = [
        f"# Project Blueprint — {bp.project_id}",
        "",
        "> **Planning artifact only. No execution has occurred.**",
        "",
        "---",
        "",
        "## Overview",
        "",
        "| Field | Value |",
        "|---|---|",
        f"| Project ID | `{bp.project_id}` |",
        f"| Project type | `{bp.project_type}` |",
        f"| Environment | `{bp.environment}` |",
        f"| Confidence | `{bp.confidence_level}` |",
        f"| Phase | `{bp.phase}` |",
        f"| Created | {bp.created_at} |",
        "",
        "## Client goal",
        "",
        bp.client_goal or "_Not specified._",
        "",
        "## Task source",
        "",
        bp.task_source or "_Unknown._",
        "",
        "## Target application",
        "",
        f"{bp.target_application}",
        "",
    ]

    if bp.target_application and bp.target_application != "Not yet provided":
        lines.append("> **Blocked for execution** — target URL requires approval before any fetch or browser run.")
        lines.append("")

    lines += [
        "## Input sources",
        "",
    ]
    for src in bp.input_sources:
        lines.append(f"- `{src}`")
    lines.append("")

    lines += ["## Application surfaces", ""]
    for s in bp.application_surfaces:
        lines.append(f"- {s}")
    lines.append("")

    lines += ["## Risk areas", ""]
    for r in bp.risk_areas:
        lines.append(f"- {r}")
    lines.append("")

    lines += ["## Missing information", ""]
    for m in bp.missing_information:
        lines.append(f"- {m}")
    lines.append("")

    lines += ["## Assumptions", ""]
    for a in bp.assumptions:
        lines.append(f"- {a}")
    lines.append("")

    lines += ["## Safe next steps", ""]
    for i, s in enumerate(bp.safe_next_steps, 1):
        lines.append(f"{i}. {s}")
    lines.append("")

    lines += ["## Blocked actions", ""]
    for b in bp.blocked_actions:
        short = b.split(" — BLOCKED")[0]
        lines.append(f"- **{short}** — BLOCKED")
    lines.append("")

    lines += ["## Required approvals", ""]
    for a in bp.required_approvals:
        lines.append(f"- {a}")
    lines.append("")

    lines += [
        "## Recommended strategy",
        "",
        bp.recommended_strategy or "_To be determined._",
        "",
        "## Tactical test focus",
        "",
    ]
    for f in bp.tactical_test_focus:
        lines.append(f"- {f}")
    lines += [
        "",
        "---",
        "",
        "_Generated by ProjectBlueprintBuilder (Phase 2B — planning only). "
        "No tests were executed. No URLs were fetched. "
        "All blocked actions require explicit approval before proceeding._",
        "",
    ]
    return "\n".join(lines)


def _assumptions_md(bp: ProjectBlueprint) -> str:
    lines = [
        f"# Assumptions — {bp.project_id}",
        "",
        "> These are working assumptions derived from available input. "
        "Confirm each with the client before proceeding to execution.",
        "",
    ]
    for i, a in enumerate(bp.assumptions, 1):
        lines.append(f"{i}. {a}")
    lines += ["", "---", "", "_No execution has occurred. Assumptions are based on text classification only._", ""]
    return "\n".join(lines)


def _missing_info_md(bp: ProjectBlueprint) -> str:
    lines = [
        f"# Missing Information — {bp.project_id}",
        "",
        "> Gather this information before building the full QA strategy or executing any tests.",
        "",
    ]
    for i, m in enumerate(bp.missing_information, 1):
        lines.append(f"{i}. {m}")
    lines += ["", "---", "", "_Resolving missing information is required before Phase 2C (Strategy Planner)._", ""]
    return "\n".join(lines)


def _safe_next_steps_md(bp: ProjectBlueprint) -> str:
    lines = [
        f"# Safe Next Steps — {bp.project_id}",
        "",
        "> Actions that are safe to perform right now, without any URL access or execution.",
        "",
    ]
    for i, s in enumerate(bp.safe_next_steps, 1):
        lines.append(f"{i}. {s}")
    lines += ["", "---", "", "_All listed steps are planning-only. None require URL access, credentials, or execution._", ""]
    return "\n".join(lines)


def _blocked_actions_md(bp: ProjectBlueprint) -> str:
    lines = [
        f"# Blocked Actions — {bp.project_id}",
        "",
        "> These actions cannot proceed until the listed approvals are obtained.",
        "",
    ]
    for b in bp.blocked_actions:
        parts = b.split(". ")
        lines.append(f"### {parts[0]}")
        lines.append("")
        for part in parts[1:]:
            if part.strip():
                lines.append(f"{part.strip()}")
        lines.append("")
    lines += [
        "---",
        "",
        "_No blocked action was attempted. This document lists what requires approval for future phases._",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def _write_json(path, data: dict) -> str:
    import json
    from pathlib import Path
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return str(path)


def _write_text(path, content: str) -> str:
    from pathlib import Path
    Path(path).write_text(content, encoding="utf-8")
    return str(path)

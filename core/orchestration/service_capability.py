"""Service Capability Matrix (v3.2 Section 7).

A versioned, honest contract for the QA services the operator publicly offers. It records, per
service: supported execution modes, required inputs/tools/access, an HONEST readiness state, the
acceptance evidence that backs it, the safety boundaries, a fallback, and the exact operator/client
action when blocked. Readiness never overstates: only services with genuine acceptance in this repo
are "Fixture Verified" / "Live Verified"; anything needing the client's repo/accounts/runtime is
"Needs Client"; anything needing an operator credential/authorization is "Needs Operator".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List

SCHEMA_VERSION = "service-capability-matrix/v1"

# Execution modes (Section 3).
PLAN_ONLY = "PLAN_ONLY"
AUTONOMOUS_LOCAL = "AUTONOMOUS_LOCAL"
APPROVAL_GATED_EXTERNAL = "APPROVAL_GATED_EXTERNAL"

# Honest readiness ladder (Section 8) as used by the capability matrix.
READINESS = ("Declared", "Installed", "Connected", "Authenticated", "Runtime Verified",
             "Fixture Verified", "Live Verified", "Needs Operator", "Needs Client", "Blocked",
             "Unavailable")


@dataclass
class ServiceCapability:
    service_id: str
    name: str
    description: str
    modes: List[str]
    required_inputs: List[str]
    required_tools: List[str]
    required_access: List[str]
    readiness: str
    acceptance_evidence: List[str]          # test files / artifacts that genuinely back the claim
    safety_boundaries: List[str]
    fallback: str
    operator_action_if_blocked: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


_C = ServiceCapability
SERVICE_CAPABILITIES: List[ServiceCapability] = [
    _C("playwright_framework", "Playwright + TypeScript framework engineering",
       "Create or assess a Playwright/TS framework: fixtures, page objects, config, auth state, UI+API "
       "tests, parallelism, retries, traces/screenshots/video, reporting, tagging, CI integration.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL], ["repository or target", "acceptance criteria"],
       ["node", "playwright_internal", "@playwright/test", "chromium"],
       ["client repository (for real client work)"],
       "Fixture Verified",
       ["tests/test_v3_genuine_execution_ab.py (real `playwright test` on a generated framework)"],
       ["local fixtures only in acceptance", "no external targets without authorization"],
       "internal Playwright runner (fixture) when the client repo is not yet provided",
       "provide the client repository + acceptance criteria to run against real client work"),
    _C("migration", "Selenium/Cypress/PyTest assessment and migration",
       "Inventory an existing suite, map coverage, identify flaky/slow tests, plan and stage a "
       "Selenium/Cypress -> Playwright migration with parity evidence before retiring old tests.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL], ["existing suite", "coverage expectations"],
       ["node", "playwright_internal", "@playwright/test"],
       ["client suite"],
       "Fixture Verified",
       ["tests/test_v32_service_acceptance.py::migration (inventory + migrate + parity)"],
       ["preserve critical coverage; validate before retiring old tests"],
       "internal migration acceptance on a legacy-style fixture until the client suite is provided",
       "share the existing Selenium/Cypress suite to produce a real inventory + migration plan"),
    _C("ui_api_db_validation", "UI, API, and database validation",
       "REST/OpenAPI/GraphQL positive+negative testing, schema/contract validation, error handling, "
       "state transitions, and safe read-only PostgreSQL/MySQL verification (mutation gated).",
       [PLAN_ONLY, AUTONOMOUS_LOCAL, APPROVAL_GATED_EXTERNAL],
       ["OpenAPI/GraphQL contract or endpoint", "database reference (read-only)"],
       ["api_runner_internal", "python", "db drivers (client-specific)"],
       ["authorized endpoint / read-only DB credentials (client)"],
       "Fixture Verified",
       ["tests/test_v3_genuine_execution_cd.py (real OpenAPI + localhost HTTP)",
        "tests/test_v32_service_acceptance.py::sqlite_readonly (real read-only DB query)"],
       ["database MUTATION requires explicit authorization and is never the default"],
       "SQLite read-only fixture; PostgreSQL/MySQL are Client Validation Required until credentials",
       "provide a read-only DB connection (or a Docker DB) + the API/GraphQL contract"),
    _C("cicd", "CI/CD generation, repair, and optimization",
       "GitHub Actions / Azure DevOps / GitLab CI / Jenkins: execution, sharding, caching, artifacts, "
       "reports, retries, failure diagnostics, secret references, PR quality gates, Docker repro.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL, APPROVAL_GATED_EXTERNAL],
       ["repository", "target CI provider"], ["gh", "git"],
       ["client CI access for non-GitHub providers"],
       "Live Verified",
       ["this repository's hosted GitHub Actions (4 jobs) genuinely run on every candidate SHA"],
       ["only GitHub Actions is Live Verified here; Azure/GitLab/Jenkins configs are Fixture "
        "Verified / Client Validation Required until run on the client's provider"],
       "generate the config labeled Client Validation Required for non-GitHub providers",
       "grant access to the target CI provider to genuinely run non-GitHub pipelines"),
    _C("stabilization", "QA stabilization and release readiness",
       "Flaky-test measurement via repeated runs, root-cause grouping, environment/product/test "
       "classification, quarantine with debt tracking, deterministic remediation, before/after "
       "measurement, coverage-gap + critical-flow mapping, and a release-readiness verdict.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL], ["test suite"], ["python", "pytest"],
       ["client suite for real client work"],
       "Fixture Verified",
       ["tests/test_v32_service_acceptance.py::flaky_stabilization (measured before/after on a "
        "controlled intermittent fixture)"],
       ["historical portfolio metrics are NEVER reported as a new client's result"],
       "run on a controlled fixture until the client suite is available",
       "provide the flaky suite + CI history to measure real before/after on the client project"),
    _C("ai_mvp", "AI-generated MVP testing",
       "QA for Lovable/Cursor/Bolt/v0/AI-generated SaaS: broken auth, authorization boundaries, race "
       "conditions, duplicate submissions, async/persistence/stale data, API mismatches, responsive, "
       "accessibility, edge/error/loading/empty states, secret exposure, release readiness.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL], ["app URL or repository"],
       ["playwright_internal", "chromium", "axe_core_python"],
       ["authorized app/staging"],
       "Fixture Verified",
       ["tests/test_v32_service_acceptance.py::ai_mvp (real browser over a generated MVP fixture: "
        "auth/state/edge cases + axe)"],
       ["local fixture only in acceptance; no unauthorized targets"],
       "internal MVP fixture until the client app is provided",
       "provide the AI-generated app (URL/repo) + a test account to test the real MVP"),
    _C("bdd", "BDD and business-readable acceptance",
       "Gherkin/Cucumber assessment, business-readable acceptance scenarios, and requirement -> "
       "scenario -> automated test -> evidence traceability without redundant non-executable features.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL], ["requirements / acceptance criteria"], ["python", "node"],
       ["client requirements"],
       "Declared",
       ["planning capability; executable BDD acceptance is generated per client project"],
       ["avoid redundant feature files with no executable value"],
       "produce a traceability plan; executable step definitions require the client project",
       "provide the requirements + the target framework to generate executable BDD scenarios"),
    _C("website_qa", "Website QA check",
       "Critical navigation/flows, forms (no unauthorized submission), responsive behavior, browser "
       "runtime errors, broken assets, accessibility, safe performance diagnostics, severity + repro.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL], ["authorized public/staging URL"],
       ["playwright_internal", "chromium", "axe_core_python"],
       ["authorization for the target site"],
       "Fixture Verified",
       ["tests/test_v3_genuine_execution_ab.py::scenario_b (real Chromium + axe detects a planted "
        "accessibility defect)"],
       ["read-only; no form submission/purchase; never bypass auth/CAPTCHA"],
       "internal audit fixture until an authorized target is provided",
       "authorize a specific public/staging URL for a real website QA pass"),
    _C("workflow_automation", "n8n and Make workflow automation",
       "Analyze/build/repair workflows with input/output contracts, retries, idempotency, error paths, "
       "redaction, notifications, sandbox validation, an exportable artifact, and operator docs.",
       [PLAN_ONLY, APPROVAL_GATED_EXTERNAL], ["workflow spec", "platform access"],
       ["n8n/Make runtime (client)"],
       ["authorized n8n/Make workspace + credentials"],
       "Needs Client",
       ["no acceptance without the real runtime; an unexecuted JSON workflow is never Live Verified"],
       ["do not describe an unexecuted workflow as Live Verified"],
       "produce a design + exportable artifact; validation needs the real platform",
       "provide authorized n8n/Make access + credentials to build and sandbox-validate a workflow"),
    _C("technical_writing", "Technical and article writing",
       "Source-backed drafting for QA/Playwright/TS/JS/API/CI-CD/SaaS/AI testing/automation with a "
       "research map, factual-claim map, citations, technical validation, and operator review.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL], ["topic + source inputs"], ["python"], [],
       "Fixture Verified",
       ["tests/test_v32_service_acceptance.py::technical_writing (source-backed artifact + claim/"
        "citation validation, labeled as an acceptance artifact not client work)"],
       ["no fabricated experience/benchmarks; operator review before client delivery"],
       "generate a draft + claim map; operator review is mandatory before delivery",
       "operator reviews and approves the draft before any client delivery"),
    _C("legal_tech", "Legal-tech and compliance-oriented writing/testing",
       "Source-backed legal-tech whitepaper drafts, compliance QA checklists, evidence/control mapping, "
       "and DORA-oriented testing evidence when the client supplies the control framework.",
       [PLAN_ONLY], ["client control framework + sources"], ["python"], ["client authorization"],
       "Needs Operator",
       ["source-backed drafting only; mandatory operator (legal) review before delivery"],
       ["never a legal certification; never a regulator; no compliance guarantee; not a substitute "
        "for professional legal review"],
       "produce a source-mapped draft with limitations; a qualified reviewer must sign off",
       "a qualified legal/compliance reviewer must review before any legal/compliance delivery"),
    _C("docker_aws", "Docker and bounded AWS QA support",
       "Reproducible test environments, Dockerfile/Compose assessment, containerized test execution, "
       "service dependency readiness, logs/health checks, and bounded AWS QA diagnostics with scope.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL, APPROVAL_GATED_EXTERNAL],
       ["Dockerfile/Compose or AWS scope + credentials"], ["docker"],
       ["AWS credentials + explicit scope (client)"],
       "Fixture Verified",
       ["tests/test_v32_service_acceptance.py::docker (Docker runtime probed; containerized DB smoke "
        "when the runtime permits, else honestly Client Validation Required)"],
       ["never provision/deploy/mutate/purchase cloud resources without approval"],
       "Docker assessment locally; AWS is Client Validation Required until credentials + scope",
       "provide AWS credentials + an explicit bounded scope for real AWS QA diagnostics"),
]

_BY_ID = {s.service_id: s for s in SERVICE_CAPABILITIES}


def snapshot() -> Dict[str, Any]:
    return {"schema": SCHEMA_VERSION, "service_count": len(SERVICE_CAPABILITIES),
            "services": [s.to_dict() for s in SERVICE_CAPABILITIES]}


def get_service(service_id: str) -> ServiceCapability | None:
    return _BY_ID.get(service_id)

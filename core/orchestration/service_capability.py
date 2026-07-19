"""Service Capability Matrix (v3.2 Section 7).

A versioned, honest contract for the QA services the operator publicly offers. It records, per
service: supported execution modes, required inputs/tools/access, an HONEST readiness state, the
acceptance evidence that backs it, the safety boundaries, a fallback, and the exact operator/client
action when blocked. Readiness never overstates: only services with genuine acceptance in this repo
are "Fixture Verified" / "Live Verified"; anything needing the client's repo/accounts/runtime is
"Needs Client"; anything needing an operator credential/authorization is "Needs Operator".
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = "service-capability-matrix/v2"

# Execution modes (Section 3).
PLAN_ONLY = "PLAN_ONLY"
AUTONOMOUS_LOCAL = "AUTONOMOUS_LOCAL"
APPROVAL_GATED_EXTERNAL = "APPROVAL_GATED_EXTERNAL"

# Honest readiness ladder (Section 8) as used by the capability matrix. "Runtime Available" marks a
# provider whose runtime is present but not yet exercised here; "Partially Verified" is the ONLY
# honest aggregate when a multi-provider row has components at different readiness (item 19).
READINESS = ("Declared", "Installed", "Connected", "Authenticated", "Runtime Available",
             "Runtime Verified", "Fixture Verified", "Live Verified", "Partially Verified",
             "Needs Operator", "Needs Client", "Blocked", "Unavailable")

# Readiness values that genuinely back a claim (each component that has one is really exercised).
_VERIFIED = frozenset({"Runtime Verified", "Fixture Verified", "Live Verified"})


@dataclass
class Component:
    """A provider/engine WITHIN a service that has its own honest readiness (items 18-19). A row is
    never shown as Live/Fixture Verified when only one of its components is verified."""
    component_id: str
    name: str
    readiness: str
    evidence: str = ""
    action_if_blocked: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


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
    required_access_ids: List[str] = field(default_factory=list)   # typed AccessBootstrap ids
    components: List[Component] = field(default_factory=list)       # per-provider readiness

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def aggregate_readiness(components: List[Component], declared: str) -> str:
    """Honest aggregate for a multi-component row: the shared readiness when every component agrees,
    else 'Partially Verified' (never overstating to Live/Fixture Verified when only one is verified)."""
    if not components:
        return declared
    vals = {c.readiness for c in components}
    if len(vals) == 1:
        return next(iter(vals))
    return "Partially Verified"


_Cmp = Component
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
       "provide the client repository + acceptance criteria to run against real client work",
       required_access_ids=["client_repository"]),
    _C("migration", "Selenium/Cypress/PyTest assessment and migration",
       "Inventory an existing suite, map coverage, identify flaky/slow tests, plan and stage a "
       "Selenium/Cypress -> Playwright migration with parity evidence before retiring old tests.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL], ["existing suite", "coverage expectations"],
       ["node", "playwright_internal", "@playwright/test"],
       ["client suite"],
       "Fixture Verified",
       ["tests/test_v32_service_acceptance.py::migration invokes production "
        "service_profiles.migrate_selenium_to_playwright (inventory + spec generation + parity)"],
       ["preserve critical coverage; validate before retiring old tests"],
       "internal migration acceptance on a legacy-style fixture until the client suite is provided",
       "share the existing Selenium/Cypress suite to produce a real inventory + migration plan",
       required_access_ids=["client_repository"]),
    _C("ui_api_db_validation", "UI, API, and database validation",
       "REST/OpenAPI/GraphQL positive+negative testing, schema/contract validation, error handling, "
       "state transitions, and safe read-only PostgreSQL/MySQL verification (mutation gated).",
       [PLAN_ONLY, AUTONOMOUS_LOCAL, APPROVAL_GATED_EXTERNAL],
       ["OpenAPI/GraphQL contract or endpoint", "database reference (read-only)"],
       ["api_runner_internal", "python", "db drivers (client-specific)"],
       ["authorized endpoint / read-only DB credentials (client)"],
       "Partially Verified",          # SQLite is Fixture Verified; PG/MySQL depend on detection
       ["tests/test_v3_genuine_execution_cd.py (real OpenAPI + localhost HTTP)",
        "tests/test_v32_service_acceptance.py::sqlite_readonly (real read-only DB query)"],
       ["database MUTATION requires explicit authorization and is never the default"],
       "SQLite read-only fixture; PostgreSQL/MySQL are Runtime Available or Needs Client as detected",
       "provide a read-only DB connection (or a Docker DB) + the API/GraphQL contract",
       required_access_ids=["client_database", "client_test_account"],
       components=[
           _Cmp("sqlite", "SQLite (read-only)", "Fixture Verified",
                "tests/test_v32_service_acceptance.py::sqlite_readonly invokes the production "
                "read-only query guard", ""),
           _Cmp("postgresql", "PostgreSQL (read-only)", "Needs Client",
                "resolved at snapshot: Runtime Available when the driver is installed",
                "client provides a read-only PostgreSQL connection (or a Docker DB)"),
           _Cmp("mysql", "MySQL (read-only)", "Needs Client",
                "resolved at snapshot: Runtime Available when the driver is installed",
                "client provides a read-only MySQL connection (or a Docker DB)")]),
    _C("cicd", "CI/CD generation, repair, and optimization",
       "GitHub Actions / Azure DevOps / GitLab CI / Jenkins: execution, sharding, caching, artifacts, "
       "reports, retries, failure diagnostics, secret references, PR quality gates, Docker repro.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL, APPROVAL_GATED_EXTERNAL],
       ["repository", "target CI provider"], ["gh", "git"],
       ["client CI access for non-GitHub providers"],
       "Partially Verified",          # aggregate: only GitHub Actions is Live Verified here (item 19)
       ["this repository's hosted GitHub Actions (4 jobs) genuinely run on every candidate SHA"],
       ["the aggregate row is NEVER shown as Live Verified; only the GitHub Actions component is. "
        "Azure/GitLab/Jenkins are Needs Client until run on the client's provider"],
       "generate the config; non-GitHub providers stay Needs Client until run on the client's CI",
       "grant access to the target CI provider to genuinely run non-GitHub pipelines",
       required_access_ids=["client_ci_access"],
       components=[
           _Cmp("github_actions", "GitHub Actions", "Live Verified",
                "this repo's 4-job hosted CI runs on every candidate SHA", ""),
           _Cmp("azure_devops", "Azure DevOps", "Needs Client", "no client Azure project executed",
                "client grants Azure DevOps access to run the generated pipeline"),
           _Cmp("gitlab_ci", "GitLab CI", "Needs Client", "no client GitLab project executed",
                "client grants GitLab access to run the generated pipeline"),
           _Cmp("jenkins", "Jenkins", "Needs Client", "no client Jenkins instance executed",
                "client grants Jenkins access to run the generated pipeline")]),
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
       "provide the flaky suite + CI history to measure real before/after on the client project",
       required_access_ids=["client_repository"]),
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
       "provide the AI-generated app (URL/repo) + a test account to test the real MVP",
       required_access_ids=["client_test_account"]),
    _C("bdd", "BDD and business-readable acceptance",
       "Gherkin/Cucumber assessment, business-readable acceptance scenarios, and requirement -> "
       "scenario -> automated test -> evidence traceability without redundant non-executable features.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL], ["requirements / acceptance criteria"], ["python", "node"],
       ["client requirements"],
       "Partially Verified",          # internal profile is verified; the real Cucumber runtime is not
       ["tests/test_v32_service_acceptance.py::bdd (production service_profiles.generate_bdd_suite + "
        "run_bdd_suite: requirements -> executable scenarios -> pass/fail + traceability)"],
       ["the internal Python profile is a bounded callback runner; the actual Cucumber/client "
        "framework is NOT verified here and stays Needs Client until run on the client's stack"],
       "generate executable scenarios from the requirements; real client work needs the client repo",
       "provide the requirements + the target framework to generate executable BDD scenarios",
       required_access_ids=["client_repository"],
       components=[
           _Cmp("bdd_internal", "Internal executable BDD profile", "Fixture Verified",
                "service_profiles.generate_bdd_suite + run_bdd_suite genuinely execute scenarios "
                "with requirement traceability", ""),
           _Cmp("cucumber", "Cucumber / client framework", "Needs Client",
                "the real Cucumber runtime is not provisioned or run here",
                "provide the client's Cucumber/BDD framework to run scenarios on the real stack")]),
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
       "authorize a specific public/staging URL for a real website QA pass",
       required_access_ids=["client_test_account"]),
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
       "provide authorized n8n/Make access + credentials to build and sandbox-validate a workflow",
       required_access_ids=["client_workflow_platform"]),
    _C("technical_writing", "Technical and article writing",
       "Source-backed drafting for QA/Playwright/TS/JS/API/CI-CD/SaaS/AI testing/automation with a "
       "research map, factual-claim map, citations, technical validation, and operator review.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL], ["topic + source inputs"], ["python"], [],
       "Fixture Verified",
       ["tests/test_v32_service_acceptance.py::technical_writing invokes production "
        "service_profiles.validate_source_backed_article (claim/citation map + fabricated-benchmark "
        "rejection), labeled as an acceptance artifact not client work"],
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
       "a qualified legal/compliance reviewer must review before any legal/compliance delivery",
       required_access_ids=["client_control_framework"]),
    _C("docker_aws", "Docker and bounded AWS QA support",
       "Reproducible test environments, Dockerfile/Compose assessment, containerized test execution, "
       "service dependency readiness, logs/health checks, and bounded AWS QA diagnostics with scope.",
       [PLAN_ONLY, AUTONOMOUS_LOCAL, APPROVAL_GATED_EXTERNAL],
       ["Dockerfile/Compose or AWS scope + credentials"], ["docker"],
       ["AWS credentials + explicit scope (client)"],
       "Partially Verified",          # Docker + AWS are distinct components with distinct readiness
       ["tests/test_v32_service_acceptance.py::docker (Docker runtime probed honestly; containerized "
        "smoke only when the runtime + a local image genuinely permit)"],
       ["the aggregate row is NEVER shown as Verified on the strength of Docker alone; AWS is its own "
        "Needs Client component. Never provision/deploy/mutate/purchase cloud resources without approval"],
       "Docker assessment locally; AWS stays Needs Client until credentials + explicit scope",
       "provide AWS credentials + an explicit bounded scope for real AWS QA diagnostics",
       required_access_ids=["client_cloud_scope"],
       components=[
           _Cmp("docker", "Docker runtime", "Runtime Available",
                "docker probed honestly; containerized smoke runs only when the daemon + a local "
                "image are present, else Needs Client",
                "install Docker + a local image for a bounded container smoke"),
           _Cmp("aws", "AWS", "Needs Client", "no AWS scope/credentials provided",
                "client provides AWS credentials + an explicit bounded scope")]),
]

_BY_ID = {s.service_id: s for s in SERVICE_CAPABILITIES}


def detect_components() -> Dict[str, str]:
    """Resolve the readiness of the dynamic components (DB engines + Docker) from ACTUAL local
    detection. Bounded and dependency-light (driver import + PATH lookup only; no daemon round-trip)
    so a snapshot never blocks. Absent detection leaves the conservative static default."""
    import shutil
    detected: Dict[str, str] = {}
    try:
        from core.orchestration.db_validation import engine_readiness
        er = engine_readiness()
        for eng in ("sqlite", "postgresql", "mysql"):
            v = er.get(eng, "")
            if v:
                detected[eng] = "Needs Client" if v == "Client Validation Required" else v
    except Exception:
        pass
    detected["docker"] = "Runtime Available" if shutil.which("docker") else "Needs Client"
    return detected


def _resolve_components(svc: ServiceCapability, detected: Dict[str, str]) -> List[Component]:
    return [Component(c.component_id, c.name, detected.get(c.component_id, c.readiness),
                      c.evidence, c.action_if_blocked) for c in svc.components]


def service_view(svc: ServiceCapability, detected: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """A service's honest dict with components resolved and the aggregate readiness recomputed so a
    multi-component row is never shown as Live/Fixture Verified when only one component is verified."""
    detected = detected if detected is not None else detect_components()
    d = svc.to_dict()
    if svc.components:
        comps = _resolve_components(svc, detected)
        d["components"] = [c.to_dict() for c in comps]
        d["readiness"] = aggregate_readiness(comps, svc.readiness)
    return d


def snapshot() -> Dict[str, Any]:
    detected = detect_components()
    return {"schema": SCHEMA_VERSION, "service_count": len(SERVICE_CAPABILITIES),
            "services": [service_view(s, detected) for s in SERVICE_CAPABILITIES]}


def get_service(service_id: str) -> Optional[ServiceCapability]:
    return _BY_ID.get(service_id)

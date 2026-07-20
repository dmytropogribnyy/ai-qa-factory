"""Project Resource Readiness — chat-first, per-project (v3.2).

Composes the EXISTING planning signals (profile, INPUT_MAP, MissingInformationAnalyzer, the feasibility
capability/tool selection, and the operator/local AccessBootstrap readiness) into one per-project
Resource Readiness Checklist. It is NOT a second subsystem or a second store: it is a deterministic
projection persisted next to the other planning artifacts (RESOURCE_READINESS.json/.md) and rendered
identically in Claude/VS Code chat, the CLI, and (as a read-only mirror) the Dashboard.

Each resource carries: name/type, why it is needed, required/optional/not-applicable, minimum access
level, environment, current status, who must provide it, a SAFE connection/storage instruction (env
var NAME only — never a value), a validation result, the capabilities it unlocks, and a blocker +
next action. Every Needs-Client item gets a ready-to-copy client request that requests scope/access
NAMES only — never a secret — and is never sent automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# Canonical resource statuses (distinct from the service-capability readiness ladder).
DETECTED = "Detected"            # referenced/found in the intake, not yet validated
PROVIDED = "Provided"            # the operator/client supplied it (name/reference), not yet validated
VERIFIED = "Verified"            # actually checked and working
NEEDS_CLIENT = "Needs Client"    # only the client can supply it (repo, account, DB, staging URL)
NEEDS_OPERATOR = "Needs Operator"  # the operator must configure/authorize it locally
OPTIONAL = "Optional"            # helpful but not required for the core deliverable
NOT_APPLICABLE = "Not Applicable"  # not relevant to this profile
BLOCKED = "Blocked"              # a prerequisite failed; cannot proceed
INVALID = "Invalid"              # supplied but malformed/unusable
CANONICAL_STATUSES = (DETECTED, PROVIDED, VERIFIED, NEEDS_CLIENT, NEEDS_OPERATOR, OPTIONAL,
                      NOT_APPLICABLE, BLOCKED, INVALID)

REQUIRED, OPTIONAL_NEC, NA_NEC = "Required", "Optional", "Not Applicable"


@dataclass
class ResourceItem:
    name: str
    resource_type: str
    why_needed: str
    necessity: str                       # Required | Optional | Not Applicable
    min_access_level: str
    environment: str                     # client-provided | operator-local | local
    status: str                          # one of CANONICAL_STATUSES
    provided_by: str                     # client | operator | local | n/a
    connection_instruction: str          # env var NAME / safe storage — never a value
    validation_result: str
    capabilities_unlocked: List[str] = field(default_factory=list)
    blocker: str = ""
    next_action: str = ""
    client_request: str = ""             # ready-to-copy (Needs Client only); never auto-sent

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name, "resource_type": self.resource_type, "why_needed": self.why_needed,
            "necessity": self.necessity, "min_access_level": self.min_access_level,
            "environment": self.environment, "status": self.status, "provided_by": self.provided_by,
            "connection_instruction": self.connection_instruction,
            "validation_result": self.validation_result,
            "capabilities_unlocked": list(self.capabilities_unlocked), "blocker": self.blocker,
            "next_action": self.next_action, "client_request": self.client_request}


# Per-profile resource templates. detect_types: input_map source types that satisfy the resource.
_TEMPLATES: Dict[str, List[Dict[str, Any]]] = {
    "web_app_audit": [
        {"name": "Target web app URL", "type": "url", "why": "the page(s) to audit",
         "necessity": REQUIRED, "access": "public URL", "env": "client-provided", "by": "client",
         "detect": ("target_url", "task_url"), "unlocks": ["browser audit", "accessibility", "performance"],
         "instruction": "paste the exact URL into analyze-job intake (no secret)"},
        {"name": "Authenticated test account", "type": "account",
         "why": "reach pages behind login for a private app", "necessity": "auth",
         "access": "dedicated test/staging account", "env": "client-provided", "by": "client",
         "detect": (), "unlocks": ["authenticated-page audit"],
         "instruction": "client provides a dedicated NON-production test login; store only by env-var NAME"},
        {"name": "Browser runtime (Playwright)", "type": "runtime",
         "why": "run the real browser checks", "necessity": REQUIRED, "access": "local",
         "env": "operator-local", "by": "operator", "detect": (), "bootstrap": "playwright_python",
         "unlocks": ["real Chromium execution"],
         "instruction": "pip install playwright && python -m playwright install chromium"},
    ],
    "api_project": [
        {"name": "API spec or base URL", "type": "api", "why": "define the endpoints to test",
         "necessity": REQUIRED, "access": "OpenAPI/Postman file or base URL", "env": "client-provided",
         "by": "client", "detect": ("api_docs_url", "target_url", "task_url"),
         "unlocks": ["contract import", "positive/negative case generation"],
         "instruction": "share the OpenAPI/Postman file or the base URL (no secret)"},
        {"name": "API credentials", "type": "credential",
         "why": "call authenticated endpoints (execution-time only)", "necessity": OPTIONAL_NEC,
         "access": "test-scope API key/token", "env": "client-provided", "by": "client", "detect": (),
         "unlocks": ["authenticated endpoint tests"],
         "instruction": "client provides a TEST-scope key; store only by env-var NAME, never in the repo"},
    ],
    "data_project": [
        {"name": "Read-only database connection", "type": "database",
         "why": "validate data safely without writes", "necessity": REQUIRED,
         "access": "read-only connection", "env": "client-provided", "by": "client", "detect": (),
         "unlocks": ["read-only data validation"],
         "instruction": "client provides a READ-ONLY connection string via env-var NAME (or a Docker DB)"},
        {"name": "Schema / access details", "type": "doc", "why": "know which tables/columns to check",
         "necessity": OPTIONAL_NEC, "access": "schema doc", "env": "client-provided", "by": "client",
         "detect": (), "unlocks": ["targeted validations"],
         "instruction": "client shares the schema or the tables in scope (no secret)"},
        {"name": "DB runtime (Docker/SQLite)", "type": "runtime",
         "why": "run a local DB for fixtures", "necessity": OPTIONAL_NEC, "access": "local",
         "env": "operator-local", "by": "operator", "detect": (), "bootstrap": "docker",
         "unlocks": ["containerized DB smoke"],
         "instruction": "install Docker Desktop / engine (optional)"},
    ],
    "code_project": [
        {"name": "Client repository / test suite", "type": "repository",
         "why": "run against the real code", "necessity": REQUIRED, "access": "repo read access",
         "env": "client-provided", "by": "client", "detect": ("repo_url",),
         "unlocks": ["framework build", "test stabilization", "real test execution"],
         "instruction": "client shares the repository (read access); clone into the private work dir only"},
        {"name": "Validation test command", "type": "command",
         "why": "prove the change with the project's own tests", "necessity": OPTIONAL_NEC,
         "access": "command string", "env": "client-provided", "by": "client", "detect": (),
         "unlocks": ["objective pass/fail validation"],
         "instruction": "client states the test command (e.g. `pytest -q`); no secret"},
        {"name": "Local runtimes (Python/Node)", "type": "runtime",
         "why": "build and run the suite", "necessity": REQUIRED, "access": "local",
         "env": "operator-local", "by": "operator", "detect": (), "bootstrap": "node",
         "unlocks": ["local build + execution"], "instruction": "install the required language runtime"},
    ],
    "automation_project": [
        {"name": "Automation target + trigger", "type": "system",
         "why": "know what the automation acts on", "necessity": REQUIRED, "access": "system access",
         "env": "client-provided", "by": "client", "detect": ("repo_url", "target_url"),
         "unlocks": ["authorized automation"],
         "instruction": "client describes the trigger + target systems and authorizes side effects"},
        {"name": "Local runtimes (Python/Node)", "type": "runtime", "why": "run the automation locally",
         "necessity": REQUIRED, "access": "local", "env": "operator-local", "by": "operator",
         "detect": (), "bootstrap": "node", "unlocks": ["local execution"],
         "instruction": "install the required language runtime"},
    ],
}


def _bootstrap_index(integrations: Optional[List[Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for it in integrations or []:
        out[getattr(it, "id", "")] = it
    return out


def _authenticated_hint(profile: str, raw_text: str, missing) -> bool:
    """Deterministically decide whether a web-app audit is a PRIVATE (authenticated) app."""
    if profile != "web_app_audit":
        return False
    t = (raw_text or "").lower()
    return any(k in t for k in ("login", "log in", "authenticated", "private", "sign in", "sign-in",
                                "behind auth", "account", "dashboard behind", "portal"))


def _client_request_for(item: ResourceItem, project_id: str) -> str:
    """A ready-to-copy client request that asks for the ACCESS/NAME only — never a secret value."""
    return (f"Hi — to proceed with {project_id} I need one thing: **{item.name}** "
            f"({item.min_access_level}). {item.why_needed}. "
            f"Please share the access/reference only — do not paste any password, token, or secret; "
            f"I will store it securely by reference. Thank you!")


def build_readiness(*, project_id: str, profile: str, raw_text: str, input_map_sources: List[Any],
                    missing, integrations: Optional[List[Any]] = None) -> Dict[str, Any]:
    """Compose the per-project Resource Readiness Checklist deterministically from existing signals."""
    boot = _bootstrap_index(integrations)
    provided_types = {getattr(s, "input_type", s.get("input_type") if isinstance(s, dict) else "")
                      for s in (input_map_sources or [])}
    authenticated = _authenticated_hint(profile, raw_text, missing)
    items: List[ResourceItem] = []

    for spec in _TEMPLATES.get(profile, []):
        necessity = spec["necessity"]
        # The authenticated test account is Required for a private app, Not Applicable for a public one.
        if necessity == "auth":
            necessity = REQUIRED if authenticated else NA_NEC

        detected = bool(set(spec.get("detect", ())) & provided_types)
        by = spec["by"]
        instruction = spec["instruction"]
        validation = "not provided"
        status = OPTIONAL if necessity == OPTIONAL_NEC else NEEDS_CLIENT
        blocker, next_action = "", ""

        if necessity == NA_NEC:
            status, by, blocker = NOT_APPLICABLE, "n/a", ""
            next_action = "nothing required for this profile"
        elif spec.get("bootstrap") and by == "operator":
            # Operator/local runtime — read the ACTUAL AccessBootstrap readiness (no invented state).
            integ = boot.get(spec["bootstrap"])
            check = getattr(integ, "check_result", "") if integ else ""
            readiness = getattr(integ, "readiness", "") if integ else ""
            validation = check or "not inspected"
            if readiness in ("Installed", "Runtime Verified", "Live Verified", "Authenticated"):
                status, next_action = VERIFIED, ""
            else:
                status = OPTIONAL if necessity == OPTIONAL_NEC else NEEDS_OPERATOR
                next_action = getattr(integ, "setup_action", "") or instruction
                if necessity == REQUIRED:
                    blocker = f"{spec['name']} not ready locally"
        elif detected:
            status = DETECTED
            validation = "referenced in intake; not yet validated"
            next_action = "validate the provided reference"
        else:
            # Not provided yet.
            if necessity == REQUIRED:
                status, blocker = NEEDS_CLIENT, f"{spec['name']} not provided"
                next_action = f"request {spec['name']} from the client"
            else:
                status = OPTIONAL
                next_action = f"optional — request {spec['name']} if in scope"

        item = ResourceItem(
            name=spec["name"], resource_type=spec["type"], why_needed=spec["why"],
            necessity=necessity, min_access_level=spec["access"], environment=spec["env"],
            status=status, provided_by=by, connection_instruction=instruction,
            validation_result=validation, capabilities_unlocked=list(spec.get("unlocks", [])),
            blocker=blocker, next_action=next_action)
        if status == NEEDS_CLIENT:
            item.client_request = _client_request_for(item, project_id)
        items.append(item)

    # Blocking missing-information (from the existing analyzer) surfaces as explicit blockers.
    blockers = [it.blocker for it in items if it.blocker] + list(getattr(missing, "blocking", []) or [])
    return {
        "schema": "resource-readiness/v1", "project_id": project_id, "profile": profile,
        "authenticated_web_app": authenticated,
        "resources": [it.to_dict() for it in items],
        "blockers": sorted(set(b for b in blockers if b)),
        "any_secret_requested": False}


def _bucket(readiness: Dict[str, Any], statuses) -> List[Dict[str, Any]]:
    return [r for r in readiness["resources"] if r["status"] in statuses]


def readiness_summary_text(readiness: Dict[str, Any]) -> str:
    """Chat-first 7-section summary (presentation only; the JSON artifact is the source of truth)."""
    pid = readiness["project_id"]
    lines = [f"# Resource Readiness — {pid}  (profile: {readiness['profile'] or 'unresolved'})", ""]

    def section(title, rows, render):
        lines.append(f"## {title}")
        if not rows:
            lines.append("- (none)")
        else:
            lines.extend(render(r) for r in rows)
        lines.append("")

    section("1. Ready now", _bucket(readiness, (VERIFIED, DETECTED, PROVIDED)),
            lambda r: f"- {r['name']} — {r['status']} ({r['validation_result']})")
    section("2. Needs Client", _bucket(readiness, (NEEDS_CLIENT,)),
            lambda r: f"- {r['name']} ({r['min_access_level']}) — {r['next_action']}")
    section("3. Needs Operator", _bucket(readiness, (NEEDS_OPERATOR, BLOCKED, INVALID)),
            lambda r: f"- {r['name']} — {r['status']}: {r['next_action']}")
    section("4. Optional", _bucket(readiness, (OPTIONAL,)),
            lambda r: f"- {r['name']} — {r['why_needed']}")
    section("5. Not required", _bucket(readiness, (NOT_APPLICABLE,)),
            lambda r: f"- {r['name']}")
    lines.append("## 6. Current blockers")
    lines.extend([f"- {b}" for b in readiness["blockers"]] or ["- (none)"])
    lines.append("")
    lines.append("## 7. Ready-to-copy client request(s) — review before sending; never sent automatically")
    reqs = [r for r in readiness["resources"] if r.get("client_request")]
    if not reqs:
        lines.append("- (no client request needed)")
    else:
        for r in reqs:
            lines.append(f"> **{r['name']}**")
            lines.append(f"> {r['client_request']}")
    lines.append("")
    lines.append("_No secret is ever requested here; access is stored by reference (env-var name) only._")
    return "\n".join(lines) + "\n"

# Phase Contracts — Guided QA Automation Workbench

**Version:** 5.2.0
**Updated:** 2026-05-25
**Phase:** 2B-AGENT

This document defines the contract for each implementation phase: inputs, outputs,
allowed actions, blocked actions, and acceptance criteria. Agents must respect these
boundaries before, during, and after each phase.

Status markers:
- `[implemented]` — built and tested in this repository
- `[planned]` — designed but not yet built

---

## Phase 1A — Identity and Documentation `[implemented]`

**Purpose:** Establish product identity, vision, and operational runbook.

**Input artifacts:** none (initial phase)

**Output artifacts:**
- `README.md`
- `docs/VISION.md`
- `docs/RUNBOOK.md`
- `docs/COMMANDS.md`
- `docs/APPROVAL_MODEL.md`
- `docs/SAFETY_RULES.md`
- `docs/TOOLING_DECISIONS.md`

**Allowed actions:**
- Create and edit documentation
- Define product direction, principles, and workflow

**Blocked actions:**
- No code execution
- No external calls
- No credentials

**Acceptance criteria:**
- README describes entry points
- VISION, RUNBOOK, COMMANDS, APPROVAL_MODEL, SAFETY_RULES, TOOLING_DECISIONS present

---

## Phase 1B — Schema Foundation `[implemented]`

**Purpose:** Define the full domain model for the workbench as pure Python dataclasses.
No runtime execution. No side effects.

**Input artifacts:** Phase 1A docs

**Output artifacts:**
- `core/schemas/` — all domain schema modules
- `tests/test_schema_foundations.py`

**Allowed actions:**
- Create Python dataclasses in `core/schemas/`
- Define `to_dict()` / `from_dict()` via `SchemaMixin`
- Write schema round-trip tests
- Update `docs/SCHEMA_FOUNDATION.md`

**Blocked actions:**
- No runtime execution
- No external calls
- No database
- No credentials
- No side effects

**Acceptance criteria:**
- All schemas have `to_dict()` / `from_dict()` round-trips
- All schema tests pass
- `docs/SCHEMA_FOUNDATION.md` accurately describes the schema layer

---

## Phase 1B-DOCS — Documentation Governance `[implemented]`

**Purpose:** Add documentation governance so docs never drift from code.

**Input artifacts:** Phase 1B schemas, Phase 1A docs

**Output artifacts:**
- `docs/DOCS_MANIFEST.md`
- `docs/DOCUMENTATION_GOVERNANCE.md`
- `tools/docs_audit.py`
- `outputs/docs_audit/DOCS_FRESHNESS_REPORT.md` (runtime, gitignored)

**Allowed actions:**
- Create docs manifest and governance rules
- Create `tools/docs_audit.py` — dependency-free, no external calls
- Run audit and write report to `outputs/`

**Blocked actions:**
- No external calls in audit tool
- No automatic doc rewriting
- No LLM calls

**Acceptance criteria:**
- `docs_audit.py` reports PASS
- All required docs exist
- DOCS_MANIFEST.md is populated

---

## Phase 2A — Input Context Resolver + Work Request Classifier `[implemented]`

**Purpose:** Classify raw inputs (URLs, files, text) into typed schema objects and write
initial project artifacts. Classify-only — no execution, no fetching.

**Input artifacts:** raw text / URLs / files from user

**Output artifacts (per project run, under `outputs/<project_id>/00_project/`):**
- `INPUT_MAP.json` / `INPUT_MAP.md`
- `WORK_REQUEST.json` / `WORK_REQUEST.md`
- `TASK_CLASSIFICATION.json` / `TASK_CLASSIFICATION.md`
- `PROJECT_STATUS.json` / `PROJECT_STATUS.md`
- `NEXT_SAFE_STEP.md`

**Runtime modules:**
- `core/input_context_resolver.py` — `InputContextResolver`
- `core/work_request_classifier.py` — `WorkRequestClassifier`
- `core/workbench_controller.py` — `WorkbenchController` (Phase 2A methods)
- `tools/classify_inputs.py` — CLI entry point

**Allowed actions:**
- Classify input strings by type (task_url, target_url, repo_url, api_docs_url, etc.)
- Redact detected secrets before storing
- Write artifacts to `outputs/<project_id>/00_project/`
- Run keyword signal detection (no LLM required)

**Blocked actions:**
- No URL fetching
- No browser execution
- No repository cloning
- No credential use
- No external API calls
- No n8n/webhook calls [planned — Phase 2+]

**Secret redaction rules (enforced):**
- Raw passwords, tokens, cookies, JWTs, API keys are replaced with `[REDACTED_*]`
- `credentials_reference` sources are blocked and approval-required
- No raw secret value is stored in any artifact

**Acceptance criteria:**
- `python tools/classify_inputs.py --input "..."` classifies correctly
- All 5 artifact types are written
- No raw secrets in any artifact
- 69+ Phase 2A tests passing

---

## Phase 2B — Project Blueprint Builder `[implemented]`

**Purpose:** Build the project planning source-of-truth from Phase 2A context.
Planning-only — no execution, no scaffolding.

**Input artifacts:**
- `INPUT_MAP.json` (Phase 2A)
- `WORK_REQUEST.json` (Phase 2A)
- `TASK_CLASSIFICATION.json` (Phase 2A)

**Output artifacts (under `outputs/<project_id>/00_project/`):**
- `PROJECT_BLUEPRINT.json` / `PROJECT_BLUEPRINT.md`
- `ASSUMPTIONS.md`
- `MISSING_INFO.md`
- `SAFE_NEXT_STEPS.md`
- `BLOCKED_ACTIONS.md`
- `INITIAL_QA_STRATEGY_OUTLINE.md`

**Runtime modules:**
- `core/project_blueprint_builder.py` — `ProjectBlueprintBuilder`
- `core/workbench_controller.py` — Phase 2B methods
- `tools/classify_inputs.py --with-blueprint` — CLI entry point

**Allowed actions:**
- Infer project type from text signals (8 types)
- Infer environment from text signals (5 types)
- Build assumptions, missing info, safe next steps, blocked actions lists
- Write all 7 artifact files to `outputs/<project_id>/00_project/`
- Redact secrets in all artifacts

**Blocked actions:**
- No URL fetching
- No browser execution
- No Playwright scaffold generation
- No credential use
- No external calls
- No executable test generation
- No n8n/webhook calls [planned — Phase 2+]

**Acceptance criteria:**
- `python tools/classify_inputs.py --input "..." --with-blueprint` writes 16 artifacts
- No raw secrets in any artifact
- `credentials_reference` sources blocked and noted in blueprint
- 82+ Phase 2B tests passing

---

## Phase 2B-AGENT — Agent Operating Contract `[implemented]`

**Purpose:** Define the agent operating contract, phase contracts, artifact contracts,
and handoff template. Create an agent readiness audit tool.
Documentation and tooling only — no runtime changes.

**Input artifacts:** all Phase 2B docs and code

**Output artifacts:**
- `docs/AGENT_CONTRACT.md`
- `docs/PHASE_CONTRACTS.md` ← this file
- `docs/ARTIFACT_CONTRACTS.md`
- `docs/AGENT_HANDOFF_TEMPLATE.md`
- `tools/agent_readiness_audit.py`
- `tests/test_agent_readiness.py`

**Allowed actions:**
- Create agent contract and phase contract docs
- Create artifact contract doc
- Create handoff report template
- Create `tools/agent_readiness_audit.py` — dependency-free, no external calls
- Write tests that verify docs and audit tool exist and pass
- Update DOCS_MANIFEST, DOCUMENTATION_GOVERNANCE, COMMANDS, RUNBOOK, TOOLING_DECISIONS

**Blocked actions:**
- No new runtime modules
- No schema changes
- No autonomous agent runtime
- No external calls
- No credentials

**Acceptance criteria:**
- All four agent contract docs created
- `agent_readiness_audit.py` reports PASS
- All tests pass
- docs_audit passes

---

## Phase 2C — Strategy Planner + Tactical Planning Foundation `[planned]`

**Purpose:** Build QA strategy and tactical test plan from `ProjectBlueprint`.
Planning-only — no execution, no scaffolding.

**Input artifacts:**
- `PROJECT_BLUEPRINT.json` (Phase 2B)
- Optional: `api_docs_file` sources from `INPUT_MAP.json`

**Planned output artifacts:**
- `QA_STRATEGY.json` / `QA_STRATEGY.md`
- `RISK_MATRIX.md`
- `TEST_SCOPE.md`
- `TACTICAL_TEST_PLAN.md` (Phase 2C+)

**Allowed actions (planned):**
- Build QA strategy from blueprint (classify-only, no execution)
- Generate risk matrix from project type and risk signals
- Define test scope from surfaces and blocked actions
- Write artifacts to `outputs/<project_id>/02_strategy/`

**Blocked actions (permanent):**
- No URL fetching
- No browser execution
- No credential use
- No external calls
- No Playwright scaffold (Phase 3A)

---

## Phase 3A — Framework Scaffold Generation `[planned]`

**Purpose:** Generate a Playwright TypeScript framework from the strategy.
Scaffold-only — no execution against live URLs.

**Input artifacts:**
- `QA_STRATEGY.json` (Phase 2C)
- `PROJECT_BLUEPRINT.json` (Phase 2B)

**Planned output artifacts (under `outputs/<project_id>/03_framework/`):**
- `package.json`, `tsconfig.json`, `playwright.config.ts`
- `specs/smoke.spec.ts`, `specs/auth.spec.ts` (per type)
- `CI workflow`

**Allowed actions (planned):**
- Generate scaffold files (local writes only, no execution)
- Run TypeScript compile check (`npx tsc --noEmit`) — safe local validation
- Run Playwright dry-run (`npx playwright test --dry-run`) — no browser, no network

**Blocked actions:**
- No execution against any URL (requires Phase 4A approval)
- No credential use
- No external calls

---

## Phase 3B — Safe Local Validation `[planned]`

**Purpose:** Validate generated scaffold locally without any external execution.

**Input artifacts:** Phase 3A framework output

**Actions:**
- TypeScript compile
- Playwright dry-run
- Lint
- No network calls

---

## Phase 4A — Evidence and Reporting `[planned]`

**Purpose:** Run approved tests, collect evidence, produce internal summary.
Requires explicit approval checklist per run.

**Required approvals before execution:**
- Target URL approval
- Environment confirmation (staging, not production)
- Synthetic test accounts confirmed
- Approval checklist completed (`RUNBOOK.md` section 4)
- `--approve` flag passed with awareness

**Output artifacts (under `outputs/<project_id>/04_execution/` and `05_evidence/`):**
- Test results (Playwright HTML report, JSONL)
- Screenshots, traces
- `EVIDENCE.md`

**Blocked actions (permanent):**
- No production execution without explicit read-only written approval
- No payment flows without sandbox written confirmation
- No credential use without test account approval
- No destructive actions

---

## Phase 5A — Approval-Gated External/Auth/Mobile/Integration Adapters `[planned]`

**Purpose:** Add execution adapters for auth flows, mobile platforms, and optional
integrations. Each adapter is gated by an explicit per-run approval.

This phase does not exist yet. When it is designed, it must:
- Define per-adapter approval gates
- Document risk levels for each adapter
- Add explicit test accounts confirmation
- Add mobile platform confirmation and device/emulator setup
- Keep `IntegrationPolicy.allow_outbound_events=False` as default

---

## Cross-Phase Rules (all phases)

These rules apply in every phase, without exception:

1. `outputs/` is always gitignored — never staged, never committed
2. Secrets are redacted before storage in any field or artifact
3. `core/orchestrator.py` is never replaced without explicit architecture approval
4. Docs are updated alongside code changes (same commit)
5. Every phase ends with: `pytest -q` + `docs_audit` + `agent_readiness_audit` all passing
6. Execution phases require the `RUNBOOK.md` section 4 checklist completed per run

---

## Related Documents

- [`AGENT_CONTRACT.md`](AGENT_CONTRACT.md) — agent operating rules
- [`ARTIFACT_CONTRACTS.md`](ARTIFACT_CONTRACTS.md) — artifact paths and ownership
- [`AGENT_HANDOFF_TEMPLATE.md`](AGENT_HANDOFF_TEMPLATE.md) — final report template
- [`SAFETY_RULES.md`](SAFETY_RULES.md) — non-negotiable safety rules
- [`COMMANDS.md`](COMMANDS.md) — CLI reference

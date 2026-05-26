# Documentation Manifest — Guided QA Automation Workbench

**Version:** 5.7.0  
**Updated:** 2026-05-25  
**Phase:** 4ABC

This file is the registry of all documentation tracked by the workbench.  
Run `python tools/docs_audit.py` to verify that these docs are current.

---

## Source-of-truth documentation

These docs define the canonical behavior, rules, and structure of the workbench.

| Path | Purpose | Source of Truth | Update Triggers | Status | Notes |
|---|---|---|---|---|---|
| `README.md` | Public overview, entry point, quickstart | Yes | version_changed, phase_completed, command_added | current | High-level only; does not describe schema internals |
| `docs/VISION.md` | Product direction, guiding principles, identity | Yes | phase_completed, workflow_changed | current | Updated in Phase 1A for Workbench identity |
| `docs/RUNBOOK.md` | Day-to-day operational workflow | Yes | command_added, workflow_changed, phase_completed | current | Sections 1–12 + docs freshness section (Phase 1B-DOCS) |
| `docs/COMMANDS.md` | CLI command reference — all implemented and planned | Yes | command_added, command_removed, workflow_changed | current | Planned commands marked `[planned]`; implemented marked `[implemented]` |
| `docs/APPROVAL_MODEL.md` | Approval/risk model, risk level definitions | Yes | approval_model_changed, safety_rule_changed, auth_changed | current | Credential approval gates added in Phase 1B addendum |
| `docs/SAFETY_RULES.md` | Non-negotiable safety rules (Rules 1–10 + auth + integration) | Yes | safety_rule_changed, auth_changed, integration_added | current | Credential, auth, integration safety sections added in Phase 1B addendum |
| `docs/TOOLING_DECISIONS.md` | Tooling choices, optional adapters, what is NOT added | Yes | tool_added, integration_added, workflow_changed | current | n8n integration model section added in Phase 1B addendum |
| `docs/SCHEMA_FOUNDATION.md` | `core/schemas/` layer — classes, defaults, patterns | Yes | schema_changed, phase_completed | current | Auth, mobile, integration sections added; documentation.py added in Phase 1B-DOCS |
| `docs/DOCUMENTATION_GOVERNANCE.md` | Docs maintenance rules, governance, audit process | Yes | phase_completed, schema_changed, command_added, agent_behavior_changed | current | Agent contract update trigger added in Phase 2B-AGENT |
| `docs/DOCS_MANIFEST.md` | Registry of all documentation files and status | Yes | phase_completed, command_added, schema_changed | current | This file — created in Phase 1B-DOCS |
| `docs/AGENT_CONTRACT.md` | Agent operating contract — allowed/forbidden actions, report format | Yes | safety_rule_changed, phase_completed, workflow_changed, agent_behavior_changed | current | Created in Phase 2B-AGENT |
| `docs/PHASE_CONTRACTS.md` | Phase-by-phase contracts — inputs, outputs, blocked actions, acceptance criteria | Yes | phase_completed, phase_added, workflow_changed | current | Created in Phase 2B-AGENT |
| `docs/ARTIFACT_CONTRACTS.md` | Stable artifact paths, formats, and ownership rules | Yes | artifact_path_changed, phase_completed, workflow_changed | current | Created in Phase 2B-AGENT |
| `docs/AGENT_HANDOFF_TEMPLATE.md` | Reusable final report template for agent phase handoffs | No | phase_completed, report_format_changed | current | Created in Phase 2B-AGENT |
| `docs/CLIENT_SCENARIO_FIXTURES.md` | Practical client scenario fixtures — categories, safe usage, blocked actions | Yes | phase_completed, scenario_added, safety_rule_changed | current | Created in Phase 3B-SCENARIOS |

---

## Operational guides

These support day-to-day work. They should stay current but are secondary to source-of-truth docs.

| Path | Purpose | Source of Truth | Update Triggers | Status | Notes |
|---|---|---|---|---|---|
| `docs/PROJECT_TYPES.md` | Project type taxonomy and recommended QA approaches | No | workflow_changed, phase_completed | current | Stable taxonomy — update when new project types are added |
| `docs/CAPABILITY_MATRIX.md` | What project/opportunity types are supported | No | command_added, workflow_changed | needs_review | May not reflect all Phase 1B schema additions |
| `docs/REAL_TESTING_PREPARATION.md` | Pre-execution checklist for real-mode test runs | No | safety_rule_changed, approval_model_changed | current | Linked from RUNBOOK.md section 4 |
| `docs/MODEL_ROUTING_PROFILES.md` | LLM routing profiles and fallback behavior | No | ai_resilience_changed, tool_added | current | Stable; update when model profiles change |
| `docs/VSCODE_USAGE.md` | IDE setup guidance for VS Code + Claude Code | No | tool_added | current | Extension-specific; update when tooling changes |

---

## Tool / integration guides

These explain optional tools. All optional tools must be described as optional.

| Path | Purpose | Source of Truth | Update Triggers | Status | Notes |
|---|---|---|---|---|---|
| `docs/PLAYWRIGHT_MCP_GUIDE.md` | Playwright MCP integration reference | No | integration_added | current | Optional helper — not a required runtime dependency |
| `docs/LANGGRAPH_V5_NOTE.md` | LangGraph migration notes from v5.0.x | No | workflow_changed | current | Historical note; LangGraph is optional future |

---

## Legacy / archive docs

These are historical or superseded. Do not use as authoritative references.

| Path | Purpose | Status | Notes |
|---|---|---|---|
| `docs/archive/` | Archived older versions | deprecated | Not loaded by default |
| `docs/AI_QA_Factory_Concept_and_Implementation_Plan_v7_validation_hardened.md` | Early concept doc | stale | Superseded by VISION.md + RUNBOOK.md |
| `docs/V507_CODE_DOC_SYNC_NOTES.md` | v5.0.7 sync notes | stale | Historical reference only |
| `docs/V508_MODEL_ROUTING_NOTES.md` | v5.0.8 routing notes | stale | Historical reference only |
| `docs/REPO_STRATEGIC_READINESS_AUDIT_v1.md` | Early strategic audit | stale | Historical reference only |
| `docs/GLOBAL_AUDIT_AND_REAL_TESTING_READINESS.md` | Early readiness audit | stale | Historical reference only |
| `docs/DEMO_SITE_TESTING_REPORT_v1.md` | Demo site test report | stale | Generated artifact, not a governance doc |
| `docs/VALIDATION_WEBSITE_TESTING_REPORT.md` | Validation run report | stale | Generated artifact, not a governance doc |

---

## Generated output docs

Produced during workbench runs. Not source of truth. Not committed by default.

| Path pattern | Purpose | Source of Truth | Status |
|---|---|---|---|
| `outputs/*/DECISION.md` | Pre-screening decision | No | generated — do not edit |
| `outputs/*/READ_ME_FIRST.md` | Run summary | No | generated — do not edit |
| `outputs/*/HUMAN_REVIEW_REQUIRED.md` | Manual review checklist | No | generated — complete before delivery |
| `outputs/*/QUALITY_GATE_REPORT.md` | Quality gate results | No | generated — internal only |
| `outputs/docs_audit/DOCS_FRESHNESS_REPORT.md` | Docs audit output | No | generated by `python tools/docs_audit.py` |
| `outputs/docs_audit/docs_freshness_report.json` | Docs audit JSON | No | generated by `python tools/docs_audit.py` |
| `outputs/<id>/00_project/INPUT_MAP.json/.md` | Classified inputs for a project | No | generated by `python tools/classify_inputs.py` (Phase 2A) |
| `outputs/<id>/00_project/WORK_REQUEST.json/.md` | Normalised work request | No | generated by `python tools/classify_inputs.py` (Phase 2A) |
| `outputs/<id>/00_project/TASK_CLASSIFICATION.json/.md` | Task + project type classification | No | generated by `python tools/classify_inputs.py` (Phase 2A) |
| `outputs/<id>/00_project/PROJECT_STATUS.json/.md` | Current project phase and status | No | generated by `python tools/classify_inputs.py` (Phase 2A) |
| `outputs/<id>/00_project/NEXT_SAFE_STEP.md` | Human-readable next action guidance | No | generated by `python tools/classify_inputs.py` (Phase 2A) |
| `outputs/<id>/00_project/PROJECT_BLUEPRINT.json/.md` | Planning source-of-truth | No | generated by `python tools/classify_inputs.py --with-blueprint` (Phase 2B) |
| `outputs/<id>/00_project/ASSUMPTIONS.md` | Working assumptions for client confirmation | No | generated by `python tools/classify_inputs.py --with-blueprint` (Phase 2B) |
| `outputs/<id>/00_project/MISSING_INFO.md` | Information needed before execution | No | generated by `python tools/classify_inputs.py --with-blueprint` (Phase 2B) |
| `outputs/<id>/00_project/SAFE_NEXT_STEPS.md` | Planning-only actions safe to proceed | No | generated by `python tools/classify_inputs.py --with-blueprint` (Phase 2B) |
| `outputs/<id>/00_project/BLOCKED_ACTIONS.md` | Actions blocked until approvals obtained | No | generated by `python tools/classify_inputs.py --with-blueprint` (Phase 2B) |
| `outputs/<id>/00_project/INITIAL_QA_STRATEGY_OUTLINE.md` | Preliminary test layer guidance | No | generated by `python tools/classify_inputs.py --with-blueprint` (Phase 2B) |
| `outputs/<id>/02_strategy/QA_STRATEGY.json` | Full `QAStrategy` schema — areas, risk matrix, test layers, tactical plan, decisions | No | generated by `python tools/build_strategy.py` or `--with-strategy` (Phase 2C) |
| `outputs/<id>/02_strategy/QA_STRATEGY.md` | Strategy summary, project type, confidence, blocked actions | No | generated by `python tools/build_strategy.py` or `--with-strategy` (Phase 2C) |
| `outputs/<id>/02_strategy/TEST_SCOPE.md` | In-scope and out-of-scope areas, blocked areas, surfaces | No | generated by `python tools/build_strategy.py` or `--with-strategy` (Phase 2C) |
| `outputs/<id>/02_strategy/RISK_MATRIX.md` | Risk items with likelihood, impact, severity, mitigation | No | generated by `python tools/build_strategy.py` or `--with-strategy` (Phase 2C) |
| `outputs/<id>/02_strategy/TEST_LAYERS.md` | Recommended test layers with purpose, priority, examples | No | generated by `python tools/build_strategy.py` or `--with-strategy` (Phase 2C) |
| `outputs/<id>/02_strategy/TACTICAL_PLAN_OUTLINE.md` | Phase-ordered tactical planning sequence | No | generated by `python tools/build_strategy.py` or `--with-strategy` (Phase 2C) |
| `outputs/<id>/02_strategy/QUALITY_RUBRIC.md` | Quality criteria for this project type | No | generated by `python tools/build_strategy.py` or `--with-strategy` (Phase 2C) |
| `outputs/<id>/02_strategy/STRATEGY_DECISIONS.md` | Key strategy decisions with rationale and alternatives | No | generated by `python tools/build_strategy.py` or `--with-strategy` (Phase 2C) |
| `outputs/<id>/02_strategy/UPDATED_PROJECT_STATUS.json` | Updated project status reflecting strategy phase | No | generated by `python tools/build_strategy.py` or `--with-strategy` (Phase 2C) |
| `outputs/<id>/02_strategy/UPDATED_PROJECT_STATUS.md` | Human-readable updated project status | No | generated by `python tools/build_strategy.py` or `--with-strategy` (Phase 2C) |
| `outputs/<id>/03_framework/playwright/FRAMEWORK_SCAFFOLD.json` | Full `FrameworkScaffold` schema — files, status, safety flags | No | generated by `python tools/generate_scaffold.py` (Phase 3A) |
| `outputs/<id>/03_framework/playwright/FRAMEWORK_SCAFFOLD.md` | Human-readable scaffold summary | No | generated by `python tools/generate_scaffold.py` (Phase 3A) |
| `outputs/<id>/03_framework/playwright/package.json` | Node.js project definition with Playwright scripts | No | generated by `python tools/generate_scaffold.py` (Phase 3A) |
| `outputs/<id>/03_framework/playwright/tsconfig.json` | TypeScript compiler configuration | No | generated by `python tools/generate_scaffold.py` (Phase 3A) |
| `outputs/<id>/03_framework/playwright/playwright.config.ts` | Playwright test runner config — reads `BASE_URL` from env | No | generated by `python tools/generate_scaffold.py` (Phase 3A) |
| `outputs/<id>/03_framework/playwright/tests/smoke/smoke.spec.ts` | Smoke test placeholder | No | generated by `python tools/generate_scaffold.py` (Phase 3A) |
| `outputs/<id>/03_framework/playwright/tests/auth/auth-placeholder.spec.ts` | Auth flow placeholder — skipped until credentials approved | No | generated by `python tools/generate_scaffold.py` (Phase 3A) — conditional on project type |
| `outputs/<id>/03_framework/playwright/tests/api/api-placeholder.spec.ts` | API test placeholder — skipped until API_BASE_URL approved | No | generated by `python tools/generate_scaffold.py` (Phase 3A) — conditional on project type |
| `outputs/<id>/03_framework/playwright/pages/BasePage.ts` | Base page object template | No | generated by `python tools/generate_scaffold.py` (Phase 3A) |
| `outputs/<id>/03_framework/playwright/docs/SCAFFOLD_REVIEW_CHECKLIST.md` | Pre-execution safety checklist — must be completed before any test run | No | generated by `python tools/generate_scaffold.py` (Phase 3A) |
| `outputs/<id>/03_framework/playwright/STATIC_VALIDATION_REPORT.json` | Full `ScaffoldValidationReport` schema — checks, blockers, safety flags | No | generated by `python tools/validate_scaffold.py` (Phase 3B) |
| `outputs/<id>/03_framework/playwright/STATIC_VALIDATION_REPORT.md` | Human-readable validation report with safety invariants section | No | generated by `python tools/validate_scaffold.py` (Phase 3B) |
| `outputs/<id>/03_framework/playwright/VALIDATION_PLAN.md` | What static checks ran and what toolchain steps require approval | No | generated by `python tools/validate_scaffold.py` (Phase 3B) |
| `outputs/<id>/03_framework/playwright/LOCAL_VALIDATION_CHECKLIST.md` | Manual checklist of steps to complete before running any local command | No | generated by `python tools/validate_scaffold.py` (Phase 3B) |
| `outputs/<id>/03_framework/playwright/TOOLCHAIN_VALIDATION_PLAN.md` | Proposed toolchain commands (npm install etc.) requiring explicit approval | No | generated by `python tools/validate_scaffold.py` (Phase 3B) |
| `outputs/<id>/03_framework/playwright/TOOLCHAIN_VALIDATION_REPORT.json` | Full `ToolchainValidationReport` schema — commands, safety invariants | No | generated by `python tools/validate_toolchain.py` (Phase 3C) |
| `outputs/<id>/03_framework/playwright/TOOLCHAIN_VALIDATION_REPORT.md` | Human-readable toolchain report with safety invariants and next steps | No | generated by `python tools/validate_toolchain.py` (Phase 3C) |
| `outputs/<id>/03_framework/playwright/TOOLCHAIN_COMMAND_LOG.md` | Per-command stdout/stderr excerpts — no secrets reproduced | No | generated by `python tools/validate_toolchain.py` (Phase 3C) |
| `outputs/<id>/03_framework/playwright/TOOLCHAIN_APPROVAL_RECORD.md` | Approval state, allowed/denied commands, safety constraints | No | generated by `python tools/validate_toolchain.py` (Phase 3C) |
| `outputs/<id>/04_execution_plan/EXECUTION_APPROVAL_CHECKLIST.json` | `ExecutionApprovalChecklist` schema — approval requirements for execution | No | generated by `python tools/plan_execution.py` (Phase 4A) |
| `outputs/<id>/04_execution_plan/EXECUTION_APPROVAL_CHECKLIST.md` | Human-readable checklist — all `approved_for_*` flags False | No | generated by `python tools/plan_execution.py` (Phase 4A) |
| `outputs/<id>/04_execution_plan/EXECUTION_READINESS_REPORT.json` | `ExecutionReadinessReport` schema — blockers, warnings, required approvals | No | generated by `python tools/plan_execution.py` (Phase 4A) |
| `outputs/<id>/04_execution_plan/EXECUTION_READINESS_REPORT.md` | Human-readable readiness report | No | generated by `python tools/plan_execution.py` (Phase 4A) |
| `outputs/<id>/04_execution_plan/EVIDENCE_COLLECTION_PLAN.md` | Plan for future evidence collection after approved execution | No | generated by `python tools/plan_execution.py` (Phase 4A) |
| `outputs/<id>/04_execution_plan/EXECUTION_BOUNDARIES.md` | What has/has not been done, what requires approval | No | generated by `python tools/plan_execution.py` (Phase 4A) |
| `outputs/<id>/05_evidence/EVIDENCE_MANIFEST.json` | `EvidenceCollection` schema — registry of internal evidence records | No | generated by `python tools/build_evidence_foundation.py` (Phase 4B) |
| `outputs/<id>/05_evidence/EVIDENCE_MANIFEST.md` | Human-readable evidence registry | No | generated by `python tools/build_evidence_foundation.py` (Phase 4B) |
| `outputs/<id>/05_evidence/EVIDENCE_QUALITY_GATE.json` | `EvidenceQualityGate` schema — gate before client review | No | generated by `python tools/build_evidence_foundation.py` (Phase 4B) |
| `outputs/<id>/05_evidence/EVIDENCE_QUALITY_GATE.md` | Human-readable quality gate (approved_for_client_view=False) | No | generated by `python tools/build_evidence_foundation.py` (Phase 4B) |
| `outputs/<id>/05_evidence/EVIDENCE_REDACTION_REPORT.json` | `EvidenceRedactionReport` schema — redaction status | No | generated by `python tools/build_evidence_foundation.py` (Phase 4B) |
| `outputs/<id>/05_evidence/EVIDENCE_REDACTION_REPORT.md` | Human-readable redaction report | No | generated by `python tools/build_evidence_foundation.py` (Phase 4B) |
| `outputs/<id>/05_evidence/INTERNAL_EVIDENCE_SUMMARY.md` | Internal evidence summary — not for client delivery | No | generated by `python tools/build_evidence_foundation.py` (Phase 4B) |
| `outputs/<id>/06_client_draft/INTERNAL_QA_SUMMARY_DRAFT.json` | `ReportDraft` schema — internal QA summary (draft) | No | generated by `python tools/build_report_drafts.py` (Phase 4C) |
| `outputs/<id>/06_client_draft/INTERNAL_QA_SUMMARY_DRAFT.md` | Internal QA summary draft — not for client delivery | No | generated by `python tools/build_report_drafts.py` (Phase 4C) |
| `outputs/<id>/06_client_draft/CLIENT_REPORT_DRAFT.json` | `ReportDraft` schema — client report (DRAFT, not approved) | No | generated by `python tools/build_report_drafts.py` (Phase 4C) |
| `outputs/<id>/06_client_draft/CLIENT_REPORT_DRAFT.md` | Client report draft — DRAFT, not approved for delivery | No | generated by `python tools/build_report_drafts.py` (Phase 4C) |
| `outputs/<id>/06_client_draft/DELIVERY_NOTE_DRAFT.json` | `DeliveryNoteDraft` schema — delivery note (draft) | No | generated by `python tools/build_report_drafts.py` (Phase 4C) |
| `outputs/<id>/06_client_draft/DELIVERY_NOTE_DRAFT.md` | Delivery note draft — not approved for delivery | No | generated by `python tools/build_report_drafts.py` (Phase 4C) |
| `outputs/<id>/06_client_draft/REPORT_QUALITY_CHECKLIST.json` | `ReportQualityChecklist` schema — safe_to_deliver=False | No | generated by `python tools/build_report_drafts.py` (Phase 4C) |
| `outputs/<id>/06_client_draft/REPORT_QUALITY_CHECKLIST.md` | Human-readable quality checklist for reports | No | generated by `python tools/build_report_drafts.py` (Phase 4C) |
| `outputs/<id>/06_client_draft/DELIVERY_PACKAGE_PREVIEW.json` | `DeliveryPackagePreview` schema — preview only, no package created | No | generated by `python tools/build_delivery_preview.py` (Phase 4C) |
| `outputs/<id>/06_client_draft/DELIVERY_PACKAGE_PREVIEW.md` | Human-readable preview manifest (preview only) | No | generated by `python tools/build_delivery_preview.py` (Phase 4C) |
| `outputs/<id>/06_client_draft/DELIVERY_SAFETY_CHECKLIST.json` | `DeliverySafetyChecklist` schema — safe_to_package=False | No | generated by `python tools/build_delivery_preview.py` (Phase 4C) |
| `outputs/<id>/06_client_draft/DELIVERY_SAFETY_CHECKLIST.md` | Human-readable delivery safety checklist | No | generated by `python tools/build_delivery_preview.py` (Phase 4C) |
| `outputs/<id>/99_internal/scenario_evaluation/SCENARIO_BATCH_EVALUATION.json` | `ScenarioBatchEvaluationReport` schema — local fixture evaluation | No | generated by `python tools/evaluate_scenarios.py` (Phase 4ABC) |
| `outputs/<id>/99_internal/scenario_evaluation/SCENARIO_BATCH_EVALUATION.md` | Human-readable scenario evaluation — internal only | No | generated by `python tools/evaluate_scenarios.py` (Phase 4ABC) |

---

## Phase 4D — Controlled Browser Execution artifacts

| Artifact | Schema / Description | Committed? | Owner |
|---|---|---|---|
| `outputs/<id>/07_execution/BROWSER_EXECUTION_APPROVAL.json` | `BrowserExecutionApproval` schema — approval record for session | No | generated by `python tools/run_demo_execution.py` (Phase 4D) |
| `outputs/<id>/07_execution/BROWSER_EXECUTION_APPROVAL.md` | Human-readable approval record | No | generated by `python tools/run_demo_execution.py` (Phase 4D) |
| `outputs/<id>/07_execution/BROWSER_EXECUTION_REPORT.json` | `BrowserExecutionReport` schema — full execution report | No | generated by `python tools/run_demo_execution.py` (Phase 4D) |
| `outputs/<id>/07_execution/BROWSER_EXECUTION_REPORT.md` | Human-readable execution report (internal-only) | No | generated by `python tools/run_demo_execution.py` (Phase 4D) |
| `outputs/<id>/07_execution/BROWSER_COMMAND_LOG.md` | Command execution log with stdout/stderr excerpts | No | generated by `python tools/run_demo_execution.py` (Phase 4D) |
| `outputs/<id>/07_execution/BROWSER_EVIDENCE_MANIFEST.json` | Evidence path references (all internal-only) | No | generated by `python tools/run_demo_execution.py` (Phase 4D) |
| `outputs/<id>/07_execution/BROWSER_EVIDENCE_MANIFEST.md` | Human-readable evidence manifest | No | generated by `python tools/run_demo_execution.py` (Phase 4D) |

---

## Foundation-only features — not yet runtime

These features have schema foundations in `core/schemas/` but no runtime implementation yet.  
Any doc describing them must include a qualifier: `schema-only`, `foundation-only`, `planned`, or `[planned]`.

| Feature | Schema module | Runtime phase | Notes |
|---|---|---|---|
| Credential use + auth execution (foundation-only) | `credentials.py`, `auth_flow.py` | Phase 2+ | Schema defaults block all credential use; no runtime auth execution yet |
| Mobile/native test execution | `mobile_testing.py` | Phase 3+ | Playwright mobile web emulation may be earlier |
| n8n / external integration calls | `integration.py` | Phase 2+ | All outbound events disabled by default |
| Cleanup apply / file deletion (foundation-only; dry-run only) | `cleanup.py` | Phase 2+ | `dry_run=True` by default; no deletion without explicit approval |
| Redaction pass (live) | `redaction.py` | Phase 2+ | Schema describes redaction rules only |
| Documentation governance runtime | `documentation.py` | Phase 2+ | `docs_audit.py` is the current lightweight implementation |
| State integration with schemas | `core/state.py` TODO | Phase 2 | QAFactoryState wiring deferred |
| QA Strategy (full execution) — Phase 4A+ | `qa_strategy.py` | Phase 4A+ | Phase 2C builds planning strategy; Phase 3A generates scaffold; execution is Phase 4A+ |
| Framework Scaffold (execution) | `framework_scaffold.py` | Phase 3B+ | Phase 3A generates the scaffold files; TypeScript compilation and test execution require Phase 3B+ approval |

---

## How to use this manifest

1. **Before starting a phase:** review the Status column. Update stale/needs_review entries first.
2. **After completing a phase:** update the Status column to reflect new state.
3. **When adding a new doc:** add a row here. Set status to `current` only if content is accurate now.
4. **When a doc becomes stale:** change its status to `needs_review` or `stale` and add a note.
5. **When a doc is superseded:** move to the legacy section, set status to `deprecated`.

### Phase 4E — Credential Safety artifacts (`outputs/<id>/08_credentials/`)

| Artifact | Format | Owner | Notes |
|---|---|---|---|
| `CREDENTIAL_POLICY.json` | JSON | system | Credential safety policy — internal-only |
| `CREDENTIAL_POLICY.md` | MD | system | Human-readable policy |
| `CREDENTIAL_SAFETY_REPORT.json` | JSON | system | Full inspection report — internal-only |
| `CREDENTIAL_SAFETY_REPORT.md` | MD | system | Human-readable report |
| `STORAGE_STATE_POLICY.json` | JSON | system | storageState handling policy |
| `STORAGE_STATE_POLICY.md` | MD | system | Human-readable storageState policy |
| `AUTH_EXECUTION_APPROVAL_DRAFT.json` | JSON | system | Draft auth approval — not an active approval |
| `AUTH_EXECUTION_APPROVAL_DRAFT.md` | MD | system | Human-readable draft |
| `SANDBOX_PROFILE_CLASSIFICATION.json` | JSON | system | Sandbox/account classifications |
| `SANDBOX_PROFILE_CLASSIFICATION.md` | MD | system | Human-readable classification |
| `CREDENTIAL_REDACTION_CHECKLIST.md` | MD | human | Checklist before any client-visible delivery |

All Phase 4E artifacts: `internal_only=True`, `client_visible=False`. Human redaction review required before delivery.

### Phase 4F — Auth Execution artifacts (`outputs/<id>/09_auth/`)

| Artifact | Type | Owner | Description |
|---|---|---|---|
| `AUTH_EXECUTION_APPROVAL.json` | JSON | system | Approval record for demo auth execution |
| `AUTH_EXECUTION_APPROVAL.md` | MD | system | Human-readable approval |
| `AUTH_EXECUTION_REPORT.json` | JSON | system | Full auth execution report |
| `AUTH_EXECUTION_REPORT.md` | MD | system | Human-readable report |
| `AUTH_COMMAND_LOG.md` | MD | system | Command log (credentials masked) |
| `AUTH_SESSION_ARTIFACTS.json` | JSON | system | Session artifact references |
| `AUTH_SESSION_ARTIFACTS.md` | MD | system | Human-readable artifact list |
| `AUTH_REDACTION_CHECKLIST.md` | MD | human | Checklist before any client-visible use |
| `.auth/storageState.json` | JSON | system | Optional — storageState (gitignored) |

All Phase 4F artifacts: `internal_only=True`, `client_visible=False`. storageState `approved_for_commit=False` always.

### Phase 4G — Scenario Execution Matrix artifacts (`outputs/<id>/10_execution_matrix/`)

| Artifact | Type | Owner | Description |
|---|---|---|---|
| `SCENARIO_EXECUTION_MATRIX.json` | JSON | system | Full matrix report (lanes, rules, profiles) |
| `SCENARIO_EXECUTION_MATRIX.md` | MD | system | Human-readable matrix report |
| `EXECUTION_LANES.md` | MD | system | All 9 canonical execution lanes |
| `PERMISSION_ROUTING_TABLE.md` | MD | system | Permission routing rules |
| `TARGET_PROFILE_RULES.md` | MD | system | Target profiles and routing rules |
| `BLOCKED_SCENARIOS.md` | MD | system | All strictly-blocked scenario patterns |
| `FUTURE_SCENARIOS.md` | MD | system | Planned future execution lanes |
| `CREDENTIAL_PROVISIONING_ROUTES.md` | MD | system | Credential provisioning route options |
| `DEDICATED_TEST_ACCOUNT_PLAN.json` | JSON | system | Test account plan |
| `DEDICATED_TEST_ACCOUNT_PLAN.md` | MD | system | Human-readable test account plan |

All Phase 4G artifacts: `internal_only=True`, `client_visible=False`. Planning documents only — `safe_for_execution_now=False` always.

### Phase 5AB — Runtime Secret Routing + Dedicated Auth artifacts

**`outputs/<id>/11_runtime_secrets/`** — intake validation and routing plan:

| Artifact | Type | Owner | Description |
|---|---|---|---|
| `TEST_ACCOUNT_INTAKE_VALIDATION.json` | JSON | system | `TestAccountValidationResult` schema |
| `RUNTIME_SECRET_ROUTING_PLAN.md` | MD | system | Routing plan with accepted/rejected secret references |

**`outputs/<id>/12_dedicated_auth/`** — execution artifacts:

| Artifact | Type | Owner | Description |
|---|---|---|---|
| `DEDICATED_AUTH_EXECUTION_REPORT.json` | JSON | system | `DedicatedAuthExecutionReport` schema |
| `DEDICATED_AUTH_EXECUTION_REPORT.md` | MD | system | Human-readable execution report |
| `DEDICATED_AUTH_COMMAND_LOG.md` | MD | system | Per-command stdout/stderr excerpts (secrets masked) |
| `DEDICATED_AUTH_SESSION_ARTIFACTS.json` | JSON | system | `DedicatedAuthSessionArtifact` list |
| `DEDICATED_AUTH_SESSION_ARTIFACTS.md` | MD | system | Human-readable session artifact registry |
| `DEDICATED_AUTH_SAFETY_BOUNDARY.md` | MD | system | Safety invariants and what was/was not done |
| `.auth/storageState.json` | JSON | system | Optional storageState (gitignored, internal-only, never committed) |

All Phase 5AB artifacts: `internal_only=True`, `client_visible=False`, `approved_for_commit=False`, `safe_to_deliver=False` always.

### `13_api_auth/` (Phase 5E — implemented)

| Filename | Format | Owner | Purpose |
|---|---|---|---|
| `API_AUTH_EXECUTION_REPORT.json` | JSON | system | `APIAuthExecutionReport` schema |
| `API_AUTH_EXECUTION_REPORT.md` | MD | system | Human-readable execution report |

All Phase 5E artifacts: `internal_only=True`, `client_visible=False`, `token_logged=False`, `safe_to_deliver=False` always.

### `14_qa_report/` (Phase 5F — implemented)

| Filename | Format | Owner | Purpose |
|---|---|---|---|
| `QA_EVIDENCE_REPORT.json` | JSON | system | `QAEvidenceReport` schema — consolidated multi-source report |
| `QA_EVIDENCE_REPORT.md` | MD | system | Human-readable QA evidence report |
| `QA_REPORT_REVIEW_CHECKLIST.md` | MD | system | Pre-delivery human review checklist |
| `QA_REPORT_SECRET_SCAN.json` | JSON | system | `QASecretScanResult` schema — scan result |
| `QA_REPORT_SECRET_SCAN.md` | MD | system | Human-readable secret scan summary |

All Phase 5F artifacts: `execution_performed=False`, `safe_to_deliver=False`, `human_review_required=True` always.

### `15_google_auth/` (Phase 5G — implemented)

| Filename | Format | Owner | Purpose |
|---|---|---|---|
| `GOOGLE_AUTH_CAPABILITY_PLAN.json` | JSON | system | `GoogleAuthCapability` schema — mode policies and account profile |
| `GOOGLE_AUTH_CAPABILITY_PLAN.md` | MD | system | Human-readable capability plan |
| `GOOGLE_STORAGE_STATE_POLICY.json` | JSON | system | `GoogleStorageStatePolicy` schema — path/metadata only |
| `GOOGLE_STORAGE_STATE_POLICY.md` | MD | system | Human-readable storage-state policy |
| `GOOGLE_AUTH_EXECUTION_DECISION.json` | JSON | system | `GoogleAuthExecutionDecision` schema — per-request allow/block |
| `GOOGLE_AUTH_EXECUTION_DECISION.md` | MD | system | Human-readable execution decision |
| `GOOGLE_AUTH_EVIDENCE_REPORT.json` | JSON | system | `GoogleAuthEvidenceReport` schema — execution evidence |
| `GOOGLE_AUTH_EVIDENCE_REPORT.md` | MD | system | Human-readable evidence report |
| `GOOGLE_AUTH_REDACTION_CHECKLIST.md` | MD | system | Pre-review redaction checklist |
| `.auth/google-storageState.json` | JSON | system | Captured session — **NEVER COMMITTED**, gitignored |
| `manual_capture.cjs` | JS | system | Runtime Playwright script — **NEVER COMMITTED**, gitignored |
| `storage_state_smoke.cjs` | JS | system | Runtime Playwright script — **NEVER COMMITTED**, gitignored |
| `smoke_redacted.png` | PNG | system | Optional redacted screenshot — **NEVER COMMITTED**, gitignored |

All Phase 5G artifacts: `safe_to_deliver=False`, `human_review_required=True`, `cookies_logged=False`, `tokens_logged=False`, `storage_state_content_read=False`, `captcha_bypass_attempted=False`, `anti_bot_bypass_attempted=False`, `personal_account_used=False`, `production_account_used=False` always.

Run `python tools/docs_audit.py` to check for missing required docs.

---

## Related documents

- [`DOCUMENTATION_GOVERNANCE.md`](DOCUMENTATION_GOVERNANCE.md) — full governance rules
- [`SCHEMA_FOUNDATION.md`](SCHEMA_FOUNDATION.md) — schema layer including `documentation.py`
- [`COMMANDS.md`](COMMANDS.md) — CLI commands including planned docs commands

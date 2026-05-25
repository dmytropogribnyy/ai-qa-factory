# Documentation Manifest — Guided QA Automation Workbench

**Version:** 5.1.0  
**Updated:** 2026-05-24  
**Phase:** 2B-AGENT

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
| Project Blueprint (full strategy generation) | `project_blueprint.py` | Phase 2C+ | Phase 2B builds planning blueprint only — no full strategy generation yet |

---

## How to use this manifest

1. **Before starting a phase:** review the Status column. Update stale/needs_review entries first.
2. **After completing a phase:** update the Status column to reflect new state.
3. **When adding a new doc:** add a row here. Set status to `current` only if content is accurate now.
4. **When a doc becomes stale:** change its status to `needs_review` or `stale` and add a note.
5. **When a doc is superseded:** move to the legacy section, set status to `deprecated`.

Run `python tools/docs_audit.py` to check for missing required docs.

---

## Related documents

- [`DOCUMENTATION_GOVERNANCE.md`](DOCUMENTATION_GOVERNANCE.md) — full governance rules
- [`SCHEMA_FOUNDATION.md`](SCHEMA_FOUNDATION.md) — schema layer including `documentation.py`
- [`COMMANDS.md`](COMMANDS.md) — CLI commands including planned docs commands

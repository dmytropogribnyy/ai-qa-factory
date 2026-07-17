# Documentation Governance — Guided QA Automation Workbench

**Version:** 5.1.0  
**Updated:** 2026-05-24  
**Phase:** 1B-DOCS — Documentation Freshness & Governance Foundation

---

## Purpose

The workbench evolves in phases. Schemas, commands, workflows, safety rules, integrations, and tool decisions change. Documentation must stay accurate.

This document defines:
- Which docs are source of truth
- Which docs are operational guides
- Which docs are planned/future-facing
- Which docs must be updated when code changes
- How to mark planned vs implemented
- How to avoid overclaiming runtime behavior
- How to handle schema-only phases
- How to review docs before moving to the next phase

---

## Documentation categories

### Source-of-truth docs

These define the canonical behavior, rules, and structure of the workbench. They must be accurate at all times. If there is a conflict between one of these and the code, both must be investigated and reconciled.

| Doc | What it owns |
|---|---|
| `README.md` | Public overview, entry point, quickstart |
| `docs/VISION.md` | Product direction, guiding principles |
| `docs/RUNBOOK.md` | Day-to-day operational workflow |
| `docs/COMMANDS.md` | CLI command reference — all implemented and planned commands |
| `docs/APPROVAL_MODEL.md` | Risk levels, approval gates, what requires human decision |
| `docs/SAFETY_RULES.md` | Non-negotiable safety rules — governs all execution |
| `docs/TOOLING_DECISIONS.md` | Tooling choices, what is optional, what is not added |
| `docs/SCHEMA_FOUNDATION.md` | `core/schemas/` layer — classes, defaults, patterns |
| `docs/DOCUMENTATION_GOVERNANCE.md` | This file — docs maintenance rules |
| `docs/DOCS_MANIFEST.md` | Registry of all documentation files and their status |

### Operational guides

These support daily work. They should stay current but are less critical than source-of-truth docs.

| Doc | Purpose |
|---|---|
| `docs/REAL_TESTING_PREPARATION.md` | Pre-execution checklist for real-mode test runs |
| `docs/PROJECT_TYPES.md` | Project type taxonomy and test strategy by type |
| `docs/CAPABILITY_MATRIX.md` | What project/opportunity types are supported |
| `docs/MODEL_ROUTING_PROFILES.md` | LLM routing profiles and fallback behavior |

### Planned / future-facing docs

These describe the direction the workbench is heading. They may describe functionality that is not yet implemented.

| Doc | Status note |
|---|---|
| `docs/COMMANDS.md` — planned section | Commands marked `[planned]` are not yet implemented |
| `docs/TOOLING_DECISIONS.md` — optional adapters | LangGraph, Allure, LangSmith, Playwright MCP, n8n are optional/future |
| `docs/APPROVAL_MODEL.md` — future gates | Some approval gates are designed but not yet wired to runtime |

### Generated / output docs

These are produced by the workbench during runs. They are not source of truth.

| Doc | Purpose |
|---|---|
| `outputs/*/DECISION.md` | Decision output from prescreen run |
| `outputs/*/TEST_STRATEGY.md` | Generated test strategy |
| `outputs/*/HUMAN_REVIEW_REQUIRED.md` | Manual review checklist |
| `outputs/docs_audit/DOCS_FRESHNESS_REPORT.md` | Output from `python tools/docs_audit.py` |

---

## Marking planned vs implemented

All commands in `docs/COMMANDS.md` must carry one of these status markers:

| Marker | Meaning |
|---|---|
| `[implemented]` | Command works now. Tested. |
| `[planned]` | Command is designed but not yet built. |
| `[placeholder]` | Exists in code but not fully wired. |

**Rule:** Never describe a planned command as if it works today. If you add a command to `COMMANDS.md`, mark it `[planned]` until it is implemented and tested.

**Direct scripts** (not `main.py` commands) are documented separately. `python tools/docs_audit.py` is an implemented direct script — not a `main.py` command.

---

## Avoiding runtime overclaims

### Schema-only phases

Several Phase 1B addendums added schemas for features that are not yet runtime:
- `core/schemas/credentials.py` — schema only; no real credential resolution
- `core/schemas/auth_flow.py` — schema only; no auth execution (not implemented in this phase)
- `core/schemas/mobile_testing.py` — schema only; no mobile automation
- `core/schemas/integration.py` — schema only; no HTTP calls to n8n or other services
- `core/schemas/redaction.py` — schema only; no live redaction pass

**Rule:** Any doc that mentions these features must include one of these qualifiers:
- `schema-only`
- `foundation-only`
- `not yet implemented`
- `planned`
- `[planned]`
- `Phase 2+`

### Optional tools and integrations

These tools/adapters are optional and must never be described as mandatory or always-on:

| Tool | Status | Qualifier required |
|---|---|---|
| n8n / Make / Zapier | Optional external adapter | `optional`, `not the core engine` |
| LangGraph | Optional future orchestration backend | `optional future`, `not added until conditions met` |
| Allure | Optional reporting adapter | `optional`, `not in requirements.txt` |
| LangSmith | Optional tracing adapter | `optional`, `not mandatory` |
| Playwright MCP | Optional helper, not runtime dependency | `optional`, `not mandatory`, `guide only` |
| Mobile/native execution | Future phase | `foundation-only`, `planned`, `Phase 3+` |
| Auth/credential execution | Future phase | `foundation-only`, `planned`, `Phase 2+` |
| Cleanup apply/deletion | Requires explicit approval | `dry-run required`, `explicit approval required` |

---

## Update triggers

When the following changes happen, the corresponding docs must be reviewed and updated:

| Code / behavior change | Docs that must be reviewed |
|---|---|
| Schema module added/changed | `SCHEMA_FOUNDATION.md`, `DOCS_MANIFEST.md` |
| CLI command added or removed | `COMMANDS.md`, `RUNBOOK.md` |
| Workflow step added or changed | `RUNBOOK.md`, `COMMANDS.md` |
| Safety rule added or changed | `SAFETY_RULES.md`, `APPROVAL_MODEL.md` |
| Approval gate added or changed | `APPROVAL_MODEL.md`, `SAFETY_RULES.md` |
| New tool added or dropped | `TOOLING_DECISIONS.md` |
| New integration added | `TOOLING_DECISIONS.md`, `SAFETY_RULES.md`, `SCHEMA_FOUNDATION.md` |
| Auth/credential behavior changes | `SAFETY_RULES.md`, `APPROVAL_MODEL.md`, `SCHEMA_FOUNDATION.md` |
| Mobile testing support changes | `TOOLING_DECISIONS.md`, `SCHEMA_FOUNDATION.md` |
| Evidence/reporting changes | `SCHEMA_FOUNDATION.md`, `RUNBOOK.md` |
| AI resilience behavior changes | `SCHEMA_FOUNDATION.md`, `TOOLING_DECISIONS.md` |
| Version bump | `README.md`, relevant docs headers |
| Phase completed | `DOCS_MANIFEST.md` (update status column) |
| Workflow phases added or changed | `AGENT_CONTRACT.md`, `PHASE_CONTRACTS.md` |
| Safety rules added or changed | `AGENT_CONTRACT.md`, `SAFETY_RULES.md`, `APPROVAL_MODEL.md` |
| Artifact paths added or changed | `ARTIFACT_CONTRACTS.md`, `DOCS_MANIFEST.md` |
| Agent behavior or contract changed | `AGENT_CONTRACT.md`, `PHASE_CONTRACTS.md`, `DOCS_MANIFEST.md` |

---

## How to handle schema-only phases

When a phase adds schemas but no runtime behavior:

1. **In `SCHEMA_FOUNDATION.md`:** document the new schema module, describe defaults, mark "schema-only foundation. No runtime behavior in this phase."
2. **In `COMMANDS.md`:** if planned commands will use these schemas, add them under `## Planned commands` with `[planned]` marker.
3. **In `SAFETY_RULES.md`:** if the schema encodes safety rules, document them. Note they are enforced by schema defaults today, and will be enforced at runtime in a future phase.
4. **In `TOOLING_DECISIONS.md`:** if the feature involves optional tools, note the boundary.
5. **Do not write** "the workbench does X" in any present-tense statement about runtime behavior until the runtime is implemented and tested.

---

## Reviewing docs before phase transitions

Before starting a new phase:

1. Run `python tools/docs_audit.py` — review all warnings and errors.
2. Open `docs/DOCS_MANIFEST.md` — check the status column. Update stale entries.
3. Check that all new schema modules are listed in `SCHEMA_FOUNDATION.md`.
4. Check that all new commands are in `COMMANDS.md` with correct `[planned]` or `[implemented]` markers.
5. Check that no doc describes a planned feature as implemented.
6. If a doc needs significant updates, update it before starting the phase — not after.

**Rule:** A phase transition should never leave docs in a stale state that contradicts the current code.

---

## Documentation audit script

```bash
python tools/docs_audit.py
```

What it checks:
- All required docs exist (ERROR if missing)
- Known-implemented commands in COMMANDS.md carry `[implemented]` marker (WARNING)
- Foundation-only features not described as active runtime in any doc (WARNING)
- DOCS_MANIFEST.md references core source-of-truth docs (WARNING)
- SCHEMA_FOUNDATION.md mentions documentation.py schema (WARNING)

Exit codes:
- `0` — all required docs present, no hard errors
- `1` — missing required docs or hard contradictions

Run after any phase that changes schemas, commands, workflows, safety rules, or integrations.

---

## Related documents

- [`DOCS_MANIFEST.md`](DOCS_MANIFEST.md) — map of all documentation files
- [`SCHEMA_FOUNDATION.md`](SCHEMA_FOUNDATION.md) — schema layer including `documentation.py`
- [`COMMANDS.md`](COMMANDS.md) — CLI commands including planned docs commands
- [`SAFETY_RULES.md`](SAFETY_RULES.md) — safety rules that govern all execution
- [`RUNBOOK.md`](RUNBOOK.md) — operational workflow including docs freshness section

---

## Nested architecture specifications (`docs/architecture/`)

A distinct documentation category for detailed architecture specifications of ARK capability
domains and work contours.

Rules:

- A nested architecture doc **may be source of truth** for a specific domain.
- It **may be approved but future-facing** — it must clearly distinguish approved architecture
  from implemented runtime (a status block near the top).
- `docs/PHASE_CONTRACTS.md` is authoritative for **implementation status**;
  `docs/PRODUCT_VISION_2026.md` owns the high-level **phase map**.
- Nested architecture docs **are included in the docs audit** (the content/runtime-overclaim
  scan is recursive) and **must be registered in** [`DOCS_MANIFEST.md`](DOCS_MANIFEST.md).
- Archive documents under `docs/archive/` are **not authoritative** and are handled separately
  (excluded from the runtime-overclaim scan by design).

**Update triggers** for nested architecture docs: `phase_completed`, `architecture_approved`,
`schema_changed`, `runtime_status_changed`.

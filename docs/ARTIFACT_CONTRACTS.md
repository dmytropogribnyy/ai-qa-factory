# Artifact Contracts — Guided QA Automation Workbench

**Version:** 5.2.0
**Updated:** 2026-05-25
**Phase:** 2B-AGENT

This document defines the stable artifact paths, formats, and ownership rules for all
workbench-generated files. Agents and scripts should use these paths and respect the
ownership boundaries described here.

---

## Core Principle

```
outputs/                  ← runtime artifacts — always gitignored, never committed
core/                     ← source code — committed
tests/                    ← Workbench self-tests — committed
docs/                     ← governance docs — committed
```

**`repository tests/` is reserved exclusively for Workbench self-tests.**
It must never contain generated client test specs, Playwright specs, or project-specific
test files. Those belong under `outputs/<project_id>/03_framework/` (Phase 3A+).

---

## Artifact Ownership

| Artifact type | Location | Committed? | Agent may create? |
|---|---|---|---|
| Generated project artifacts | `outputs/<project_id>/` | No — gitignored | Yes |
| Playwright/pytest framework | `outputs/<project_id>/03_framework/` | No — gitignored | Phase 3A+ |
| Workbench self-tests | `tests/` | Yes | Yes (in phase scope) |
| Schema modules | `core/schemas/` | Yes | Yes (in phase scope) |
| Runtime modules | `core/*.py` | Yes | Yes (in phase scope) |
| Governance docs | `docs/` | Yes | Yes (in phase scope) |
| Audit reports | `outputs/docs_audit/`, `outputs/agent_audit/` | No — gitignored | Yes |

---

## Phase 2A/2B Artifact Layout

All Phase 2A and 2B artifacts are written to:

```
outputs/<project_id>/00_project/
```

### Machine-readable (JSON) — source for agents

| File | Phase | Description |
|---|---|---|
| `INPUT_MAP.json` | 2A | All classified input sources with types, labels, approval status |
| `WORK_REQUEST.json` | 2A | Normalised intake record: title, summary, raw brief, platform, inputs |
| `TASK_CLASSIFICATION.json` | 2A | Task type, project type, confidence, signals, notes |
| `PROJECT_STATUS.json` | 2A | Current phase, overall status, next action, notes |
| `PROJECT_BLUEPRINT.json` | 2B | Full planning source-of-truth: type, environment, surfaces, risks, etc. |

When reading project state, prefer `.json` over `.md` for structured processing.

### Human-readable (Markdown) — companion files for review

| File | Phase | Description |
|---|---|---|
| `INPUT_MAP.md` | 2A | Formatted list of input sources |
| `WORK_REQUEST.md` | 2A | Formatted work request |
| `TASK_CLASSIFICATION.md` | 2A | Classification table and signals |
| `PROJECT_STATUS.md` | 2A | Status table and next action |
| `NEXT_SAFE_STEP.md` | 2A | Human-readable next action guidance |
| `PROJECT_BLUEPRINT.md` | 2B | Full planning overview |
| `ASSUMPTIONS.md` | 2B | Working assumptions for client confirmation |
| `MISSING_INFO.md` | 2B | Information needed before execution |
| `SAFE_NEXT_STEPS.md` | 2B | Planning-only actions safe to proceed |
| `BLOCKED_ACTIONS.md` | 2B | Actions blocked until approvals obtained |
| `INITIAL_QA_STRATEGY_OUTLINE.md` | 2B | Preliminary test layer guidance |

### Artifact contract guarantees (Phase 2A/2B)

- **No raw secrets** — all passwords, tokens, cookies, JWTs are replaced with
  `[REDACTED_*]` before writing
- **No execution claims** — artifacts explicitly state no execution has occurred
- **No invented data** — all values are derived from actual input text
- `PROJECT_BLUEPRINT.json` is the primary source for Phase 2C (Strategy Planner)
- `BLOCKED_ACTIONS.md` lists what requires approval before any execution

---

## Future Artifact Layout (Phase 3A+)

These paths are planned. No implementation yet.

```
outputs/<project_id>/
    00_project/          ← Phase 2A/2B (implemented)
    01_approval/         ← Approval decisions and status (Phase 3+)
    02_strategy/         ← QA strategy, risk matrix, test scope (Phase 2C)
    03_framework/        ← Generated Playwright TypeScript framework (Phase 3A)
    04_execution/        ← Test run results and logs (Phase 4A)
    05_evidence/         ← Screenshots, traces, HTML reports (Phase 4A)
    06_client_draft/     ← Client-facing reports and delivery packages (Phase 4A+)
        packages/        ← Zipped delivery packages (require delivery approval)
    99_internal/         ← Internal notes, quality gate reports, debug logs
```

### Folder ownership rules

| Folder | Committed? | Client-visible? | Notes |
|---|---|---|---|
| `00_project/` | No | No (internal) | Planning artifacts |
| `01_approval/` | No | No | Approval records |
| `02_strategy/` | No | Prepared by agent, reviewed by human | Strategy docs |
| `03_framework/` | No | Delivered after review | Generated scaffold |
| `04_execution/` | No | No | Raw execution logs |
| `05_evidence/` | No | Referenced in report | Screenshots, traces |
| `06_client_draft/` | No | After human review only | Client delivery |
| `99_internal/` | No | Never | Internal quality gates, debug |

**`06_client_draft/` is never sent without completing `HUMAN_REVIEW_REQUIRED.md`.**
**`99_internal/` must never be included in client delivery packages.**

---

## Audit Report Layout

```
outputs/docs_audit/
    DOCS_FRESHNESS_REPORT.md    ← generated by python tools/docs_audit.py
    docs_freshness_report.json  ← machine-readable summary

outputs/agent_audit/
    AGENT_READINESS_REPORT.md   ← generated by python tools/agent_readiness_audit.py
    agent_readiness_report.json ← machine-readable summary
```

Both report folders are under `outputs/` and are gitignored.

---

## Artifact Safety Rules

1. **Never commit `outputs/`** — it is gitignored for a reason. Artifacts contain runtime
   data, potentially partial secrets, client info, and internal state.
2. **JSON artifacts are machine-readable truth** — prefer them over `.md` when reading
   project state programmatically.
3. **Markdown artifacts are for human review** — they may be opened in a browser, IDE, or
   shared in Slack. Ensure they contain no raw secrets.
4. **Framework code in `03_framework/`** is generated scaffold — always review before
   execution. It does not run automatically.
5. **`99_internal/` content never goes to clients** — quality gate reports, agent
   reasoning notes, and debug logs stay internal.

---

## Machine-Readable Format Notes

All JSON artifacts use:
- UTF-8 encoding
- 2-space indentation
- ISO 8601 timestamps
- `project_id` present in every root object
- Empty lists `[]` rather than `null` for list fields

Agents reading JSON artifacts should:
1. Check `project_id` matches expected project
2. Check `phase` field to understand what was generated
3. Check `BLOCKED_ACTIONS.md` before planning any execution
4. Check `SAFE_NEXT_STEPS.md` for approved planning actions

---

## Related Documents

- [`AGENT_CONTRACT.md`](AGENT_CONTRACT.md) — agent operating rules
- [`PHASE_CONTRACTS.md`](PHASE_CONTRACTS.md) — phase boundaries
- [`AGENT_HANDOFF_TEMPLATE.md`](AGENT_HANDOFF_TEMPLATE.md) — final report template
- [`DOCS_MANIFEST.md`](DOCS_MANIFEST.md) — all docs registry

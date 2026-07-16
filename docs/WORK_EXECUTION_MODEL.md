# Work Execution Model

**Version:** 8.0.0 (foundation)
**Status:** Planned. Phase 8.0 defines the state vocabulary and backend strategy as
schemas + docs. No executor and no MCP calls exist yet.

---

## Canonical resumable state machine

### Reuse decision

The existing `ProjectStatus` (`core/schemas/project_status.py`) uses free-form
`phase` / `overall_status` strings and is **not** a formal resumable state machine.
`ProgressTracker` tracks completion percentages, not lifecycle. Therefore `WorkRunState`
(`core/schemas/work_run_state.py`) is added as an **additive** canonical lifecycle record
that complements `ProjectStatus` (which is unchanged).

### States

```
RECEIVED → INTAKE_COMPLETE → PLANNED
  → WAITING_FOR_INFORMATION | WAITING_FOR_APPROVAL
  → READY_TO_EXECUTE → EXECUTING → EXECUTION_PARTIAL
  → VERIFYING → REPAIR_REQUIRED → READY_FOR_REVIEW → READY_FOR_DELIVERY → COMPLETED
Side states: BLOCKED, FAILED, CANCELLED
```

Terminal states (`COMPLETED`, `FAILED`, `CANCELLED`) are immutable once reached. The
allowed forward transitions are declared in `ALLOWED_TRANSITIONS` and documented for the
future orchestrator; Phase 8.0 does not enforce them at runtime.

### What the state machine enables

- resume after restart (state + completed_steps persisted as artifacts)
- retry a single failed step (`pending_step`, `REPAIR_REQUIRED`)
- partial execution (`EXECUTION_PARTIAL`)
- cancellation (`CANCELLED`)
- idempotency and prevention of duplicate write actions
- switching between Claude, Codex, and CLI via `owner_agent` + artifacts
- independent verifier state (`VERIFYING` distinct from `EXECUTING`)
- immutable execution history (`history: [StateTransition]`)

## Backend strategy (correction #3)

`SelectedMCPTool.backend` ∈ `{existing_runner, playwright_cli, playwright_mcp,
chrome_devtools_mcp}`. Intended routing:

| Work | Backend |
|---|---|
| Exploration / surface mapping / iterative browser reasoning | `playwright_mcp` |
| Performance / network / console / deep debugging | `chrome_devtools_mcp` |
| Repeatable regression / CI | `playwright_cli` + generated specs |
| Deterministic compatibility (default) | `existing_runner` |

**Existing runners are not removed or modified.** Any replacement of an existing runner by
an MCP backend requires parity tests (Windows, auth, evidence, reports, CI) plus a rollback
plan. MCP is an additional backend, not an immediate replacement.

## Execution budgets and untrusted content

Every execution is bounded by an `ExecutionBudget` and governed by the untrusted-content
rule (`ToolExecutionPolicy.untrusted_output = True`). See
`docs/MCP_SECURITY_AND_TRUST_MODEL.md`.

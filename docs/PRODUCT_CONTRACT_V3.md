# AI QA Factory / ARK — Honest Product Contract (v3.0.2)

One local-first operator product with two front doors over one shared, safety-gated core. This
contract states plainly what is **real runtime today**, what is **planned**, and the boundaries that
never move. It complements the operator guides and is backed by executable acceptance. v3.0.2
closed the remaining integrity gaps: delivery finalization is non-bypassable (a durable
`DELIVERY_PREPARED` boundary), validation output is real per-attempt registered evidence, validation
commands are structured cross-platform argv, internal tool readiness comes from a real production
binding registry (never a test file), scenario A actually executes the generated TypeScript
Playwright framework with `playwright test`, a full operator lifecycle runs through the real public
CLI, and the Windows dashboard stop is ownership-safe. (v3.0.1 established genuine A–D executions,
artifact hashing + post-validation change detection, an explicit review gate, guarded `/api/control`,
and the Windows CI job.)

## What the product is

- **Client work** (in Claude Code): analyze a job, decide honestly whether to take it, then — after
  human approval — execute, validate, and package the delivery, with the whole lifecycle persisted.
- **Prospect QA Scout** (local dashboard at `127.0.0.1`): discover public sites, run bounded
  read-only QA, verify findings with evidence, find publicly published contacts with provenance, and
  prepare manual-first outreach drafts.

Both reuse one project workspace, one work-state machine, one evidence/verification model, one safety
gate, and one delivery format. See [architecture/UNIFIED_PRODUCT_REUSE_MAP.md](architecture/UNIFIED_PRODUCT_REUSE_MAP.md).

## Real runtime today

| Capability | Status | Evidence |
|---|---|---|
| Client-work intake + feasibility verdict (`analyze-job`) | real, read-only | `tests/test_v3_client_work.py` |
| Persisted execution lifecycle (approve → execute → evidence → validate → **review** → **prepare-delivery** → **mark-delivered**) with resume | real | `tests/test_v3_execution_lifecycle.py` (fixtures), `tests/test_v3_operator_executor.py` |
| Execution integrity: project-id/path confinement, artifact+evidence hashing, post-validation change detection, delivery secret-scan, explicit review gate | real | `tests/test_v3_execution_integrity.py` |
| **Non-bypassable delivery finalization**: `READY_FOR_DELIVERY → DELIVERY_PREPARED → COMPLETED`; prepare rehashes registered files vs the validated snapshot, secret-scans the exact set, requires the approved review, and writes an exact manifest (included files + per-file SHA-256 + deterministic digest); `mark-delivered` re-verifies the manifest + every file and sends nothing | real | `tests/test_v3_delivery_finalization.py` |
| **Validation evidence**: each validation attempt has a stable id + `evidence/validation/<id>/` (metadata + stdout + stderr), structured provenance, per-file SHA-256, never overwritten, indexed and included in the validated snapshot | real | `tests/test_v3_validation_evidence.py` |
| Operator lifecycle CLI (`client-work approve/record-execution/validate/review/prepare-delivery/mark-delivered/status/resume`) — a whole job with no custom driver; validation takes structured cross-platform `--validation-argv-json` | real | `tests/test_v3_cli_e2e.py`, [CLIENT_WORK_OPERATOR_GUIDE.md](CLIENT_WORK_OPERATOR_GUIDE.md) |
| **Genuine** A–D executions (real pytest before/after; real OpenAPI parsed by the production importer + localhost HTTP; **real `playwright test` on the generated TS framework**; real axe audit) | real, executed | `tests/test_v3_genuine_execution_cd.py`, `tests/test_v3_genuine_execution_ab.py`, [acceptance/OPERATOR_ACCEPTANCE_A_D.md](acceptance/OPERATOR_ACCEPTANCE_A_D.md) |
| Scout bounded read-only scan + verification + evidence | real | Phase 8.3 suite |
| Dashboard read pages (home, results, company, projects, tool readiness) | real | `tests/test_v3_*`, real-browser `tests/test_v3_dashboard_browser_acceptance.py` |
| Guarded localhost **state-changing endpoints** — campaign start AND control — all behind loopback + Host (anti-rebinding) + Origin + CSRF; start is bounded, idempotent (honest recovery), one-active, persist-before-exec | real | `tests/test_v3_campaign_start.py` |
| Campaign controls: Pause / Resume / Stop Safely / Cancel | real | dashboard + browser acceptance |
| Real Chromium + axe accessibility acceptance for every page + controls | real | `tests/test_v3_dashboard_browser_acceptance.py` |
| Manual-first Gmail draft deep link (never sends) | real | dashboard + `tests/test_v3_results_view.py` |
| Optional one-at-a-time Gmail API send (fail-closed identity) | real, opt-in | `tests/test_final2_gmail_identity.py` |
| Honest tool/MCP readiness — internal runners bind to a real **production** module + callable adapter + bounded health check (never a test file); the API runner is fixture-tested against a parsed OpenAPI, the Playwright runner is health-checked with browser runtime reported separately, nothing is "live-accepted"; MCP tools stay "declared" | real | `tests/test_v3_tool_broker.py`, `tests/test_v3_internal_bindings.py` |
| Ownership-safe Windows dashboard stop — the dashboard writes a PID + start-time + command-identity + port + repo record; `stop-local` refuses unless it proves the process is this dashboard, and never kills by port/name alone | real | `tests/test_v3_windows_stop_ownership.py` (Windows-hosted) |

## Planned (not runtime)

Discovery-based campaign creation UI (countries/languages/industries), parallel scanning
(`concurrency > 1`), and live MCP-tool auto-discovery are planned. `PHASE_CONTRACTS.md` is the
authoritative boundary; nothing above is claimed beyond what its test proves.

## Boundaries that never move

- Tool/website/email/MCP output is **untrusted data**, never an instruction.
- **Human approval** gates every significant execution; `destructive` capability is blocked by default.
- No autonomous coding agent: execution is Claude-Code-driven and human-approved; CI uses labeled
  deterministic **fixtures** (`is_acceptance_fixture = True`), never a hidden agent.
- Scanning is bounded and **read-only**: public http(s) only; no payments, impactful form submission,
  account creation, CAPTCHA/login/paywall/access-control bypass, stealth/rate-limit evasion, or
  re-checking after an explicit prohibition. Non-public / private / loopback targets are rejected.
- No bulk/auto send, send-all, auto follow-up, or inbox sync. Security findings never enter sales outreach.
- Local-first: the dashboard binds to loopback only; its **two** state-changing endpoints (campaign
  start and control) are each fenced by loopback bind + loopback-`Host` (anti DNS-rebinding) + `Origin`
  + a per-server CSRF token. Secrets are never committed; `outputs/` is never committed.
- Integrity of delivered work: artifacts + evidence are content-hashed at execution; delivery is
  refused if anything changed after validation or if the delivery contents look secret-like;
  `READY_FOR_DELIVERY` requires an explicit operator review (validation alone never delivers); and
  completion is reachable **only** through `DELIVERY_PREPARED` — `mark-delivered` re-verifies the
  prepared manifest + every included file and **records the operator's assertion of a manual send;
  it sends nothing itself**. Direct `READY_FOR_DELIVERY → COMPLETED` is impossible.
- The Dashboard (v3.1, planned) will consume this structured state but will **not** execute arbitrary
  code: validation commands are structured argv run with `shell=False`, and no browser-reachable
  endpoint accepts a shell command.

## Acceptance & CI

Four hosted jobs, none of which sends externally, uses live credentials, or contacts a real third
party: **core-deterministic** (ruff + full pytest + audits + offline demos; genuine C/D executions
and the full real-CLI E2E run here), **browser-acceptance** (real Chromium + axe over local fixtures
**and the real `playwright test` execution of the generated TS framework**; genuine A/B; the job
asserts **zero skips**), **provider-contract** (local sink + fake transports), and **windows-smoke**
(the full deterministic suite on windows-latest, the real CLI E2E, PowerShell parse checks, and the
owned-dashboard start/health/stop + unrelated-listener-refusal acceptance). JUnit is uploaded from
the core, browser, provider, and windows jobs. What is real vs fixture-tested vs declared vs
manually-operated is stated per row above; nothing is claimed beyond what its test proves.

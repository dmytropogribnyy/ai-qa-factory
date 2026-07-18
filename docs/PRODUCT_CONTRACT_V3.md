# AI QA Factory / ARK — Honest Product Contract (v3.0.0)

One local-first operator product with two front doors over one shared, safety-gated core. This
contract states plainly what is **real runtime today**, what is **planned**, and the boundaries that
never move. It complements the operator guides and is backed by executable acceptance.

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
| Persisted execution lifecycle (approval → execution → evidence → validation → delivery → resume) | real | `tests/test_v3_execution_lifecycle.py` (fixtures), `tests/test_v3_operator_executor.py` |
| Operator lifecycle CLI (`client-work status/approve/resume/prepare-delivery`) | real | this guide + [CLIENT_WORK_OPERATOR_GUIDE.md](CLIENT_WORK_OPERATOR_GUIDE.md) |
| Documented real Claude-Code operator acceptance A–D | real, performed | [acceptance/OPERATOR_ACCEPTANCE_A_D.md](acceptance/OPERATOR_ACCEPTANCE_A_D.md) |
| Scout bounded read-only scan + verification + evidence | real | Phase 8.3 suite |
| Dashboard read pages (home, results, company, projects, tool readiness) | real | `tests/test_v3_*`, real-browser `tests/test_v3_dashboard_browser_acceptance.py` |
| Guarded localhost campaign **start** (loopback + Host + Origin + CSRF; bounded; idempotent; one-active; persist-before-exec) | real | `tests/test_v3_campaign_start.py` |
| Campaign controls: Pause / Resume / Stop Safely / Cancel | real | dashboard + browser acceptance |
| Real Chromium + axe accessibility acceptance for every page + controls | real | `tests/test_v3_dashboard_browser_acceptance.py` |
| Manual-first Gmail draft deep link (never sends) | real | dashboard + `tests/test_v3_results_view.py` |
| Optional one-at-a-time Gmail API send (fail-closed identity) | real, opt-in | `tests/test_final2_gmail_identity.py` |
| Honest tool/MCP readiness (declared … live-accepted; MCP tools only "declared") | real | `tests/test_v3_tool_broker.py` |

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
- Local-first: the dashboard binds to loopback only and exposes exactly one state-changing endpoint
  (the guarded campaign start). Secrets are never committed; `outputs/` is never committed.

## Acceptance & CI

Three hosted jobs, none of which sends externally, uses live credentials, or contacts a real third
party: **core-deterministic** (ruff + full pytest + audits + offline demos), **browser-acceptance**
(real Chromium + axe + performance over local fixtures), and **provider-contract** (local sink + fake
transports). JUnit is uploaded from the core, browser, and provider jobs.

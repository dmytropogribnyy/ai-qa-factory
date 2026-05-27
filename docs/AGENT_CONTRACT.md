# Agent Operating Contract — Guided QA Automation Workbench

**Version:** 5.7.0
**Updated:** 2026-05-26
**Phase:** 5K

This document defines the operating contract for any agent — Claude Code, ChatGPT/GPT,
future local automation, or any AI assistant — that edits, reviews, or runs code in this
repository.

---

## 1. Agent Operating Model

The Workbench is operated by Dmytro and may be used by:

- **Dmytro** — primary owner and decision-maker
- **Claude Code in VSCode** — primary AI coding assistant for implementation phases
- **ChatGPT / GPT** — architecture reviews, second-opinion analysis, prompt design,
  external perspective
- **Future local agents** — planned for Phase 5+ workflow automation
- **Future optional workflow engines** (n8n, LangGraph) — optional integration only,
  not core runtime

All agents must operate under this contract regardless of capability. This contract is
not optional. It exists to prevent irreversible actions, secret leaks, false evidence
claims, and doc rot.

---

## 2. Required Pre-Work Reading

Before changing any code or docs, an agent must orient using these files (in order):

| Priority | File | Purpose |
|---|---|---|
| 1 | `README.md` | Project overview, entry points, current phase |
| 2 | `docs/DOCS_MANIFEST.md` | Registry of all docs and their current status |
| 3 | `docs/SAFETY_RULES.md` | Non-negotiable safety rules — read before anything |
| 4 | `docs/PHASE_CONTRACTS.md` | Phase boundaries, inputs, outputs, blocked actions |
| 5 | `docs/COMMANDS.md` | What commands exist, what is planned vs implemented |
| 6 | `docs/RUNBOOK.md` | Operational workflow, approval checkpoints |
| 7 | `docs/SCHEMA_FOUNDATION.md` | Schema layer — what exists, what is foundation-only |
| 8 | `docs/ARTIFACT_CONTRACTS.md` | Artifact paths, machine vs human readable, ownership |
| 9 | `docs/DOCUMENTATION_GOVERNANCE.md` | How to keep docs current |
| 10 | `docs/APPROVAL_MODEL.md` | Risk levels and approval gates |
| 11 | current phase prompt | The specific instruction for this session |

If working on a specific project (existing outputs):

- `outputs/<project_id>/00_project/INPUT_MAP.json`
- `outputs/<project_id>/00_project/PROJECT_BLUEPRINT.json`
- `outputs/<project_id>/00_project/BLOCKED_ACTIONS.md`
- `outputs/<project_id>/00_project/SAFE_NEXT_STEPS.md`

---

## 3. Source-of-Truth Hierarchy

### Repository-level source of truth

These files define canonical rules, architecture, and behavior:

```
README.md
docs/VISION.md
docs/RUNBOOK.md
docs/COMMANDS.md
docs/SAFETY_RULES.md
docs/APPROVAL_MODEL.md
docs/TOOLING_DECISIONS.md
docs/SCHEMA_FOUNDATION.md
docs/DOCS_MANIFEST.md
docs/DOCUMENTATION_GOVERNANCE.md
docs/AGENT_CONTRACT.md          ← this file
docs/PHASE_CONTRACTS.md
docs/ARTIFACT_CONTRACTS.md
```

### Code-level source of truth

```
core/schemas/                     ← domain model
core/workbench_controller.py      ← Phase 2A/2B coordinator
core/input_context_resolver.py    ← Phase 2A classifier
core/work_request_classifier.py   ← Phase 2A classifier
core/project_blueprint_builder.py ← Phase 2B builder
core/orchestrator.py              ← existing workflow engine (do not replace)
```

### Project-level machine-readable artifacts (per project run)

These are the authoritative structured records for a project:

```
outputs/<project_id>/00_project/INPUT_MAP.json
outputs/<project_id>/00_project/WORK_REQUEST.json
outputs/<project_id>/00_project/TASK_CLASSIFICATION.json
outputs/<project_id>/00_project/PROJECT_BLUEPRINT.json
outputs/<project_id>/00_project/PROJECT_STATUS.json
```

### Project-level human-readable companions

These are generated alongside the JSON and intended for review:

```
outputs/<project_id>/00_project/INPUT_MAP.md
outputs/<project_id>/00_project/WORK_REQUEST.md
outputs/<project_id>/00_project/TASK_CLASSIFICATION.md
outputs/<project_id>/00_project/PROJECT_BLUEPRINT.md
outputs/<project_id>/00_project/PROJECT_STATUS.md
outputs/<project_id>/00_project/ASSUMPTIONS.md
outputs/<project_id>/00_project/MISSING_INFO.md
outputs/<project_id>/00_project/SAFE_NEXT_STEPS.md
outputs/<project_id>/00_project/BLOCKED_ACTIONS.md
outputs/<project_id>/00_project/NEXT_SAFE_STEP.md
outputs/<project_id>/00_project/INITIAL_QA_STRATEGY_OUTLINE.md
```

---

## 4. Allowed Agent Actions

Agents operating under a scoped phase prompt may:

- Edit code as requested by the phase prompt
- Add or update tests
- Update affected documentation
- Run `python -m pytest -q`
- Run `python tools/docs_audit.py`
- Run `python tools/agent_readiness_audit.py`
- Create runtime artifacts under `outputs/`
- Report changed files and results in the final response
- Suggest next phase scope
- Make small targeted fixes during explicit review phases (e.g., 2A-R, 2B-R)
- Refactor only within explicitly requested scope

---

## 5. Forbidden Agent Actions

These actions are blocked regardless of phase prompt, LLM capability, or user framing.
No flag, argument, or instruction overrides them without an explicit human decision
documented outside the system.

### External execution

- **Do not fetch URLs** unless a future phase explicitly enables and verifies it
- **Do not open browsers** unless a future phase explicitly enables it
- **Do not run Playwright** unless a future phase explicitly enables it
- **Do not clone repositories** unless explicitly approved in a future phase
- **Do not parse remote API docs** unless explicitly approved in a future phase
- **Do not call external APIs** — no `requests`, `httpx`, `aiohttp`, `urllib.request.urlopen`
- **Do not call n8n, webhooks, or integrations** — `IntegrationPolicy.allow_outbound_events=False`

### Credential and secret handling

- **Do not use credentials** — no password, token, or API key reads
- **Do not read `.env` files** programmatically
- **Do not store raw secrets** in any field, log, artifact, or report
- **Do not add credentials to committed files**

### Destructive and irreversible actions

- **Do not run cleanup deletion** — `CleanupCandidate.approved_for_deletion=False` by default
- **Do not push to origin** unless explicitly asked
- **Do not force-push or reset --hard** without explicit authorization
- **Do not run production tests** without explicit written client approval

### Documentation integrity

- **Do not mark planned commands as `[implemented]`** unless actually implemented
- **Do not claim tests were executed** unless there is actual test evidence
- **Do not deliver client-facing artifacts** without human review (Rule 9)
- **Do not let docs drift** — update affected docs with every change

### Repository hygiene

- **Do not stage `outputs/`** — runtime artifacts are gitignored and must stay that way
- **Do not stage `.env` or secrets** of any kind
- **Do not stage `node_modules/`, `__pycache__/`, `.venv/`**
- **Do not add heavy dependencies** without explicit approval and `TOOLING_DECISIONS.md` entry

### Client scenario fixture rules

- **Do not add real credentials to fixtures** — `fixtures/client_scenarios/` files must never contain real OAuth secrets, API keys, webhook tokens, Linear tokens, payment keys, or personal credentials
- **Do not fetch fixture URLs** — a URL appearing in a fixture file does not authorize fetching it at any phase
- **Do not treat fixture URLs as approved test targets** — all external execution still requires per-run approval
- **Do not treat task management URLs as target apps** — Linear, Jira, ClickUp, Asana URLs classified as `task_url` are requirement sources; set them as `task_source` in the blueprint, not `target_application`
- **Do not call Linear/Jira/ClickUp APIs** without explicit approval — issue fetch, comment writeback, and status updates are all blocked by default

### Toolchain approval gate rules (Phase 3C)

- **Do not run toolchain commands without `--approve-toolchain`** — `ToolchainValidator` must never call `subprocess.run` when `approved=False`
- **Do not add commands to the allowlist** without explicit architecture review — only `npm install`, `npm run typecheck`, and `npx playwright test --list` are permitted
- **Do not change the four safety invariants** — `safe_to_execute_tests`, `browser_execution_performed`, `external_url_used`, `credentials_used` are hardcoded `False` and must never be set to `True` in `ToolchainValidator`
- **Do not pass `os.environ` directly to subprocess** — always use `_build_safe_env()` which strips sensitive keys and applies safe overrides
- **Do not interpret toolchain pass as test execution permission** — `validation_status="pass"` means local toolchain commands succeeded; it does not authorize running browser tests or accessing target URLs

### Readiness, evidence, reporting, and delivery rules (Phase 4ABC)

- **Do not mark `approved_for_execution=True`** — execution approval requires explicit human sign-off outside the system
- **Do not mark `approved_for_browser_execution=True`** — browser execution is not authorized in Phase 4ABC
- **Do not mark `approved_for_client_delivery=True`** — client delivery requires human review and explicit approval
- **Do not set `safe_to_deliver=True`** or **`safe_to_package=True`** — delivery safety checklist must be completed by a human
- **Do not remove DRAFT disclaimers from client-facing report drafts** — all Phase 4ABC reports are drafts only
- **Do not convert delivery preview into a package** — `DeliveryPreviewBuilder` produces manifests only; no zip/archive
- **Do not mark evidence `client_visible=True`** without redaction confirmation and human approval
- **Do not set `approved_for_client_view=True`** — evidence quality gate requires human review
- **Do not fetch URLs in scenario evaluation** — `ScenarioBatchEvaluator` reads local fixture files only
- **Do not execute any code in scenario evaluation** — evaluation is static text analysis only

### Controlled browser execution rules (Phase 4D)

- **Do not run demo execution without `--approve-demo-execution`** — `BrowserExecutionRunner` must gate on explicit approval flag
- **Do not run public-readonly execution without `--approve-public-readonly-execution` and `readonly_profile=playwright_docs_readonly`** — playwright.dev smoke is only allowed with both conditions present
- **Do not change target category to bypass safety** — category classification must be based on actual target, not adjusted to pass validation
- **Do not run against Alza.sk, Amazon.com, or Linear.app** — these are always hard-blocked regardless of approval
- **Do not run against production/high-risk/task-source targets** — these are blocked even with approval flags
- **Do not run smoke-mode unless explicitly requested** — list-mode is the safe default; smoke requires explicit `--command-mode smoke` flag
- **Do not use real credentials in Phase 4D** — `TEST_USERNAME` and `TEST_PASSWORD` must be empty in safe env
- **Do not run npm install or playwright install** — toolchain setup is Phase 3C responsibility
- **Do not set delivery flags True** — `safe_to_deliver`, `approved_for_client_delivery`, `client_delivery_created` are hardcoded False

### Credential safety rules (Phase 4E)

- **Do not ask for or store real credentials** — no passwords, tokens, API keys, OAuth secrets, or session cookies in any file, artifact, or log
- **Do not use personal accounts** — personal Google, Amazon, Alza, LinkedIn, Upwork, or any personal account is forbidden for QA automation
- **Do not use production accounts** — production marketplace/e-commerce accounts are always blocked
- **Do not read `.env`, `.auth`, or `storageState` files** unless a future explicitly approved phase enables it
- **Do not run auth execution in Phase 4E** — login flows, session management, and account-based testing require a future explicit phase approval
- **Do not commit storageState** — `.auth/*.json` and `storageState*.json` must be gitignored and never committed
- **Do distinguish Amazon.com retail from Amazon Pay Sandbox** — retail account = always blocked; Pay Sandbox = future sandbox integration profile, blocked in Phase 4E
- **Do distinguish Alza.sk production from Alza staging/test** — production account = blocked; staging/test = future candidate with client-provided test account and explicit scope
- **Do not mark `safe_for_auth_execution=True`** — auth execution safety gate requires explicit human approval
- **Do not mark `safe_for_client_visibility=True`** for credential artifacts — redaction checklist must be completed by a human first

### Demo auth execution rules (Phase 4F)

- **Do not run demo auth without `--approve-demo-auth-execution`** — no subprocess, no credential injection, no storageState without explicit approval flag
- **Do not use auth profiles other than `saucedemo_demo_auth`** — no Alza, Amazon, Google, LinkedIn, Upwork, or Linear auth profiles in Phase 4F
- **Do not use personal accounts, production accounts, or client credentials** — `personal_account_used=False` and `production_account_used=False` are hardcoded
- **Do not inject credentials into command args** — demo credentials go into subprocess env only; never appear in command strings, logs, or artifacts
- **Do not read `.env`, `.auth`, or storageState files** — `DemoAuthRunner` builds its own safe env from the approved profile registry
- **Do not commit storageState** — storageState is gitignored under `outputs/<project_id>/09_auth/.auth/`; `approved_for_commit=False` always
- **Do not read storageState content** — only record the path reference; do not include content in reports or artifacts
- **Do not mark `safe_to_deliver=True`** — demo auth evidence is always internal-only; `approved_for_client_delivery=False` hardcoded
- **Do not run npm install or npx playwright install in Phase 4F** — toolchain setup is Phase 3C; if dependencies are missing, fail cleanly
- **Do not add Alza/Amazon/Google/Linear auth profiles** in any phase without explicit architecture review and spec update

### Architecture integrity

- **Do not replace `core/orchestrator.py`** without explicit architecture review
- **Do not add autonomous agent runtimes** (LangGraph, AutoGen, CrewAI, etc.) as runtime deps
- **Do not add browser automation** as a runtime dependency

---

## 6. Required Final Report Format

Every agent phase response must include:

```
## Changed files
## New files
## Tests run
## pytest result
## docs_audit result
## agent_readiness_audit result (if available)
## Safety boundary
## Secrets / redaction
## Generated artifacts
## Git status summary
## Intentionally not implemented
## Blockers (if any)
## Recommended next step
```

See `docs/AGENT_HANDOFF_TEMPLATE.md` for the full template.

---

## 7. Required Safety Phrase Declarations

Every agent phase report must explicitly state:

| Item | Required phrase (or equivalent) |
|---|---|
| URL fetching | "No URL fetching was performed." |
| Browser execution | "No browser execution was performed." |
| Credential use | "No credential use was performed." |
| External API calls | "No external calls were performed." |
| outputs/ staged | "outputs/ was not staged." |
| Secrets | "No raw secrets in generated artifacts." or "Secrets detected — redacted." |

If any of these actions were performed in a future approved phase, the report must name
the specific action, the URL or endpoint, the approval reference, and the result.

---

## 8. Phase Boundary Enforcement

Agents must respect phase boundaries defined in `docs/PHASE_CONTRACTS.md`.

- **Classify-only phases** (2A, 2B): no execution, no fetching, no scaffolding
- **Planning-only phases** (2C): no execution, no scaffolding, no external calls
- **Scaffold phases** (3A): no execution against live URLs
- **Execution phases** (4A+): require explicit approval checklist per run

When in doubt: do less, report more, ask.

---

## 9. Git Hygiene Before Any Commit

Before committing:

1. Run `git status` — confirm no `.env`, no `outputs/`, no secrets staged
2. Run `python -m pytest -q` — must pass
3. Run `python tools/docs_audit.py` — must pass
4. Run `python tools/agent_readiness_audit.py` — must pass
5. Stage only intended code/docs/tests files

Commit message format:

```
<type>: Phase <X> -- <summary>

<body with what changed and why>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`

---

## 10. Phase 4G — Scenario Execution Matrix Rules

Agents must follow these rules when proposing or evaluating test execution:

### Consult the matrix before proposing execution

- Before proposing any execution task, check `outputs/<project_id>/10_execution_matrix/EXECUTION_MATRIX_REPORT.json` (if present) to determine which lane applies.
- If no matrix artifact exists yet, run `python tools/build_execution_matrix.py --project-id <id>` first.
- Do not propose execution that falls outside an implemented, `allowed_now=True` lane.

### Routing rules (enforced by builder — agents must not bypass)

| Target type | Correct lane | Allowed now |
|---|---|---|
| SauceDemo (no auth) | `no_auth_demo_smoke` | Yes |
| Public read-only docs | `no_auth_public_readonly_smoke` | Yes |
| SauceDemo (with auth) | `demo_auth_smoke` | Yes |
| SauceDemo demo auth | `saucedemo_demo_auth` | Yes — Phase 5H |
| Practice site demo auth | `practice_site_demo_auth` | Yes — Phase 5H |
| Amazon public readonly (product/search/category) | `amazon_public_readonly` | Yes — Phase 5H (auth/cart/checkout blocked) |
| Alza public readonly (product/search/category) | `alza_public_readonly` | Yes — Phase 5H (auth/cart/checkout blocked) |
| Linear task source (API read-only) | `linear` provider | Yes — Phase 5H (`fetch_task_source.py`) |
| Dedicated test account | `dedicated_test_account_auth_future` | No — Phase 5A |
| Staging/client app | `staging_client_app_future` | No — Phase 5A |
| Production (read-only) | `production_readonly_future` | No — Phase 5B |
| Sandbox payment | `sandbox_payment_future` | No — Phase 5C |
| Task source integration (Jira, ClickUp, GitHub Issues) | `task_source_integration_future` | No — future phase |
| Real e-commerce auth / OAuth (Amazon auth, Alza auth, Google OAuth, LinkedIn, Upwork) | `strictly_blocked` | Never |

### Credential and account rules (never bypass)

- Never propose using personal accounts — `personal_account_allowed=False` always
- Never propose using production accounts — `production_account_allowed=False` always
- Never propose storing credentials in repo — `repo_storage_allowed=False` always
- Never propose logging credential values — `logging_allowed=False` always
- Never propose making credentials client-visible — `client_visible_allowed=False` always
- The dedicated test account plan is `safe_for_execution_now=False` — never treat it as execution authorization

### Scenario classification rules

- Classify task-source integration URLs (Linear, Jira, etc.) separately from test targets — they are **never** test execution targets
- Amazon Pay / payment sandbox URLs route to `sandbox_payment_future` — not `no_auth_demo_smoke`
- Alza, Amazon, Google OAuth, LinkedIn, Upwork — always `strictly_blocked`
- `localhost`/`127.0.0.1` URLs route to `no_auth_demo_smoke` with local-only note
- When unsure, route to `strictly_blocked` and surface it for human review

### Matrix artifact rules

- All `10_execution_matrix/` artifacts: `internal_only=True`, `client_visible=False`
- Matrix report is a planning document — `safe_for_execution_now=False` always
- Do not include matrix artifacts in client delivery packages

---

## 11. Phase 5AB — Runtime Secret Routing + Dedicated Test-Account Auth Rules

### Secret reference rules (never bypass)

- Never accept raw secret values via CLI flags (`--username`, `--password`, `--token`, `--secret`)
- Only env var **names** are accepted (`--username-env-var NAME`, `--password-env-var NAME`)
- Never read `.env`, `.env.local`, `.auth/*.json`, or existing storageState files
- Never log, print, or serialize env var values
- Never suggest storing credentials in chat messages, tickets, or repository files
- If credentials appear in a chat message, flag them immediately as a security incident — do not use them

### Execution gate rules

- All 9 security gates must pass before any subprocess runs (see SAFETY_RULES.md 5AB-8)
- Without `--approve-dedicated-auth-execution`: no subprocess, no env var values read, no execution
- Planning-only mode (`plan_runtime_secrets.py`) is always safe — no gates required
- `validate_intake()` never reads env values and never runs subprocess

### Allowed targets for Phase 5AB (agents must not propose others)

| Target category | Allowed now | Notes |
|---|---|---|
| `orangehrm_demo_auth` | Yes (with approval) | `https://opensource-demo.orangehrmlive.com` |
| `restful_booker_demo_auth` | Yes (with approval) | `https://restful-booker.herokuapp.com` |
| `staging` | Yes (with approval) | Requires `--client-scope-confirmed` |
| `client_test_environment` | Yes (with approval) | Requires `--client-scope-confirmed` |
| `dedicated_test_environment` | Yes (with approval) | Requires `--dedicated-test-account-confirmed` |
| `dedicated_test_account_custom_target` | Yes (with approval) | Custom approved target |

### Always-blocked in Phase 5AB

- `accounts.google.com`, `google.com/o/oauth2` — Google OAuth always blocked
- `amazon.com`, `pay.amazon.com`, `payments.amazon.com` — always blocked
- `alza.sk/cz/hu/at/de` — always blocked
- `linkedin.com`, `upwork.com` — always blocked
- Personal accounts — always blocked (`personal_account_confirmed` is a blocker)
- Production accounts — always blocked (`production_account_confirmed` is a blocker)

### Session artifact and delivery rules

- All `12_dedicated_auth/` artifacts: `internal_only=True`, `client_visible=False`
- StorageState: `approved_for_commit=False` always — never stage or commit `.auth/` contents
- `safe_to_deliver=False`, `approved_for_client_delivery=False` always
- `raw_credentials_logged=False`, `raw_credentials_serialized=False` always
- Do not include `11_runtime_secrets/` or `12_dedicated_auth/` in client delivery packages

---

## Section 12 — Phase 5E — API Auth Smoke Rules

### Allowed target profiles

| Profile | Base URL | Auth endpoint | Safe read |
|---|---|---|---|
| `restful_booker_public_api` | `https://restful-booker.herokuapp.com` | `POST /auth` | `GET /booking` |

### Rules

- **Only env var names accepted** — `--username-env-var NAME`, `--password-env-var NAME`.
  Raw credential values may never be passed as CLI args, stored in code, or logged.
- **Token masking required** — token returned by `/auth` is masked in all artifacts.
  Only `token_present` boolean is recorded. `token_logged=False` always.
- **No destructive API calls** — only `POST /auth` + optional `GET /booking` (read-only).
  No DELETE, no PUT booking update in Phase 5E.
- **Approval gate required** — `--approve-api-auth-execution` must be explicitly present.
  Without it: no env lookup, no network call.
- **Always-blocked URLs** — `accounts.google.com`, `amazon.com`, `alza.*`, `linkedin.com`, `upwork.com`.
- **Artifacts** — `outputs/<project_id>/13_api_auth/` only.
  `safe_to_deliver=False`, `approved_for_client_delivery=False` always.
- **Do not include `13_api_auth/` in client delivery packages.**

---

## Section 14 — Phase 5G — Google/OAuth Test Account Capability Rules

### Permissioned capability model

Google is **NOT globally unblocked.** Generic runners (`dedicated_auth_runner.py`,
`api_auth_runner.py`) continue to block `accounts.google.com`. Google is allowed
ONLY through the Phase 5G dedicated runner with explicit approval flags.

### Rules

- **Personal Google accounts → always blocked.** `personal_account_confirmed=True`
  produces an unconditional BLOCK regardless of all other approvals.
- **Production Google accounts → always blocked.** Same as above for `production_account_confirmed=True`.
- **CAPTCHA bypass → always blocked.** `captcha_bypass_allowed=False` hardcoded.
  Manual challenge solving during `manual_storage_state_capture` is the only path.
- **Anti-bot bypass → always blocked.** `anti_bot_bypass_allowed=False` hardcoded.
- **Stealth/undetected-browser as core path → never.** The system does not ship
  with bot-detection bypass libraries.
- **Raw secrets never via CLI flags.** `--password`, `--token`, `--cookie`,
  `--api-key`, `--username`, `--email`, `--service-account-json`, `--totp-seed`
  are blocked by all Phase 5G CLIs at startup.
- **storageState content never read by the system.** Path/metadata only.
- **Chrome profile content never read.** `dedicated_profile_context` mode requires
  an internal user-data-dir under `outputs/<project_id>/15_google_auth/user-data-dir/`.
- **Gmail/Drive content never read.** Read-only smoke verifies authentication state
  and page response only.
- **Writing/deleting Google account data → never.** No `send`, `delete`, `update`,
  or `share` actions.
- **storageState files never committed.** `.gitignore` enforces this.
- **Allowed target URL prefixes (https only):** `accounts.google.com`,
  `mail.google.com`, `drive.google.com`, `docs.google.com`, `myaccount.google.com`,
  `workspace.google.com`. URLs with `captcha`, `recaptcha`, `challenge`, `anti-bot`
  substrings are always blocked.
- **`safe_to_deliver=False` and `approved_for_client_delivery=False` always.**
- **Required approval flags for every executable mode:**
  `--approve-google-test-account`, `--google-test-account-confirmed`,
  `--dedicated-test-account-confirmed`.
- **Executable modes in Phase 5G:** `manual_storage_state_capture`, `storage_state_reuse`.
  All other modes (`cdp_attach`, `dedicated_profile_context`,
  `google_api_oauth_token_future`, `google_service_account_future`,
  `totp_test_account_future`, `mock_oauth_provider_future`) are planning-only.
- **Artifacts:** `outputs/<project_id>/15_google_auth/` only.
- **Do not include `15_google_auth/` in client delivery packages.**

---

## Section 14 — Phase 5I — Mobile Viewport + Visual Regression + GitHub OAuth Rules

### Rules

- **Mobile viewport runner accepts no credentials.**
  `MobileViewportRunner` never passes auth state, cookies, or secrets to Playwright.
  `credentials_used=False` and `auth_performed=False` are hardcoded.
- **Amazon/Alza mobile readonly uses the same gates as Phase 5H desktop.**
  Same blocked paths and dangerous selector scan apply to `amazon_mobile_readonly`
  and `alza_mobile_readonly` profiles.
- **Visual regression baselines are never committed.**
  `baselines_committed=False` hardcoded. Baselines are stored in `outputs/` (gitignored).
- **Visual regression never performs auth.**
  No credential flags accepted. Target URLs must match the allowed prefix list.
- **GitHub personal accounts are always blocked.**
  `personal_account_always_blocked=True` hardcoded. `--personal-account-confirmed` flag
  triggers an immediate block with no override.
- **GitHub production org accounts are always blocked.**
  `production_account_always_blocked=True` hardcoded. `--production-account-confirmed` flag
  triggers an immediate block with no override.
- **GitHub CAPTCHA bypass is always blocked.** `captcha_bypass_allowed=False` hardcoded.
- **GitHub storageState content is never read by Python code.**
  Only path existence and file size (metadata) are checked. `storage_state_content_read=False` hardcoded.
- **Raw GitHub secrets never in CLI args, logs, or artifacts.**
  Flags `--password`, `--token`, `--secret`, `--api-key`, `--cookie`, `--pat`,
  `--access-token`, `--bearer` are blocked at CLI entry.
- **Runtime scripts (`mobile.config.cjs`, `visual_regression.spec.ts`, `github_smoke.cjs`) are never committed.**
  These are gitignored and deleted or left in `outputs/` after execution.
- **`safe_to_deliver=False` in all Phase 5I artifacts.**
  No Phase 5I artifact is approved for client delivery without human review.
- **Artifacts:** `outputs/<project_id>/17_mobile_viewport/`, `18_visual_regression/`, `19_github_auth/` only.
- **Do not include any Phase 5I artifacts in client delivery packages.**

---

## Section 13 — Phase 5F — QA Evidence Report Rules

### Rules

- **Read-only** — `generate_qa_report.py` and `QAReportGenerator` must never invoke
  subprocess, `urllib.request`, `requests`, or any form of network call.
  Report generation is file I/O only.
- **No storageState reading** — `.auth/` directories must never be entered.
  The generator may check path existence but must not call `.read_text()` on
  storageState files. `storage_state_content_read=False` always.
- **Safety flags are unconditional** — `safe_to_deliver=False`, `approved_for_client_delivery=False`,
  `client_ready=False`, `execution_performed=False`, `human_review_required=True` cannot be
  changed via constructor arguments. They are hardcoded in `__post_init__` and `from_dict`.
- **Secret scan does not log values** — only env var names and finding descriptions may appear
  in `QA_REPORT_SECRET_SCAN.md`. Raw secret values must never be printed, stored, or returned.
- **No `--approve` flag** — Phase 5F is read-only. There is no approval gate to unlock.
  Adding an `--approve` flag is a defect.
- **Multi-source read only** — the generator reads from source project directories but must
  never write to them. All output goes to `outputs/<report_project_id>/14_qa_report/` only.
- **Artifacts** — `outputs/<project_id>/14_qa_report/` only.
  5 files: `QA_EVIDENCE_REPORT.json/md`, `QA_REPORT_REVIEW_CHECKLIST.md`,
  `QA_REPORT_SECRET_SCAN.json/md`.
- **Do not include `14_qa_report/` in client delivery packages.**

---

## Section 15 — Phase 5J — E2E Pipeline Runner + DB Smoke Rules

### Rules

- **Pipeline execution requires explicit approval flag.**
  `tools/run_e2e_pipeline.py` is blocked unless `--approve-pipeline-execution` is present.
  Plan mode (omitting that flag) is always safe — no subprocess is called.
- **Execution order is hardcoded and cannot be changed.**
  The fixed sequence `task_source → browser → api_smoke → google_auth → github_auth →
  mobile_viewport → visual_regression → db_smoke → qa_report` cannot be reordered.
- **Each module's own safety gates remain fully in effect via the pipeline runner.**
  The pipeline runner does not bypass module-level approval or safety checks.
- **Raw secrets are never accepted by the pipeline or DB smoke CLI.**
  Flags `--password`, `--token`, `--secret`, `--api-key`, `--cookie`, `--pat`,
  `--access-token`, `--bearer`, `--db-url`, `--connection-string`, `--dsn` block
  immediately with exit code 2.
- **DB connection strings passed via env var NAME only.**
  `--db-url-env-var` accepts only an env var name (`[A-Z][A-Z0-9_]{0,79}`). Raw URLs
  are rejected at the CLI and runner level. The resolved value is never logged.
- **Only read-only SQL is allowed.**
  `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `EXEC`, `EXECUTE`,
  `GRANT`, `REVOKE`, `MERGE`, `REPLACE`, `CALL`, `LOAD`, `IMPORT` — all blocked by
  word-boundary regex, even inside subqueries.
- **Only approved MongoDB operations are allowed.**
  Allowlist: `find`, `findOne`, `aggregate`, `count`, `countDocuments`,
  `estimatedDocumentCount`, `distinct`, `listCollections`, `listDatabases`.
  Validation happens before any driver connection.
- **Row limit is hard-capped at 100.** Default is 10.
- **`E2EPipelineRunner` does not replace existing orchestration layers.**
  It is a subprocess orchestration layer. `QAFactoryOrchestrator`, `WorkbenchController`,
  and `EvidenceManager` remain independent.
- **Safety invariants are unconditional.**
  `PipelineRunReport`: `raw_secrets_allowed=False`, `production_write_allowed=False`,
  `client_delivery_allowed=False`, `safe_to_deliver=False`, `human_review_required=True`.
  `DBSmokeReport`: + `destructive_db_actions_allowed=False`, `connection_string_logged=False`.
  All hardcoded in `__post_init__` AND `from_dict`.
- **Artifacts:** `outputs/<project_id>/20_e2e_pipeline/` and `21_db_smoke/` only.
- **Do not include any Phase 5J artifacts in client delivery packages.**

---

## Section 16 — Phase 5K — AI Intelligence Core Rules

### Rules

- **Raw input text is never stored.**
  `IntakeAgent.analyze()` stores only `raw_input_length` (integer). The original
  text never appears in `IntakeReport.to_dict()` output or any written artifact.
  `raw_input_stored=False` is hardcoded in `__post_init__` AND `from_dict`.
- **No credentials in any Phase 5K artifact.**
  `IntakeReport.credentials_in_output=False` is unconditionally hardcoded.
  No token, password, API key, or cookie may appear in any intake, oracle, or
  evidence intelligence artifact.
- **Test Oracle scenarios are not auto-executable.**
  `TestOracleReport.executable_without_approval=False` is hardcoded. All generated
  scenarios require human review and explicit approval before execution.
- **Evidence Intelligence is read-only.**
  `EvidenceIntelligenceReport.network_calls_made=False` and `execution_performed=False`
  are hardcoded. `EvidenceIntelligence.analyze()` only reads the local filesystem.
  No subprocess, no network, no DB calls.
- **All Phase 5K CLI tools block credential flags.**
  `--password`, `--token`, `--secret`, `--api-key`, `--cookie`, `--pat`,
  `--access-token`, `--bearer` → exit code 2 immediately.
- **Phase 5K is heuristic-only — no LLM calls.**
  `IntakeAgent` uses keyword scoring only. No LLM or external API is called.
  `IntakeReport.llm_calls_made` is always `False` in Phase 5K.
- **Phase 5K runners do not replace existing layers.**
  `IntakeAgent`, `TestOracle`, `EvidenceIntelligence` are AI planning layers.
  They do not replace `QAFactoryOrchestrator`, `WorkbenchController`, `EvidenceManager`,
  or any other existing orchestration component.
- **Safety invariants are unconditional.**
  All three report schemas have `safe_to_deliver=False` and `human_review_required=True`
  hardcoded in `__post_init__` AND `from_dict`.
- **Artifacts:** `22_intake/`, `23_test_oracle/`, `24_evidence_intelligence/` only.
- **Do not include any Phase 5K artifacts in client delivery packages.**

---

## Section 17 — Phase 5L — Desktop Browser Execution CLI Rules

### Rules

- **Credential flags are blocked before argument parsing.**
  `run_browser_execution.py` exits with code 2 on any blocked flag (`--password`,
  `--token`, `--secret`, `--api-key`, `--cookie`, `--pat`, `--access-token`, `--bearer`,
  `--db-url`, `--connection-string`, `--dsn`) before any other logic runs.
- **Ecommerce targets require dual approval — single flag is not sufficient.**
  Amazon.com and Alza.cz (`ecommerce_public_readonly`) require both
  `--approve-demo-execution` AND `--approve-public-readonly-execution`. This is by design.
- **`captcha_bypass_allowed=False` is hardcoded and non-negotiable.**
  Bot-check pages are handled with soft assertions. Do not attempt CAPTCHA bypass.
- **No personal or production accounts in any browser context.**
  No storageState injection, no cookie injection, no OAuth session reuse for personal/prod accounts.
- **Spec files use hardcoded URLs — never `process.env.BASE_URL` for site-specific specs.**
  Using `BASE_URL` in Amazon or Alza specs causes cross-site contamination when the runner
  sets the env var for a different target. Use `const BASE = 'https://...'` in every site spec.
- **Dual-viewport `test.skip()` guards are required.**
  Mobile assertions: `test.skip(vw >= 768, ...)`. Desktop assertions: `test.skip(vw < 1024, ...)`.
  Removing these causes false failures when the desktop runner executes mobile spec files.
- **`tsconfig.json` must have `noEmit: true`, `rootDir: "."`, `lib: ["ES2020", "DOM"]`.**
  Omitting `rootDir` causes a VS Code language server error that masks all `document` type errors.
  `outDir` must not be set (use `noEmit` instead — Playwright does not compile via tsc).
- **Smoke tests are read-only. No writes to the target site.**
  No checkout, no cart, no form POST, no account creation, no order placement.
- **Do not include `playwright-report/` or `test-results/` in client delivery packages.**

---

## Section 18 — Phase 5M — API Contract Importer + CI/CD Builder Rules

### Rules

- **Credential flags are blocked before argument parsing.**
  All three Phase 5M CLI tools exit with code 2 on `--password`, `--token`, `--secret`,
  `--api-key`, `--cookie`, `--pat`, `--access-token`, `--bearer`, `--db-url`,
  `--connection-string`, `--dsn`.
- **No network calls during import.**
  `APIContractImporter` reads only local files. No URL fetching is permitted.
- **Only safe_readonly endpoints generate active test stubs.**
  `requires_approval` endpoints are skipped (commented). `blocked_by_default` endpoints
  are excluded entirely. This classification cannot be overridden via CLI flags.
- **Generated tests are not auto-executable.**
  `GeneratedTestsReport.executable_without_approval=False` hardcoded in `__post_init__`
  AND `from_dict`. No generated spec file may be executed without human review.
- **CI/CD configs are planning artifacts — no auto-commit, no auto-push.**
  `CICDConfig.auto_pr_creation_allowed=False` and `client_repo_writeback_allowed=False`
  hardcoded. Generated files must be manually copied to the target repository.
- **No secrets in generated CI/CD configs.**
  Use CI/CD platform secret stores. Never embed raw credentials in workflow YAML.
- **Safety invariants are unconditional.**
  `APIContractReport`, `GeneratedTestsReport`, `CICDConfig`, `CICDManifest` all have
  safety flags hardcoded in `__post_init__` AND `from_dict`. Passing overriding values
  in `from_dict` is silently ignored.
- **Artifact dirs: `25_api_contract/`, `26_generated_tests/`, `27_cicd/` only.**

---

## Section 19 — Phase 5N — Accessibility + Performance + Passive Security Rules

- **Default mode is always `planning_only` (no network).**
  All three runners generate Playwright TypeScript specs locally with no network calls.
  `status` field is always `"planning_only"` until explicit approval flags are passed.

- **Approved execution requires explicit dual-flag for accessibility and performance.**
  `--execute` + `--approve-public-readonly-execution` + `--approve-browser-execution`.
  Missing either flag → `ValueError` raised; agent must not attempt workarounds.

- **Passive security approved execution is HEAD-only.**
  `--execute` + `--approve-public-readonly-execution` → single passive HEAD request.
  No active scan, no fuzzing, no auth bypass — these flags exit 1.

- **Safety flags are injection-proof.**
  `read_only`, `active_scan_allowed`, `exploit_attempts_allowed`, `auth_bypass_allowed`,
  `load_testing_allowed` are hardcoded in both `__post_init__` and `from_dict`.

- **Delivery pack must reflect execution status honestly.**
  `planning_only` → report shows "Generated checks only; execution requires approval."
  Never represent skeleton output as completed testing.

- **Artifact dirs: `29_accessibility/`, `30_performance/`, `31_passive_security/` only.**

---

## Section 20 — Phase 5O — Flaky Test Analyzer + Self-Healing Rules

- **Static analysis only by default — no code modifications.**
  `analyze()` and `analyze_selectors()` are read-only. `code_modification_allowed=False` hardcoded.

- **Auto-fix is always blocked.**
  `--auto-fix` exits 1. No mechanism exists to auto-replace selectors.

- **Applying proposals requires explicit dual approval.**
  `--apply-proposals` alone exits 1.
  Requires both `--apply-proposals` AND `--approve-code-modification`.
  `apply_proposals()` raises `ValueError` without the flag.

- **Applied proposals are TODO comments only — not code replacements.**
  Even in approved mode, proposals insert `// HEAL-xxx:` comments at affected lines.
  The developer reads and implements the suggested change manually.

- **Safety flags are injection-proof.**
  `read_only`, `auto_apply_changes`, `code_modification_allowed`, `production_write_allowed`,
  `human_review_required` hardcoded in `__post_init__` + `from_dict`.

- **Artifact dir: `32_flaky_test_analyzer/` only.**

---

## Section 21 — Phase 6 — MCP Server Rules

- **MCP is adapter only — core stays core.**
  `integrations/mcp/tool_handlers.py` calls existing core modules. No business logic in the MCP layer.

- **All tools default to planning_only / analysis_only.**
  No network or browser by default. Execution requires per-request approval flags.

- **No credentials accepted or returned.**
  `_check_blocked_params()` blocks any argument with credential/password/token/api_key/secret.

- **apply_self_healing_fixes defaults to dry_run=True.**
  Files modified only when `approve_code_modification=True` AND `dry_run=False`.

- **approved_for_client_delivery is always False.**
  MCP cannot grant delivery approval — human sign-off always required.

- **human_review_required=True in every response.**
  Hardcoded — cannot be overridden by any tool argument.

- **Adapter location: `integrations/mcp/` only.**
  `tool_handlers.py` (testable without mcp package) + `server.py` (requires mcp).

---

## Section 22 — Phase 6.1 — One-Command Client Audit Rules

- **`ClientAuditInputs.__post_init__` is not negotiable.**
  All safety invariants are re-enforced after object construction. Callers cannot opt out.

- **`ClientAuditResult.__post_init__` is not negotiable.**
  `approved_for_client_delivery=False` is always set. The orchestrator cannot approve delivery.

- **Mode determines modules; flags determine execution depth.**
  Mode selects which modules run. Approval flags select planning vs. execution within each module.

- **`build_plan()` must be called and shown before `run()`.**
  The CLI shows the preflight plan before running any modules, so the operator knows what will happen.

- **Blocked flags are checked before argparse.**
  `--auto-approve-all`, `--skip-human-review`, `--force-deliver` exit 1 before any parsing.

---

## Section 23 — Phase 6-R — MCP Demo Workflow Rules

- **Demo runner is read/analysis-only by default.**
  `tools/run_mcp_demo_workflow.py --no-write` produces no file artifacts.

- **Blocked flags are checked before argparse.**
  `--approve-delivery`, `--skip-review`, `--force-apply` exit 1 before any tool is called.

- **Step 7 intentionally omits approval — blocked result is the expected outcome.**
  `apply_self_healing_fixes` is always called without `approve_code_modification` in demo mode.
  Test assertion: `status == "blocked"`.

- **All 7 tools must return `human_review_required=True`.**
  Demo tests assert this for all results — no exceptions.

- **Demo output is platform-safe ASCII only.**
  No Unicode characters (checkmarks, dashes, bullets) in any print output.

---

## Section 24 — Phase 6.2 — Structured Finding Schema + Risk Matrix Rules

- **No fake findings for planning_only modules.**
  Finding adapters must only emit `Finding` objects when real evidence exists.
  `blocked_count=0, requires_approval_count=0, parse_errors=[]` must return `[]`.
  `secret_scan_passed=True` must return `[]`.

- **Risk scoring is deterministic.**
  `risk_score(f) = severity_weight * confidence_weight`. No randomness, no timestamps in sort keys.
  `RiskMatrix.sorted_by_risk()` uses `(-risk_score, id)` — stable across identical inputs.

- **Structured findings are informational only.**
  `structured_findings` and `risk_summary` in `ClientAuditResult` do not grant approvals.
  All Phase 6.1 safety invariants from `__post_init__` remain enforced.

- **Finding IDs are project-scoped and deterministic.**
  Format: `CATEGORY-TYPE-PROJECTID-NNN`. No UUID or random suffix.

- **`findings: int` backward-compat field is preserved.**
  New structured fields are added alongside; the existing `findings` count is unchanged.

---

## Section 25 — Phase 6.3 — Client Delivery Report Rules

- **`client_report.md` is always a draft.**
  `generate_client_delivery_report()` always includes a DRAFT notice and states
  `approved_for_client_delivery = False`. No caller argument suppresses this.

- **Report generation is read-only.**
  `generate_client_delivery_report()` and `write_client_delivery_report()` must not
  modify any field of `ClientAuditResult` or `ClientAuditPlan`.

- **No fake findings in the report.**
  The report renders only what is in `result.structured_findings`. Empty list → explains
  what was not tested. Never invents risks or placeholder findings.

- **`write_client_delivery_report()` is called only when `write_files=True`.**
  `--no-write` runs must not produce a `client_report.md` file.

- **Report language is client-oriented, not system log.**
  Finding descriptions use natural language. Module names are translated to human labels.
  Technical internal status values are translated before display.

---

## Phase 7A — Auth Capability Planner Agent Rules

- **Auth capability planning is classification only.**
  `AuthCapabilityPlanner` classifies methods and writes planning artifacts.
  It does not open browsers, make network requests, read credential files, or execute auth flows.

- **Raw secrets are never accepted via CLI.**
  Blocked flags (`--password`, `--secret`, `--token`, `--cookie`, `--totp-seed`,
  `--access-token`, `--bearer`, `--client-secret`, `--api-key`) exit 1 immediately.
  Use `--*-env-var NAME` to pass env var names only.

- **Safety invariants survive deserialization.**
  `AuthCapabilityInputs.__post_init__` and `AuthCapabilityPlan.__post_init__` always reset
  all safety flags regardless of what `from_dict()` or caller code passes.
  An agent must not attempt to override `personal_account_allowed`, `captcha_bypass_allowed`,
  or any other safety invariant after construction.

- **Account flags confirm dedicated test accounts, not personal accounts.**
  `--has-google-account`, `--has-github-account`, `--has-microsoft-account`,
  `--has-dedicated-test-account` confirm that a dedicated test account exists.
  An agent must never pass these flags when the only available account is personal or production.

---

## Phase 7B — Auth Strategy Selector Agent Rules

- **Strategy selection is decision-only — no execution.**
  `AuthStrategySelector` selects the best method from a capability plan.
  It does not open browsers, make network requests, read credential files, or execute auth flows.

- **`safe_to_execute=True` is informational, not a launch signal.**
  An agent must not automatically launch a runner when `safe_to_execute=True`.
  Human review is always required before proceeding to Phase 7C/7D runners.

- **Safety invariants survive deserialization.**
  `AuthStrategyDecision.__post_init__` always resets all safety flags regardless of what
  `from_dict()` or caller code passes. An agent must not attempt to set `safe_to_execute=True`
  manually or override any safety invariant after construction.

- **`next_runner` is a planning label, not a runnable command.**
  The value of `next_runner` (e.g. `"google_oauth_runner"`) names the runner that *should*
  be used in a future phase. It is not a currently executable module unless explicitly
  implemented and approved.

---

## Related Documents

- [`PHASE_CONTRACTS.md`](PHASE_CONTRACTS.md) — phase boundaries and contracts
- [`ARTIFACT_CONTRACTS.md`](ARTIFACT_CONTRACTS.md) — artifact paths and ownership
- [`AGENT_HANDOFF_TEMPLATE.md`](AGENT_HANDOFF_TEMPLATE.md) — final report template
- [`SAFETY_RULES.md`](SAFETY_RULES.md) — non-negotiable rules
- [`DOCS_MANIFEST.md`](DOCS_MANIFEST.md) — all docs registry
- [`APPROVAL_MODEL.md`](APPROVAL_MODEL.md) — risk levels and approval gates

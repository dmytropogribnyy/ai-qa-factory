# Safety Rules — Guided QA Automation Workbench

**Version:** 5.3.0  
**Updated:** 2026-05-26

These rules are non-negotiable. No flag, no argument, and no configuration overrides them without an explicit human decision documented outside the system.

---

## Hard rules

### Rule 1 — Do not confuse task URL with target application URL

A brief may contain multiple URLs:
- A **task URL** points to where the work was described (Jira ticket, Linear issue, Notion page, Upwork job post).
- A **target URL** points to the application under test (staging SaaS, e-commerce site, API endpoint).

These must be classified separately before any action. A task URL is never a test target. A target URL is never treated as task context.

**Violation:** Using a Jira ticket URL as the base URL for Playwright tests, or treating a staging URL as a source of project requirements.

### Rule 2 — Do not run against an unknown external URL

If the system or a generated script references an external URL that has not been explicitly classified and approved, that URL must not be contacted.

"It looks like a staging URL" is not sufficient. The URL must be:
1. Named explicitly in the agreed project scope
2. Confirmed by the client as a test target
3. Approved via the checklist in [`RUNBOOK.md`](RUNBOOK.md) section 4

**Violation:** Running `npx playwright test` with a BASE_URL that was not explicitly approved for testing.

### Rule 3 — Do not run against a target URL without approval

Even when the target URL is correctly classified and confirmed, automated execution against it requires explicit approval per run.

Approval means:
- `--approve` flag passed with awareness of what it unlocks
- Section 4 checklist in RUNBOOK.md completed
- Staging confirmed as separate from production

**Violation:** Running `npx playwright test` against any staging URL without completing the checklist and passing `--approve`.

### Rule 4 — Do not run against production without explicit read-only approval

Production environments require a higher level of approval than staging:
- Written confirmation from the client that production testing is in scope
- Explicit read-only scope defined (no write, no mutation, no state change)
- Stop conditions agreed in writing

**Violation:** Any automated run against a production URL, even for smoke tests, without written client authorization.

### Rule 5 — Do not test payment flows unless sandbox is confirmed

Payment flow testing requires:
- Written confirmation that the payment provider is in sandbox/test mode
- Test card numbers confirmed (Stripe test cards, etc.)
- No real money involved — ever

This must be confirmed **in writing by the client** before any payment-adjacent test runs.

**Violation:** Running checkout tests that call a payment API without written sandbox confirmation.

### Rule 6 — Do not use credentials unless explicitly approved

Credentials (usernames, passwords, API tokens, session cookies) used in tests must:
- Be synthetic test accounts created specifically for testing
- Never be real user accounts or real production credentials
- Live in `.env` files only — never in briefs, test specs, reports, or commits
- Be confirmed by the client as safe-to-use test accounts

**Violation:** Pasting a real user password into a test file. Using a production API token in automation. Including credentials in a client report.

### Rule 7 — Do not claim tests were executed unless there is evidence

The workbench generates test plans, strategies, and scaffolds. It does not execute tests unless explicitly run.

Never write or approve a client-facing report that implies tests were run when they were not. Evidence means:
- Playwright test results (HTML report, JSONL results)
- Screenshots or traces from an actual run
- A log entry showing execution

**Violation:** Delivering a `TEST_RESULTS.md` that says "All 45 tests passed" when only the scaffold was generated.

### Rule 8 — Do not include internal notes or prompts in client-facing reports

Internal artifacts include:
- System prompts and LLM instructions
- Agent reasoning notes
- Mock-mode placeholder text
- Routing decisions and internal scoring
- `HUMAN_REVIEW_REQUIRED.md` checklists
- `QUALITY_GATE_REPORT.md` errors and warnings

These must never appear in a document delivered to a client. Client reports are a clean, professional subset.

**Violation:** Delivering a report that contains `[MOCK OUTPUT]` placeholders, internal quality gate warnings, or agent prompt fragments.

### Rule 9 — Do not auto-deliver client-facing reports

No client-facing report is sent automatically. Every delivery is a manual action:
1. Open the generated report
2. Complete the `HUMAN_REVIEW_REQUIRED.md` checklist
3. Manually edit the report (remove internals, verify claims, soften overclaims)
4. Send it yourself

**Violation:** Any configuration, script, or workflow that automatically emails, posts, or submits a report to a client or platform.

### Rule 10 — Do not perform destructive actions automatically

Destructive actions include:
- Deleting records or data in any environment
- Modifying production configuration
- Triggering irreversible state changes (order cancellation, user deletion, billing changes)
- Security testing actions (injection, auth bypass attempts)

These require explicit written scope from the client and a separate approval decision per action type.

**Violation:** A generated test script that deletes test users or orders without an explicit "destructive scope" confirmation.

---

## Credential and authentication safety

These rules extend the hard rules above specifically for credential and auth flow testing. They are encoded in the `core/schemas/credentials.py`, `core/schemas/auth_flow.py`, and `core/schemas/redaction.py` schema foundation (Phase 1B-auth). Runtime enforcement comes in a later phase.

### Raw credentials must never be stored

Passwords, tokens, cookies, API keys, OTP codes, recovery codes, session IDs, and JWTs must never appear in:
- `QAFactoryState` or any state snapshot
- Schema fields (only the **name** of the env var may be stored, e.g. `TEST_USER_PASSWORD`)
- Markdown reports
- JSON logs or JSONL event logs
- Screenshots, traces, videos
- Any client-facing artifact

**Violation:** Storing a password string in `CredentialReference.secret_names`. That field holds env var names only.

### Credentials require explicit approval before use

`CredentialReference.requires_approval_before_use = True` is the immutable default. A credential is not used until `approved_for_use = True` is set via an explicit approval decision. This maps to risk level `payment_or_auth` in the approval model.

**Violation:** Running a login flow with a credential whose `approved_for_use` is `False`.

### Auth testing uses test accounts only

Only synthetic test accounts created specifically for testing are permitted. Real user accounts and production credentials are blocked by `CredentialPolicy.allow_production_credentials = False` (default).

**Violation:** Using a real user's email/password in any automated test.

### Production auth testing requires explicit production read-only approval

Any auth check against a production environment requires:
- `CredentialPolicy.allow_production_credentials = True` (explicit override)
- Approval at risk level `production_read_only`
- Written client confirmation
- Read-only scope confirmed — no state changes

**Violation:** Running a login test against production without explicit written client scope.

### Destructive account actions are blocked by default

`CredentialPolicy.prohibit_destructive_account_actions = True` is the default. Actions in the forbidden list (`change_password`, `delete_account`, `change_billing`, `create_real_payment`, `modify_production_data`) require a separate explicit approval at risk level `destructive_account_action` or `security_sensitive`.

**Violation:** Any automated test that changes a user's password or deletes an account without a separate explicit destructive-scope approval.

### Web and mobile auth — additional rules

- **OAuth2 / social login** must use test accounts only. Never use a real personal Google, Apple, or GitHub account in automation.
- **Email magic link / email OTP** automation must use an approved test mailbox only. No real user inboxes.
- **TOTP automation** may use a test TOTP seed only. The seed must never appear in logs, reports, screenshots, or traces — only the env var name referencing it.
- **SMS OTP** should default to manual or semi-automated entry unless an approved test provider (e.g. Twilio test mode) is explicitly configured.
- **Mobile biometric auth** must not be automated unless a test device or simulator in safe mock mode is explicitly approved for that step.
- **App surface context** (`app_surface` field on `CredentialReference` and `AuthFlowPlan`) must be set before planning auth flows so approval gates can apply the correct risk level.

### Reports and evidence must redact secrets

`CredentialPolicy.mask_secrets_in_outputs = True` and `block_client_delivery_if_secrets_detected = True` are defaults. Any report containing a detectable secret pattern must be blocked from client delivery until redaction is confirmed.

**Violation:** Delivering a `TEST_RESULTS.md` that contains a bearer token found in a network log trace.

---

## QA Strategy output safety (Phase 2C)

These rules apply to artifacts generated by `QAStrategyPlanner` and written to `outputs/<project_id>/02_strategy/`.

### Strategy artifacts must preserve blocked actions and approval requirements

Any action that is `blocked=True` in the `ProjectBlueprint` must remain blocked in the `QAStrategy` output. The planner must not silently drop, bypass, or weaken blocked actions or required approvals that were identified in Phase 2B.

**Violation:** A strategy artifact that describes credential use or URL access without noting that approval is required.

### `client_ready` must remain `False` for all Phase 2C outputs

`QAStrategy.client_ready = False` is a hard invariant. No Phase 2C artifact is ever delivered to a client directly. All strategy output requires human review before any delivery.

**Violation:** Any code path that sets `client_ready = True` inside `QAStrategyPlanner.build_strategy()`.

### Strategy artifacts must not make execution claims

Strategy artifacts describe what should be tested and how — they must not claim that any test was executed, any URL was fetched, or any credential was used. All execution claims require evidence from an actual test run (Phase 4A).

**Violation:** A `QA_STRATEGY.md` that contains text like "tests were run against staging" or "login was verified."

---

## Framework Scaffold safety (Phase 3A)

These rules apply to scaffold files generated by `FrameworkScaffoldGenerator` and written to `outputs/<project_id>/03_framework/playwright/`.

### Scaffold generation is file generation only — no execution

Phase 3A generates plain text files. It does not run any browser, any npm command, any TypeScript compilation, or any test. `execution_allowed = False` is a hard invariant in `FRAMEWORK_SCAFFOLD.json`.

**Violation:** Any code path in `FrameworkScaffoldGenerator` that calls `subprocess.run`, imports `playwright`, or calls `npm`/`npx`.

### Generated files must not contain hardcoded URLs or secrets

All URL references in generated files must use `process.env.BASE_URL` or `http://localhost:3000` as a placeholder only. All credential references must use `process.env.TEST_USERNAME`, `process.env.TEST_PASSWORD`, `process.env.API_BASE_URL`. Real values and real credentials must never appear in generated files.

**Violation:** A generated `playwright.config.ts` that contains `baseURL: 'https://staging.myclient.com'`.

### Auth and API specs must be skipped by default

`tests/auth/auth-placeholder.spec.ts` must include `test.skip(!process.env.TEST_USERNAME ...)` at the describe level. `tests/api/api-placeholder.spec.ts` must include `test.skip(!process.env.API_BASE_URL ...)`. These guards prevent accidental execution before credentials and URLs are approved.

**Violation:** An auth spec that runs without checking for `TEST_USERNAME`/`TEST_PASSWORD`.

### Checkout and admin specs are blocked until explicit approval

Ecommerce checkout specs and admin panel specs must use `test.skip(true, '...')` with a clear message stating what approval is required. These specs must never run automatically.

**Violation:** A checkout spec that runs any payment-adjacent test without written sandbox confirmation.

### `client_visible` and `requires_review` must not be changed by the generator

`FrameworkScaffold.client_visible = False` and `requires_review = True` are hard defaults. The generator must not set these to values that would allow the scaffold to be delivered or executed without human review.

**Violation:** Any code path that sets `client_visible = True` or `execution_allowed = True` inside `FrameworkScaffoldGenerator`.

---

## Static scaffold validation safety (Phase 3B)

These rules apply to `ScaffoldValidator` in `core/scaffold_validator.py`.

### Validator is static inspection only — no execution of any kind

Phase 3B reads local files and checks their content. It does not run npm, npx, TypeScript,
Playwright, or any subprocess. All six execution flags in `ScaffoldValidationReport` remain
`False` always, regardless of the scaffold contents or check results.

**Violation:** Any code path in `ScaffoldValidator` that calls `subprocess.run`, imports `playwright`,
calls `npm`, `npx`, or opens any network connection.

### `safe_to_execute_tests` is always `False` in Phase 3B

Static validation alone is never sufficient to grant test execution permission.
`ScaffoldValidationReport.safe_to_execute_tests` must be `False` always.
Test execution requires explicit human approval (Phase 4A), not just passing static checks.

**Violation:** Any code path that sets `safe_to_execute_tests = True` inside `ScaffoldValidator`.

### Validation artifacts must not echo scaffold secrets

The validation report describes whether secrets were found, but must not reproduce them.
Check messages may say "secret detected in tests/auth.spec.ts" but must not include the secret value.

**Violation:** `STATIC_VALIDATION_REPORT.json` or `STATIC_VALIDATION_REPORT.md` containing
a literal API key, JWT, or hardcoded password copied from the scaffold.

---

## Toolchain validation safety (Phase 3C)

These rules apply to `ToolchainValidator` in `core/toolchain_validator.py` and the
`python tools/validate_toolchain.py` CLI.

### `--approve-toolchain` is required for any command execution

Without the `--approve-toolchain` CLI flag, `ToolchainValidator` executes no subprocess
commands. All commands are recorded with `status="skipped"` and `validation_status="blocked"`.
This is the safe default — inspection only, no execution.

**Violation:** Any code path in `ToolchainValidator` that calls `subprocess.run` when
`approved=False`.

### Only allowlisted local commands may run

When `--approve-toolchain` is provided, only three commands are permitted:
`npm install`, `npm run typecheck`, and `npx playwright test --list`.
All other commands — including `playwright install`, `playwright test`, `npm test`,
`npm run test`, headed/headless browser launch, `curl`, `wget`, `git clone` — are blocked
regardless of approval.

**Violation:** Running `npx playwright test` (without `--list`), any headed browser command,
or any command that opens a network connection to an external URL.

### `safe_to_execute_tests` is always `False` in Phase 3C

Passing toolchain validation (npm install success, typecheck pass, test list discovered)
does **not** grant permission to execute tests. `safe_to_execute_tests = False` is a hard
invariant. Test execution requires a separate explicit approval gate (Phase 4A).

**Violation:** Any code path that sets `safe_to_execute_tests = True` inside `ToolchainValidator`.

### The four safety invariants are hardcoded — never cleared

`browser_execution_performed`, `external_url_used`, `credentials_used`, and
`safe_to_execute_tests` are set to `False` at report creation and re-asserted at the end of
`validate_toolchain()`. No command result, exit code, or approval state can override them.

**Violation:** Any code path that conditionally sets any of these four fields to `True`.

### Subprocess environment must be sanitized before command execution

Before passing the environment to any subprocess, keys matching the pattern
`PASSWORD|SECRET|TOKEN|API_KEY|PRIVATE_KEY|CREDENTIAL|AUTH|COOKIE|SESSION` must be stripped,
and `BASE_URL` / `API_BASE_URL` must be overridden with `http://localhost:3000` values.
Real credential values must never reach subprocess.

**Violation:** Passing `os.environ` directly (without stripping) to `subprocess.run`.

---

## Client scenario fixture safety (Phase 3B-SCENARIOS)

These rules govern the `fixtures/client_scenarios/` layer.

### Real public URLs in fixtures do not authorize execution

Fixture files in `public_demo_targets/`, `real_public_readonly/`, and `high_risk_marketplace_readonly/`
may contain real URLs (e.g. `https://www.saucedemo.com`, `https://www.amazon.com`). These URLs
are **planning references only**. They do not:
- Authorize URL fetching during classification, planning, scaffold, or validation
- Remove the per-run approval requirement for any external target
- Make any external site an approved test target by default

**Violation:** Treating `target_url: https://www.saucedemo.com` in a fixture as permission to
fetch that URL or run tests against it.

### Fixture files must never contain real credentials

All `synthetic/` fixtures use fake values only. `public_demo_targets/` fixtures may reference
published demo credentials as reference text (e.g. `standard_user / secret_sauce`) but these must
appear only as documentation — never as active scaffold values, never committed as `.env` values.

**Violation:** A fixture file or test that reads a credential value and passes it to a CLI or scaffold.

### Task management URLs are requirement sources, not test targets

When a Linear issue URL, Jira ticket URL, ClickUp URL, or similar task management URL appears in
input as `task_url`, it must be classified as `task_source` in the blueprint — not `target_application`.
The Workbench must never fetch these URLs, call their APIs, or write back comments/status without
explicit approval.

**Violation:** Using a Linear issue URL as `BASE_URL` in a Playwright config, or calling the
Linear API to fetch issue content without approval.

---

## External integration safety

These rules govern optional integrations such as n8n, Make, Zapier, Slack, Jira, and similar systems. Encoded in `core/schemas/integration.py` as schema defaults. Runtime enforcement is planned for a later phase.

### External integration calls are disabled by default

`IntegrationPolicy.allow_outbound_events = False` and `allow_inbound_webhooks = False` are the defaults. No integration sends any external request without explicit approval.

**Violation:** Any code path that sends an HTTP request to an external integration endpoint without `IntegrationPolicy.allow_outbound_events = True` and an explicit approval decision.

### No real webhook URLs or API keys in state, docs, or logs

`IntegrationEndpoint.url_ref` and `auth_ref_id` are reference labels only (e.g. env var names). Real webhook URLs containing secrets, n8n API keys, Slack tokens, Jira tokens, or similar must never appear in project state, schema fields, Markdown reports, JSONL logs, or any committed file.

**Violation:** A webhook URL containing a secret token stored in `state.json` or `factory.jsonl`.

### Integration payloads must be redacted before sending

Before any integration event is delivered externally, its payload must be reviewed and redacted using the `RedactionReport` process. `IntegrationPolicy.redact_sensitive_payloads = True` is the default.

**Violation:** Sending a payload containing a client's email address, test credentials, or internal agent notes to an external endpoint.

### Client-facing data must be reviewed before external delivery

Integration delivery (Google Drive upload, Jira ticket creation, Slack message) does not replace the final human review required by Rule 9. A human must approve the content before it is sent externally.

**Violation:** Automatically posting a generated test strategy to a Slack channel without human review.

### AI fallback events should trigger human review

When `AIFallbackEvent` is recorded (primary LLM unavailable, fallback used), the output quality may be affected. Any integration event generated from fallback output must be flagged and reviewed before delivery.

---

## Readiness, Evidence, Reporting, and Delivery Preview safety (Phase 4ABC)

These rules apply to Phase 4ABC modules and CLI tools:
`ExecutionReadinessPlanner`, `EvidenceManager`, `ReportDraftBuilder`,
`DeliveryPreviewBuilder`, `ScenarioBatchEvaluator`.

### No execution in Phase 4ABC

Phase 4ABC is readiness/foundation/draft/preview/evaluation only.
No browser execution, no Playwright tests, no target URL fetching, no credential use.

**Violation:** Any Phase 4ABC code path that opens a browser, runs Playwright, or contacts a target URL.

### `approved_for_execution` and `approved_for_browser_execution` are always `False`

In Phase 4ABC, these flags default to `False` and must not be set to `True`.
`ExecutionReadinessReport.from_dict` explicitly forces these back to `False` to prevent
deserialized data from overriding them.

**Violation:** Any Phase 4ABC code that sets `approved_for_execution=True` without a future explicitly approved execution phase.

### Evidence is internal-only by default

`EvidenceManager` always sets `client_visible=False` on new evidence records.
`EvidenceCollection.ready_for_client_review=False` always.
`EvidenceQualityGate.approved_for_client_view=False` always.

**Violation:** Any code that sets `client_visible=True` on evidence without redaction confirmation.

### Reports are draft-only and not approved for delivery

`ReportDraftBuilder` never sets `approved_for_delivery=True`.
`ReportQualityChecklist.client_ready=False` and `safe_to_deliver=False` always in Phase 4ABC.
Client report must always contain a DRAFT disclaimer and a "no browser execution" statement.

**Violation:** Any code that sets `approved_for_delivery=True` or `safe_to_deliver=True` without explicit human approval.

### Delivery preview never creates packages or zips

`DeliveryPreviewBuilder` inspects artifacts and builds a manifest only.
`package_created=False`, `zip_created=False`, `safe_to_package=False` always.
No files are copied, archived, or sent.

**Violation:** Any code that creates a zip file, tar archive, or copies artifacts to a delivery package in Phase 4ABC.

### Scenario evaluation reads local fixtures only

`ScenarioBatchEvaluator` reads only `fixtures/client_scenarios/**/*.md`.
`external_calls_performed=False` always. `evaluation_performed_without_execution=True` always.
No URL in any fixture is fetched.

**Violation:** Any code in `ScenarioBatchEvaluator` that opens a URL, calls an API, or executes code.

---

## Controlled demo/local/public-readonly execution safety (Phase 4D)

These rules apply to `BrowserExecutionRunner` and `tools/run_demo_execution.py`:

### Rule 4D-1: Explicit approval flag required

No subprocess or browser execution without `--approve-demo-execution` or `--approve-public-readonly-execution`.

**Violation:** Any code path in `BrowserExecutionRunner` that calls `subprocess.run` without first verifying approval flag.

### Rule 4D-2: Allowlist-only commands

Only these commands may pass to subprocess:
- `npx playwright test --list`
- `npx playwright test tests/smoke --reporter=list`
- `npx playwright test tests/smoke --reporter=html,list`

**Violation:** Any other command, or any command with `--headed`, `--ui`, unrestricted test path, or credential args.

### Rule 4D-3: Always-blocked targets

Alza.sk, Amazon.com, and Linear.app are always blocked regardless of approval flag or target category.
playwright.dev is blocked unless `--readonly-profile playwright_docs_readonly` + `--approve-public-readonly-execution` are both present.

**Violation:** Any code that allows execution against these domains.

### Rule 4D-4: Production/high-risk/task-source categories always blocked

`production`, `high_risk_marketplace_readonly`, and `task_source` are always blocked even with approval flags.
`real_public_readonly` is blocked unless `readonly_profile=playwright_docs_readonly` with public-readonly approval.

**Violation:** Any code that allows execution against these categories.

### Rule 4D-5: No credentials, no auth, no payment, no destructive actions

Phase 4D must not inject credentials, read `.env`, run auth/checkout/payment flows, or perform destructive writes.

**Violation:** Any code that reads `.env`, injects `TEST_USERNAME`/`TEST_PASSWORD` with real values, or executes auth-gated tests (auth execution is not implemented in Phase 4D — planned for a future explicitly approved phase).

### Rule 4D-6: Delivery flags always False

`safe_to_deliver=False`, `approved_for_client_delivery=False`, `client_delivery_created=False` must remain False via `__post_init__` and `from_dict`.

**Violation:** Any `BrowserExecutionReport` or schema path that sets delivery flags to True.

### Rule 4D-7: No npm install, no playwright install

Phase 4D must not run `npm install` or `npx playwright install`. Toolchain setup is Phase 3C responsibility.

**Violation:** Any CLI tool or runner code that calls npm install or playwright install.

---

## Consequences of rule violations

| If a rule is violated during a run | Required action |
|---|---|
| Staging URL accessed without approval | Stop the run, document what happened, re-run with proper approval |
| Client report contains internal notes | Regenerate the report, do not send the contaminated version |
| Credentials appear in test files | Rotate credentials immediately, remove from files, add to `.gitignore` |
| Evidence claimed without execution | Do not deliver. Re-run the actual tests. |
| Payment test without sandbox confirmation | Stop immediately. Confirm sandbox mode before any further run. |

---

## Credential Safety Rules (Phase 4E)

**4E-1. No real credentials in the repository.**
Do not add passwords, API tokens, OAuth secrets, session cookies, or any real secret value to any file committed to the repository. Env var names are acceptable references; actual values are never acceptable.

**4E-2. No personal accounts.**
Personal Google, Amazon, Alza, LinkedIn, Upwork, or any other personal account must never be used for QA automation. Always use dedicated test accounts provided by the client.

**4E-3. No production accounts.**
Production marketplace or e-commerce accounts (Amazon.com retail, Alza.sk production) are always blocked. Amazon Pay Sandbox and Alza staging/test accounts are future candidates — blocked in Phase 4E.

**4E-4. No .env reading without explicit approval.**
Do not read `.env`, `.env.local`, `.env.production`, `.auth/*.json`, or `storageState` files programmatically unless a future explicitly approved phase enables it.

**4E-5. storageState must never be committed.**
Playwright `storageState` / `.auth/*.json` files capture authentication state and must be treated as secrets. They must be in `.gitignore`, never committed, never delivered to clients, and always `internal_only=True`.

**4E-6. No client-visible credentials.**
Credential values, session tokens, or auth state must never appear in client-facing reports, delivery packages, or public artifacts. All credential-adjacent evidence is `internal_only=True` by default.

**4E-7. Auth execution requires explicit future phase approval.**
Running auth-gated Playwright tests (login flows, session management, account-based testing) requires a separate future explicit phase approval. Not approved in Phase 4E.

**4E-8. Sandbox credentials require separate future phase approval.**
Amazon Pay Sandbox, Alza staging, and similar sandbox credentials require their own explicit phase approval plus official merchant/test account setup. Not approved in Phase 4E.

**4E-9. Agents must distinguish Amazon retail from Amazon Pay Sandbox.**
Amazon.com retail/marketplace account = always blocked production account.
Amazon Pay Sandbox = future sandbox integration profile, blocked in Phase 4E, allowed only with official merchant setup in a future explicit phase.

**4E-10. Agents must distinguish Alza retail from Alza staging/test.**
Alza.sk production retail account = blocked production e-commerce account.
Alza staging/test account = future candidate, requires client-provided test account and explicit phase scope.

---

## Demo Auth Execution Safety Rules (Phase 4F)

These rules govern demo auth execution. They extend the hard rules above for approved public demo auth only.

**4F-1. No auth execution without `--approve-demo-auth-execution`.**
The flag must be present. Without it: no subprocess, no credential injection, no storageState creation.

**4F-2. Only `saucedemo_demo_auth` profile allowed in Phase 4F.**
No Alza, Amazon, Google, LinkedIn, Upwork, or Linear auth profiles may be added or used.
No personal accounts. No production accounts. No client credentials.

**4F-3. Credentials injected into subprocess env only — never command args, logs, or artifacts.**
Public demo credentials (SauceDemo standard_user/secret_sauce) are universally published values.
They must still be masked in stdout/stderr excerpts and must never appear in JSON/MD artifacts.

**4F-4. storageState only under `outputs/<project_id>/09_auth/.auth/`.**
Never under repository root, scaffold source root, or any path outside outputs/.
storageState content must not be read or included in reports.
`approved_for_commit=False` always. `client_visible=False` always.

**4F-5. `real_credentials_used=False` always — hardcoded in schema `__post_init__` and `from_dict`.**
Public demo credentials do not make `real_credentials_used=True`. The field reflects use of personal, production, or client credentials only.

**4F-6. No personal accounts, production accounts, or client credentials in Phase 4F.**
`personal_account_used=False` and `production_account_used=False` are hardcoded.

**4F-7. `safe_to_deliver=False` and `approved_for_client_delivery=False` always.**
Demo auth evidence is internal-only. Client delivery requires a separate explicit human approval.

**4F-8. No payment/checkout/order creation, no destructive/admin writes.**
Auth smoke is restricted to `tests/auth` path only. No ecommerce/admin/regression paths.

**4F-9. No npm install, no npx playwright install in Phase 4F.**
Toolchain setup is Phase 3C responsibility. If dependencies are missing, fail cleanly and report it.

**4F-10. Agents must not run auth without `--approve-demo-auth-execution`.**
Agents must not inject credentials without approval. Agents must not read `.env` or `.auth` files.
Agents must not expose storageState content. Agents must not create client delivery packages.

---

## Phase 4G — Scenario Execution Matrix and Dedicated Test Account Planning Rules

**4G-1. All execution must route through the Scenario Execution Matrix.**
Agents must consult the matrix before proposing execution. No execution bypasses lane classification.

**4G-2. Blocked scenarios remain blocked even if the user provides credentials.**
The `strictly_blocked` lane is a policy block, not an authorization check. Credentials do not change routing.

**4G-3. No personal credentials regardless of scenario or user input.**
`personal_account_allowed=False` always. No exceptions.

**4G-4. No production credentials regardless of scenario or user input.**
`production_account_allowed=False` always. No exceptions.

**4G-5. No repo-stored secrets regardless of phase or scenario.**
`repo_storage_allowed=False` always. Vault reference or runtime input only for future lanes.

**4G-6. Alza/Amazon production auth remains blocked.**
Alza.sk production, Amazon.com retail, Google personal OAuth, LinkedIn, Upwork are in `strictly_blocked`.

**4G-7. Amazon Pay Sandbox is future Phase 5C — not allowed now.**
Amazon Pay Sandbox routes to `sandbox_payment_future`. No execution until Phase 5C explicit approval.

**4G-8. Linear/Jira/ClickUp are task sources, not app-under-test.**
Task source URLs route to `task_source_integration_future`. Not allowed now. Phase 5D.

**4G-9. Dedicated test accounts require future explicit approval.**
`dedicated_test_account_auth_future` and `staging_client_app_future` are not allowed now. Phase 5A.

**4G-10. `safe_for_execution_now=False` in dedicated test-account plan always.**
No execution of dedicated test-account lanes without a future explicitly approved phase.

---

## Phase 5AB — Runtime Secret Routing + Dedicated Test-Account Auth Execution Rules

**5AB-1. No raw secret values in CLI args, ever.**
`--username`, `--password`, `--token`, `--secret`, `--api-key`, `--key` flags are not accepted.
Only env var **names** (`--username-env-var`, `--password-env-var`) are accepted.
Raw secret values must never appear in command history, shell history, process arguments, logs, or artifacts.

**5AB-2. No .env file reading in Phase 5AB.**
Env var values are read from `os.environ` only — never from `.env`, `.env.local`, or any file.
Agents must never suggest setting credentials in `.env` files for this phase.

**5AB-3. No existing storageState reading.**
`DedicatedAuthRunner` never reads pre-existing `.auth/*.json` or `storageState` files.
Previously captured auth state is out of scope for this phase.

**5AB-4. No personal accounts.**
`personal_account_confirmed=True` is a blocker, not an approval.
`personal_account_used=False` is hardcoded — cannot be changed via constructor or from_dict.

**5AB-5. No production accounts.**
`production_account_confirmed=True` is a blocker, not an approval.
`production_account_used=False` is hardcoded — cannot be changed via constructor or from_dict.

**5AB-6. Google OAuth strictly blocked.**
`accounts.google.com` and `google.com/o/oauth2` are always blocked regardless of approval flags, credentials provided, or target category. This applies to all OAuth flows, not just login.

**5AB-7. Alza/Amazon/LinkedIn/Upwork always blocked.**
`alza.sk`, `alza.cz`, `alza.hu`, `alza.at`, `alza.de`, `amazon.com`, `pay.amazon.com`,
`payments.amazon.com`, `linkedin.com`, `upwork.com` are always blocked.

**5AB-8. `--approve-dedicated-auth-execution` is required for all subprocess execution.**
Without the flag: no subprocess, no env var value reading, no Playwright invocation, no storageState creation. Planning and validation-only mode is safe by default.

**5AB-9. Env var names must match `^[A-Z][A-Z0-9_]{0,79}$`.**
Email addresses, lowercase names, spaces, JWT prefixes, and shell variable syntax are rejected.
This prevents injection attacks and ensures the env var reference is unambiguous.

**5AB-10. Env var values are read only after all safety gates pass.**
Gates 1–7 are checked without reading any env var values. Gate 8 reads values only to verify they exist (truthy check). Values are only materialized inside the approved subprocess call.

**5AB-11. Secret masking is applied to all subprocess stdout/stderr.**
`_mask()` replaces any env var value found in output with `[REDACTED]`.
Masking is applied before any excerpt is stored in the execution report or artifacts.

**5AB-12. `raw_credentials_logged=False` and `raw_credentials_serialized=False` always.**
These fields are hardcoded in `DedicatedAuthExecutionReport.__post_init__` and `from_dict`.
No code path can set them to True.

**5AB-13. StorageState stays internal — never committed, never delivered.**
`DedicatedAuthSessionArtifact.approved_for_commit=False` and `client_visible=False` always.
StorageState is written only under `outputs/<project_id>/12_dedicated_auth/.auth/` (gitignored).

---

## Phase 5E — API Auth Smoke Safety Rules

**5E-1. No raw secrets accepted via CLI flags.**
`run_api_auth_smoke.py` accepts only `--username-env-var NAME` and `--password-env-var NAME`.
Flags `--password`, `--username`, `--token`, `--secret`, `--api-key` are detected and rejected immediately.

**5E-2. Credentials used as HTTP request body only — not in URL, headers, logs, or artifacts.**
The POST body `{"username": val, "password": val}` is constructed in memory.
The request body is never logged, serialized, or stored in any artifact.

**5E-3. Token masking is applied to all response content before any excerpt is stored.**
`_mask()` replaces token value with `[REDACTED]` before any string enters the execution report.
`token_logged=False` and `token_serialized=False` are hardcoded in `APIAuthExecutionReport`.

**5E-4. Approval gate required — no env lookup, no network call without explicit flag.**
`--approve-api-auth-execution` must be present. Without it: gate 1 blocks immediately, no env vars read.

**5E-5. Personal and production accounts are always blocked.**
`personal_account_confirmed=True` → gate 2 blocks.
`production_account_confirmed=True` → gate 3 blocks.

**5E-6. Only allowlisted target profiles are permitted.**
Unknown `--target-profile` → gate 4 blocks. Current allowed: `restful_booker_public_api`.

**5E-7. Strictly blocked URL patterns.**
Same list as Phase 5AB: `accounts.google.com`, `google.com/o/oauth2`, `amazon.com`, `pay.amazon.com`,
`alza.sk/cz/hu/at/de`, `linkedin.com`, `upwork.com`.

**5E-8. No destructive API calls in Phase 5E.**
Only `POST /auth` and optional `GET /booking` are executed. No DELETE, no PUT booking update.

**5E-9. `safe_to_deliver=False` and `approved_for_client_delivery=False` always.**
Hardcoded in `APIAuthExecutionReport.__post_init__` and `from_dict`.

**5AB-14. `safe_to_deliver=False` and `approved_for_client_delivery=False` always.**
Dedicated auth evidence is internal-only. Client delivery requires separate explicit approval.

**5AB-15. No payment/checkout/order creation, no destructive/admin writes.**
Phase 5AB is auth smoke and auth setup only. Ecommerce/admin/regression/security paths are blocked.

**5AB-16. No scraping, crawling, load testing, or security testing.**
Phase 5AB is limited to login/session verification on approved targets.

**5AB-17. Agents must not share credentials in chat, tickets, or messages.**
If credentials were accidentally shared in a message, assume they are compromised.
Instruct immediate password rotation. Do not use shared credentials.

---

## Phase 5G — Google/OAuth Test Account Capability Safety Rules

**5G-1. Google is not globally unblocked.**
Generic runners (`dedicated_auth_runner.py`, `api_auth_runner.py`) continue to block
`accounts.google.com` and `google.com/o/oauth2`. Google is allowed ONLY via the Phase 5G
dedicated runner with explicit approval flags.

**5G-2. Personal Google accounts are always blocked.**
`personal_account_confirmed=True` → BLOCK regardless of all other approvals.
This rule cannot be overridden via CLI or schema.

**5G-3. Production Google accounts are always blocked.**
`production_account_confirmed=True` → BLOCK regardless of all other approvals.

**5G-4. CAPTCHA and anti-bot bypass are always blocked.**
`captcha_bypass_allowed=False` and `anti_bot_bypass_allowed=False` are hardcoded in
`__post_init__` and `from_dict`. The system never bypasses Google's reCAPTCHA or any
anti-bot challenge. The user solves them manually during `manual_storage_state_capture`.

**5G-5. Stealth/undetected-browser is not a core path.**
The system does not ship with `playwright-extra`, `undetected-chromedriver`, or any
bot-detection bypass library. `stealth_live_login_as_core_path=False` hardcoded.

**5G-6. Raw secrets are never accepted via CLI flags.**
`--password`, `--secret`, `--token`, `--cookie`, `--api-key`, `--username`, `--email`,
`--service-account-json`, `--totp-seed` — all blocked by all three Phase 5G CLIs at
startup. Only env var name references and storageState paths are accepted.

**5G-7. storageState content is never read by the system.**
`storage_state_content_read=False` hardcoded. The planner records only path existence
and file size. Playwright loads storageState directly; Python never reads the file.

**5G-8. Browser profile content is never read by the system.**
`browser_profile_content_read=False` hardcoded. The main Chrome profile is never
copied or read. `dedicated_profile_context` mode requires a user-data-dir under
the internal output directory only.

**5G-9. storageState files must never be committed.**
`.gitignore` excludes `**/15_google_auth/.auth/`, `**/google-storageState*.json`,
runtime `*.cjs` scripts, and `smoke_redacted*.png` screenshots.

**5G-10. Allowed Google target URL prefixes.**
Only `https://` URLs starting with `accounts.google.com`, `mail.google.com`,
`drive.google.com`, `docs.google.com`, `myaccount.google.com`, or `workspace.google.com`
are accepted as Google targets. URLs containing `captcha`, `recaptcha`, `challenge`,
or `anti-bot` are always blocked.

**5G-11. Account email label allowlist.**
The system maintains an allowlist of dedicated test-account labels in
`core/google_auth_capability.py:_PERMITTED_TEST_ACCOUNT_LABELS`. Unknown labels
produce a warning and require manual review before execution.

**5G-12. Reading Gmail/Drive content is blocked.**
The read-only smoke only verifies authentication state, page response, and may
take a redacted screenshot. It does NOT read emails, files, or any account content.

**5G-13. Writing/deleting Google account data is blocked.**
No `send`, `delete`, `update`, or `share` actions on any Google account. The runner
performs navigation + screenshot only.

**5G-14. `safe_to_deliver=False` and `approved_for_client_delivery=False` always.**
Hardcoded in `GoogleAuthEvidenceReport.__post_init__` and `from_dict`. Phase 5G
artifacts are internal-only and require human review before any client-facing use.

**5G-15. TOTP / 2FA handling.**
TOTP automation is planning-only in Phase 5G (`totp_test_account_future`). 2FA on
the dedicated test account is solved manually during `manual_storage_state_capture`.
Raw TOTP seeds must never appear in CLI args, JSON, MD, logs, or reports — only
env var name references via `--totp-seed-env-var`.

---

## Phase 5F — QA Evidence Report Safety Rules

**5F-1. No execution in report generation.**
`generate_qa_report.py` and `QAReportGenerator` must never invoke subprocess, urlopen,
requests, or any network call. Generation is read-only file I/O only.

**5F-2. storageState content must never be read.**
The generator must not read `.auth/storageState.json` or any file under `.auth/`.
Existence checks are allowed; content reads are not. `storage_state_content_read=False` always.

**5F-3. All safety flags are hardcoded False in `__post_init__` and `from_dict`.**
`safe_to_deliver`, `approved_for_client_delivery`, `client_ready`, `execution_performed`,
`network_calls_performed`, `raw_credentials_in_report`, `raw_tokens_in_report`,
`storage_state_content_read` — all unconditionally set to False (or True for
`human_review_required`) regardless of constructor arguments.

**5F-4. Secret scan must not print, log, or store secret values.**
The secret scan checks if known env var values appear in report content.
Only the env var name and finding description may appear in output — never the value.

**5F-5. No `--approve` flag is allowed in the CLI.**
Phase 5F is read-only. There is no execution gate to unlock. If `--approve` appears
in `generate_qa_report.py`, it is a defect.

**5F-6. Multi-source aggregation must not modify source artifacts.**
`QAReportGenerator` reads source artifacts but must never write to source project
directories. All output goes to `outputs/<report_project_id>/14_qa_report/` only.

---

## Phase 5H — Multi-Target Expansion + Task Source Integration Safety Rules

**5H-1. Linear is a task source — never an app-under-test.**
`linear.app` remains in `_ALWAYS_BLOCKED_DOMAINS` in `browser_execution_runner.py`.
The only permitted Linear integration is the read-only GraphQL API via `TaskSourceFetcher`.
No browser navigation to Linear. No status changes, comments, or webhooks.

**5H-2. Raw Linear API tokens are never accepted via CLI flags or stored in artifacts.**
`--token-env-var` accepts only an env var **name** (format `^[A-Z][A-Z0-9_]{0,79}$`).
Flags `--token`, `--api-key`, `--secret`, `--password`, `--linear-token`, `--bearer` are rejected.
Token values must never appear in logs, reports, JSON artifacts, or Markdown files.

**5H-3. Linear writeback is always blocked.**
`writeback_allowed=False`, `status_change_allowed=False`, `comment_allowed=False`,
`webhook_allowed=False` — all hardcoded in `TaskSourceFetchPolicy.__post_init__` and `from_dict`.
No code path can set any of these to True.

**5H-4. Amazon/Alza public readonly is path-gated.**
`amazon_public_readonly` and `alza_public_readonly` profiles are allowed only for product,
search, and category pages. The following paths are hard-blocked regardless of profile or
approval: `/signin`, `/ap/`, `/gp/buy`, `/cart`, `/checkout`, `/account`, `/order`, `/orders`,
`/your-account`, `/wishlist/`.

**5H-5. Amazon/Alza auth flows remain blocked.**
No storageState capture, no CDP attach, and no dedicated profile context is allowed for
Amazon or Alza domains. These domains are excluded from all auth runners.

**5H-6. CDP Attach requires a user-launched browser session.**
The system attaches to an already-running Chrome with `--remote-debugging-port`.
The user logs in manually (including CAPTCHA/2FA). The system never automates login,
never reads passwords, and never bypasses CAPTCHA in CDP attach mode.

**5H-7. Dedicated Profile Context requires an internal user-data-dir.**
The `user_data_dir` for `dedicated_profile_context` mode must be inside the approved
internal output directory. Arbitrary filesystem paths are rejected.

**5H-8. `client_delivery_allowed=False` in all Phase 5H artifacts.**
`TaskSourceFetchReport.client_delivery_allowed=False` hardcoded. Task source artifacts
are for internal use only and require human review.

---

---

## Phase 5I — Mobile Viewport + Visual Regression + GitHub OAuth Safety Rules

**5I-1. Mobile viewport runner accepts no credentials.**
`MobileViewportRunner` never passes auth state, cookies, usernames, or passwords to the
Playwright subprocess. `credentials_used=False` and `auth_performed=False` are hardcoded
in `MobileViewportExecutionReport.__post_init__` and `from_dict`.

**5I-2. Amazon/Alza mobile readonly paths are gated identically to desktop (Phase 5H).**
`amazon_mobile_readonly` and `alza_mobile_readonly` profiles apply the same blocked paths
(`/signin`, `/cart`, `/checkout`, `/account`, `/order`, etc.) and the same dangerous
selector scan as the Phase 5H desktop profiles. No relaxation for mobile.

**5I-3. Visual regression baselines are never committed.**
`baselines_committed=False` is hardcoded. Baselines are stored in
`outputs/<project_id>/18_visual_regression/baselines/` which is gitignored.
Visual regression specs and config files generated at runtime are also gitignored.

**5I-4. Visual regression never performs auth.**
`VisualRegressionRunner` does not accept any credential flags. `credentials_used=False`
and `auth_performed=False` are hardcoded. Target URLs must match an allowed prefix list.

**5I-5. GitHub personal accounts are always blocked.**
`GitHubAuthCapability.personal_account_always_blocked=True` hardcoded. Providing
`--personal-account-confirmed` blocks execution immediately — there is no override.

**5I-6. GitHub production org accounts are always blocked.**
`GitHubAuthCapability.production_account_always_blocked=True` hardcoded. Providing
`--production-account-confirmed` blocks execution immediately — there is no override.

**5I-7. GitHub CAPTCHA bypass is always blocked.**
`captcha_bypass_allowed=False` hardcoded. The runner may detect a CAPTCHA challenge
and must block — it never attempts to bypass.

**5I-8. GitHub storageState content is never read by Python code.**
`storage_state_content_read=False` hardcoded. The runner passes the `storageState` path
to the Playwright script but never calls `.read_text()` on it. Only path existence and
file size (metadata) are checked.

**5I-9. Raw GitHub secrets never appear in CLI args, logs, or artifacts.**
Flags `--password`, `--token`, `--secret`, `--api-key`, `--cookie`, `--pat`,
`--access-token`, `--bearer` are blocked at CLI entry. Token values must never appear
in JSON artifacts, Markdown reports, or log output.

**5I-10. GitHub smoke runtime scripts are never committed.**
`github_smoke.cjs` is a runtime-only generated script (gitignored). It is deleted or
left in `outputs/` after execution. It must never be committed to the repository.

**5I-11. `safe_to_deliver=False` in all Phase 5I artifacts.**
`MobileViewportExecutionReport`, `VisualRegressionReport`, `GitHubAuthEvidenceReport` —
all set `safe_to_deliver=False` and `human_review_required=True` unconditionally.
No Phase 5I artifact is approved for client delivery without human review.

---

---

## Phase 5J — E2E Pipeline Runner + DB Smoke Safety Rules

**5J-1. Pipeline execution requires explicit approval.**
`E2EPipelineRunner.run()` is blocked unless `approve_pipeline_execution=True`.
The plan method (`plan()`) is always safe and never calls any subprocess.

**5J-2. Execution order is fixed and cannot be reordered.**
The pipeline always runs modules in the hardcoded sequence: `task_source → browser →
api_smoke → google_auth → github_auth → mobile_viewport → visual_regression → db_smoke →
qa_report`. No config flag can change this order.

**5J-3. Each module's own safety gates remain fully in effect.**
The pipeline runner does not bypass any module-level approval or safety check.
A module that requires `--approve-browser-execution` still requires it when invoked
via the pipeline runner.

**5J-4. Raw secrets are never accepted by the pipeline CLI.**
Flags `--password`, `--token`, `--secret`, `--api-key`, `--cookie`, `--pat`,
`--access-token`, `--bearer`, `--db-url` are blocked at CLI entry (exit code 2).
Any of these flags triggers an immediate block with no override.

**5J-5. DB smoke accepts connection strings via env var NAME only.**
`--db-url-env-var` must be an env var name matching `[A-Z][A-Z0-9_]{0,79}`. Raw
PostgreSQL, MySQL, or MongoDB URLs are rejected at the CLI and at the runner level.
The env var value is read from `os.environ` at runtime and never logged, echoed, or
stored in any artifact. `connection_string_logged=False` is hardcoded.

**5J-6. Only read-only SQL is allowed.**
`validate_sql()` enforces a word-boundary regex. The following keywords block execution
regardless of context (including subqueries and SQL injection attempts):
`INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `CREATE`, `TRUNCATE`, `EXEC`, `EXECUTE`,
`GRANT`, `REVOKE`, `MERGE`, `REPLACE`, `CALL`, `LOAD`, `IMPORT`. Empty queries are also blocked.

**5J-7. Only approved MongoDB operations are allowed.**
`validate_mongo_operation()` enforces an explicit allowlist: `find`, `findOne`,
`aggregate`, `count`, `countDocuments`, `estimatedDocumentCount`, `distinct`,
`listCollections`, `listDatabases`. All other operations are blocked before any driver
connection is attempted.

**5J-8. Row limit is hard-capped at 100.**
`DBSmokeRunner` enforces `MAX_ROW_LIMIT = 100`. Any `row_limit` above 100 is silently
capped to 100. The default is 10. This prevents accidental full-table reads.

**5J-9. DB driver absence produces a `blocked` result, not an error.**
If `psycopg2`, `mysql-connector-python`, or `pymongo` is not installed, the runner
returns `execution_status="blocked"` with a blocker message that includes the install
command. No exception propagates to the caller.

**5J-10. `destructive_db_actions_allowed=False` is hardcoded.**
`DBSmokeReport.destructive_db_actions_allowed=False` is set unconditionally in
`__post_init__` AND `from_dict`. It cannot be overridden via constructor or deserialization.

**5J-11. `safe_to_deliver=False` in all Phase 5J artifacts.**
`PipelineRunReport` and `DBSmokeReport` both set `safe_to_deliver=False` and
`human_review_required=True` unconditionally. No Phase 5J artifact is approved for
client delivery without human review.

**5J-12. `E2EPipelineRunner` does not replace existing orchestration layers.**
`E2EPipelineRunner` is a subprocess orchestration layer only. It does not replace
`QAFactoryOrchestrator` (AI/LLM), `WorkbenchController` (Phase 2A), or
`EvidenceManager` (Phase 4B). These layers remain independent and unchanged.

---

## Phase 5K Safety Rules

**5K-1. Raw input text is never stored in any artifact.**
`IntakeAgent.analyze()` stores only `raw_input_length` (an integer count), never the
original text. `IntakeReport.raw_input_stored=False` is set in `__post_init__` AND
`from_dict`. Any serialization of `IntakeReport` that shows the raw text is a bug.

**5K-2. `credentials_in_output=False` is hardcoded in `IntakeReport`.**
Set unconditionally in `__post_init__` AND `from_dict`. No credential material
(passwords, tokens, API keys) may appear in any Phase 5K artifact.

**5K-3. `executable_without_approval=False` is hardcoded in `TestOracleReport`.**
Test Oracle scenarios are planning artifacts only. They must never be auto-executed
without explicit human review and approval. Set unconditionally in `__post_init__` AND `from_dict`.

**5K-4. `network_calls_made=False` and `execution_performed=False` are hardcoded in `EvidenceIntelligenceReport`.**
`EvidenceIntelligence.analyze()` is read-only file analysis only. It never makes
subprocess, network, or DB calls. Both flags set unconditionally in `__post_init__` AND `from_dict`.

**5K-5. `safe_to_deliver=False` and `human_review_required=True` in all Phase 5K artifacts.**
`IntakeReport`, `TestOracleReport`, and `EvidenceIntelligenceReport` all set these
fields unconditionally. No Phase 5K artifact is approved for client delivery without human review.

**5K-6. Phase 5K CLI tools block credential flags.**
`run_intake_agent.py`, `run_test_oracle.py`, and `run_evidence_intelligence.py` all
reject `--password`, `--token`, `--secret`, `--api-key`, `--cookie`, `--pat`,
`--access-token`, `--bearer` with exit code 2 before any parsing occurs.

**5K-7. Phase 5K runners do not make LLM calls.**
All classification and analysis is heuristic-only in Phase 5K. `IntakeReport.llm_calls_made`
is an informational field (not safety-hardcoded) but is always `False` in Phase 5K operation.
LLM integration is planned for a later phase under separate safety constraints.

---

## Phase 5L Safety Rules

**5L-1. Credential flags are blocked at entry, before any parsing.**
`run_browser_execution.py` checks for `--password`, `--token`, `--secret`,
`--api-key`, `--cookie`, `--pat`, `--access-token`, `--bearer`, `--db-url`,
`--connection-string`, `--dsn` and exits with code 2 before any argparse invocation.

**5L-2. Ecommerce targets require dual approval.**
Amazon.com and Alza.cz are classified as `ecommerce_public_readonly`. They require
both `--approve-demo-execution` AND `--approve-public-readonly-execution` to be passed
simultaneously. A single flag is insufficient and the runner falls back to plan-only mode.

**5L-3. `captcha_bypass_allowed=False` is hardcoded and cannot be changed.**
No CAPTCHA bypass, no anti-bot bypass, no headless fingerprint spoofing is permitted.
Bot-check pages must be handled by soft assertions (`console.warn`, `toBeGreaterThanOrEqual(0)`).

**5L-4. No personal or production accounts.**
`personal_accounts_blocked=True` and `production_accounts_blocked=True` are hardcoded.
No Google, GitHub, Amazon, or other OAuth session may be injected into the browser context.

**5L-5. Smoke tests are read-only only.**
No checkout, no cart, no form submission, no payment, no login, no search with PII.
Spec files must be audited before execution if modified outside the approved scaffold pattern.

**5L-6. `test.skip()` guards protect dual-viewport correctness.**
Mobile assertions must skip on desktop viewport (`vw >= 768`). Desktop assertions must
skip on mobile viewport (`vw < 1024`). Removing these guards is a correctness violation.

**5L-7. Hardcode site URLs in site-specific spec files.**
Never use `process.env.BASE_URL` in Amazon or Alza spec files. The runner sets `BASE_URL`
to the current target, causing cross-site contamination. Use `const BASE = 'https://...'`.

---

## Phase 5M Safety Rules

**5M-1. No network calls during API contract import.**
`APIContractImporter.analyze()` reads only local files. Passing a URL as `--spec-file`
is not blocked at the CLI level but will fail with a file-not-found error — by design.
Never add URL-fetch logic without a separate safety review.

**5M-2. Credential flags are blocked at entry, before any parsing.**
`import_api_contract.py`, `generate_api_tests.py`, `build_cicd_config.py` all block
`--password`, `--token`, `--secret`, `--api-key`, `--cookie`, `--pat`, `--access-token`,
`--bearer`, `--db-url`, `--connection-string`, `--dsn` with exit code 2.

**5M-3. Only safe_readonly endpoints get active test stubs.**
`APITestGenerator` generates active `test(...)` blocks only for endpoints classified as
`safe_readonly`. `requires_approval` endpoints appear as commented-out skip stubs.
`blocked_by_default` endpoints are excluded entirely from generated specs.

**5M-4. `executable_without_approval=False` is hardcoded in `GeneratedTestsReport`.**
All generated test files are planning artifacts. No generated spec may be auto-executed
without human review. Set unconditionally in `__post_init__` AND `from_dict`.

**5M-5. `auto_pr_creation_allowed=False` and `client_repo_writeback_allowed=False` hardcoded.**
CI/CD configs are planning artifacts only. The builder does not commit, push, or create
PRs. Generated files must be manually copied to the target repository and reviewed.

**5M-6. No secrets or credentials in generated CI/CD configs.**
`CICDBuilder` must never embed API keys, tokens, passwords, or connection strings in
generated workflow files. Secrets must be referenced via CI/CD platform secret stores
(e.g., `${{ secrets.MY_SECRET }}` in GitHub Actions).

**5M-7. `blocked_by_default` classification is a hard gate.**
Endpoints matching payment, billing, refund, admin, delete, deactivate, ban, suspend,
purge, or destroy path terms are classified `blocked_by_default` and must not appear
in any generated test file as an executable test case.

---

## Phase 5P safety rules

**5P-1. `approved_for_client_delivery=False` is hardcoded and cannot be bypassed.**
`ClientDeliveryManifest.__post_init__` sets this unconditionally. No CLI flag can override it.
The `--approve` flag is blocked with exit code 1.

**5P-2. `auto_send_to_client=False` is hardcoded.**
The delivery pack generator never sends artifacts to clients automatically.
The `--auto-send` flag is blocked with exit code 1.

**5P-3. Secret scan always runs before ZIP creation.**
`SecretScanner.scan()` runs on the delivery directory before `zipfile.ZipFile` is opened.
The `--skip-secret-scan` flag is blocked with exit code 1.
Files matching blocked patterns (storagestate, .env, credential, cookie, token, password, etc.)
are excluded from the ZIP even if somehow present in the delivery directory.

**5P-4. `Delivery_Checklist.md` has all items unchecked by default.**
All checklist items use `- [ ]` syntax. No item is pre-checked. Human sign-off is required.

**5P-5. Report content must never contain raw credentials.**
Generated report content (QA_Report.md, Bug_Report.md, etc.) must not contain:
`password:`, `api_key:`, `token=`, or any credential-like value patterns.
Validated programmatically in `TestArtifactContent`.

**5P-6. `SecretScanResult.scan_passed` is computed, not injected.**
`__post_init__` recomputes `scan_passed = len(blocked_files) == 0`.
Passing `scan_passed=True` with non-empty `blocked_files` is overridden.

---

## Phase 5M-R safety rules

**5MR-1. DELETE method is always `blocked_by_default`.**
`classify_endpoint` checks `method == "DELETE"` first, before any path inspection.
DELETE is inherently destructive; no path term can override this.

**5MR-2. Fixture specs must not contain real credentials or real service URLs.**
Demo fixture files under `fixtures/demo_specs/` must use placeholder domains
(e.g., `petstore.example.com`, `risky.example.com`) — never real endpoints.

**5MR-3. Generated smoke content must not include `test()` blocks for blocked endpoints.**
Programmatic test: scan generated content for lines containing `test(` and a blocked
path term (e.g., `charge`, `DELETE`) that are not comment lines. Must be zero matches.

**5MR-4. CI/CD hardening invariants are verified by automated tests, not just documentation.**
`TestCICDHardening` in `test_phase5mr_demo_workflow.py` asserts programmatically that
generated workflow content contains no passwords, API keys, deploy steps, git push, or
PR creation commands.

---

## Phase 5N — Accessibility + Performance + Passive Security Safety Rules

**5N-1. Default mode is always `planning_only` (skeleton generator, no network calls).**
All three runners (`AccessibilityRunner`, `PerformanceSmokeRunner`, `PassiveSecurityRunner`)
generate Playwright TypeScript specs without making any network requests. Status is
always `"planning_only"` until explicit approval flags are passed.

**5N-2. Approved execution for accessibility and performance requires dual flags.**
`--execute --approve-public-readonly-execution --approve-browser-execution` both required.
Missing either flag → `ValueError` raised, exit 1.

**5N-3. Approved execution for passive security requires one flag (HEAD only).**
`--execute --approve-public-readonly-execution` — performs a single passive HEAD request.
No active scanning, no fuzzing, no exploit attempts, no auth bypass — ever.

**5N-4. Active scanning is always blocked regardless of flags.**
`active_scan_allowed=False` is hardcoded in `__post_init__` and `from_dict`.
No CLI flag, environment variable, or dict injection can override this.

**5N-5. Exploit attempts are always blocked.**
`exploit_attempts_allowed=False` hardcoded in `__post_init__`. Passing
`--allow-exploit` CLI flag exits with code 1 before reaching any runner.

**5N-6. Load testing is always blocked.**
`load_testing_allowed=False` hardcoded in `PerformanceSmokeReport.__post_init__`.
The `--load-test` CLI flag exits with code 1.

**5N-7. Delivery pack must not present skeleton-only results as completed testing.**
If `status == "planning_only"`, the QA report table shows:
"Generated checks only; execution requires approval."
Only `status == "executed"` shows results as completed.

**5N-8. Human review is always required before client delivery.**
`human_review_required=True` hardcoded in all Phase 5N schemas.
Client Delivery Pack always shows execution status — never marks planning artifacts as done.

---

## Phase 5O — Flaky Test Analyzer Safety Rules

**5O-1. Static analysis only by default — no code modifications.**
`analyze()` and `analyze_selectors()` are read-only operations.
`code_modification_allowed=False` hardcoded in all Phase 5O schemas.

**5O-2. Auto-fix is always blocked.**
`--auto-fix` flag causes immediate exit 1 with `[BLOCKED]` message.
There is no mechanism to auto-replace selectors.

**5O-3. Applying proposals requires explicit dual-flag approval.**
`--apply-proposals` alone exits 1.
Both `--apply-proposals` AND `--approve-code-modification` are required.
`apply_proposals()` raises `ValueError` without `approve_code_modification=True`.

**5O-4. Applied proposals are TODO comments only — not code replacements.**
Even in approved apply mode, proposals insert `// HEAL-xxx: // TODO:` comments.
The developer must read and implement the suggested change manually.

**5O-5. Human review is always required.**
`human_review_required=True` hardcoded in `FlakyTestAnalysisReport`, `SelectorStabilityReport`, and `SelfHealingReport`.
Cannot be overridden via `from_dict()`.

**5O-6. Production write is always blocked.**
`production_write_allowed=False` hardcoded in `SelfHealingReport`.
The analyzer never writes to production systems.

---

## Phase 6 — MCP Server Safety Rules

**6-1. MCP is an adapter layer — no business logic, no shortcuts.**
`integrations/mcp/tool_handlers.py` calls existing core modules only.
MCP cannot bypass safety invariants in the core.

**6-2. All MCP tools default to planning_only / analysis_only (no network, no browser).**
`network_by_default=False`, `browser_by_default=False` hardcoded in `handle_qa_factory_health`.
Network or browser execution requires explicit per-request approval flags in tool arguments.

**6-3. No credentials accepted as tool parameters.**
`_check_blocked_params()` raises `ValueError` if any argument key contains:
`credential`, `password`, `token`, `api_key`, `secret`, `private_key`, `auth_key`, `access_key`, `bearer`.

**6-4. No credentials returned in any tool response.**
All tool response dicts must not contain raw credential values.
`generate_delivery_pack` uses the same `SecretScanner` as the CLI.

**6-5. `approved_for_client_delivery` is always False in delivery pack responses.**
Human sign-off is required before any client delivery — the MCP layer cannot grant this.

**6-6. `apply_self_healing_fixes` defaults to dry_run=True.**
File modifications only occur when both `approve_code_modification=True` AND `dry_run=False` are explicitly set.

**6-7. Blocked CLI flags exit 1 immediately.**
`--approve-delivery`, `--skip-review`, `--auto-start-browser`, `--credentials` are always blocked.

**6-8. `human_review_required=True` in every MCP tool response.**
This cannot be overridden by any tool argument or client configuration.

---

## Phase 6.1 — One-Command Client Audit Safety Rules

**6.1-1. Safety invariants are enforced via `__post_init__`, not caller trust.**
`ClientAuditInputs` and `ClientAuditResult` reset safety fields regardless of what the caller passes.
Any caller setting `raw_secrets_allowed=True` or `destructive_actions_allowed=True` is silently overridden.

**6.1-2. Blocked CLI flags always exit 1 before any module runs.**
`--auto-approve-all`, `--skip-human-review`, `--force-deliver` are checked before argparse.

**6.1-3. All module approvals are per-run and per-module.**
Approving browser execution unlocks only `accessibility_runner` and `performance_runner`.
Approving public-readonly unlocks only `passive_security_runner`.
No blanket approval path exists.

**6.1-4. `approved_for_client_delivery` is always False in `ClientAuditResult`.**
Human sign-off is required — the workflow orchestrator cannot grant delivery approval.

**6.1-5. No raw secrets accepted via CLI flags or `ClientAuditInputs`.**
`raw_secrets_allowed=False` hardcoded. Env var names are acceptable; raw values are not.

**6.1-6. ASCII-only terminal output.**
`tools/run_client_audit.py` must not emit Unicode characters in print output.

---

## Phase 6-R — MCP Demo Workflow Safety Rules

**6-R-1. Demo workflow blocked flags always exit 1.**
`--approve-delivery`, `--skip-review`, `--force-apply` are checked before argparse and always exit 1.

**6-R-2. Step 7 (`apply_self_healing_fixes`) always blocked in demo mode.**
`approve_code_modification` is intentionally omitted from demo workflow call — verifies blocked path.

**6-R-3. Demo output is ASCII-only.**
`tools/run_mcp_demo_workflow.py` must not use Unicode characters in any print output (Windows cp1252 safety).

**6-R-4. Spec fixtures are not modified by demo workflow.**
After step 7 is blocked, original spec files must have no `// HEAL-` comments inserted.

---

## Phase 6.2 — Finding Schema + Risk Matrix Safety Rules

**6.2-1. No fake findings are generated for planning_only modules.**
Finding adapters must only emit `Finding` objects when real evidence exists (blocked_count > 0, scan failed, etc.).
An empty input must always return `[]`.

**6.2-2. Finding IDs are deterministic and project-scoped.**
IDs follow the pattern `CATEGORY-TYPE-PROJECTID-NNN`. No randomness in IDs.

**6.2-3. Risk score is deterministic; no randomness in sort keys.**
`RiskMatrix.sorted_by_risk()` uses `-risk_score, id` as the sort key — no timestamps, no random tiebreakers.

**6.2-4. Structured findings are read-only in `ClientAuditResult`.**
Safety invariants from Phase 6.1 (`__post_init__` resets) remain unchanged.
`structured_findings` and `risk_summary` are informational; they do not grant any approvals.

---

## Phase 6.3 — Client Delivery Report Safety Rules

**6.3-1. `client_report.md` is always a draft — it does not grant delivery approval.**
`generate_client_delivery_report()` and `write_client_delivery_report()` never set
`approved_for_client_delivery=True`. The report states `approved_for_client_delivery = False` explicitly.

**6.3-2. The report always contains a DRAFT / PENDING HUMAN REVIEW notice.**
No configuration or caller argument can suppress this notice. The notice is generated unconditionally.

**6.3-3. No fake findings in the report.**
`generate_client_delivery_report()` renders only the findings present in `ClientAuditResult.structured_findings`.
If the list is empty, the report says so and explains what was not tested. It does not invent risks.

**6.3-4. Report generation is read-only — does not modify `ClientAuditResult`.**
Calling `generate_client_delivery_report()` or `write_client_delivery_report()` must not alter any
field of the result or plan objects passed to it.

---

## Related documents

- [`APPROVAL_MODEL.md`](APPROVAL_MODEL.md) — risk levels and approval gates
- [`RUNBOOK.md`](RUNBOOK.md) — approval checklist (section 4), safe local vs. external execution (section 5)
- [`REAL_TESTING_PREPARATION.md`](REAL_TESTING_PREPARATION.md) — full staging pre-execution checklist

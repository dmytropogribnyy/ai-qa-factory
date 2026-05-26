# Safety Rules — Guided QA Automation Workbench

**Version:** 5.2.0  
**Updated:** 2026-05-25

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

## Related documents

- [`APPROVAL_MODEL.md`](APPROVAL_MODEL.md) — risk levels and approval gates
- [`RUNBOOK.md`](RUNBOOK.md) — approval checklist (section 4), safe local vs. external execution (section 5)
- [`REAL_TESTING_PREPARATION.md`](REAL_TESTING_PREPARATION.md) — full staging pre-execution checklist

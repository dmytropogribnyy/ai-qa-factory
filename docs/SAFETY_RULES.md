# Safety Rules — Guided QA Automation Workbench

**Version:** 5.1.0  
**Updated:** 2026-05-24

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

## Consequences of rule violations

| If a rule is violated during a run | Required action |
|---|---|
| Staging URL accessed without approval | Stop the run, document what happened, re-run with proper approval |
| Client report contains internal notes | Regenerate the report, do not send the contaminated version |
| Credentials appear in test files | Rotate credentials immediately, remove from files, add to `.gitignore` |
| Evidence claimed without execution | Do not deliver. Re-run the actual tests. |
| Payment test without sandbox confirmation | Stop immediately. Confirm sandbox mode before any further run. |

---

## Related documents

- [`APPROVAL_MODEL.md`](APPROVAL_MODEL.md) — risk levels and approval gates
- [`RUNBOOK.md`](RUNBOOK.md) — approval checklist (section 4), safe local vs. external execution (section 5)
- [`REAL_TESTING_PREPARATION.md`](REAL_TESTING_PREPARATION.md) — full staging pre-execution checklist

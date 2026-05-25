# Client Scenario Fixtures — Guided QA Automation Workbench

**Version:** 1.0.0
**Updated:** 2026-05-25
**Phase:** 3B-SCENARIOS

---

## 1. What these fixtures are

Client scenario fixtures are controlled input files stored under `fixtures/client_scenarios/`.
They simulate realistic client QA tasks that the Workbench must handle correctly.

Key properties:
- **Source inputs only.** They are Markdown documents containing client-style briefs, input examples, and expected Workbench behavior. They are not runtime outputs.
- **Not executed.** Reading a fixture file does not fetch URLs, open browsers, run tests, or call external services.
- **Safe source material.** Fixtures are committed to the repository and used as stable reference inputs for classification, blueprint, strategy, scaffold, and static-validation evaluation.
- **Evaluative.** Each fixture documents what the Workbench should and should not do for that scenario — making them executable acceptance criteria for future agents.

---

## 2. Why they exist

Fixtures help verify that the Workbench correctly handles realistic QA/client tasks across all phases:

| Verification goal | Checked by |
|---|---|
| `task_url` vs `target_url` separation | Expected classification section |
| Public demo vs real production handling | Category rules |
| Auth/payment/integration blocking | Expected blocked actions section |
| Secret redaction | Synthetic scenarios with fake credentials |
| Project type inference | Expected classification section |
| Strategy quality | Expected QA strategy direction section |
| Scaffold layer selection | Expected scaffold direction section |
| No overclaiming | Expected static validation behavior section |
| No execution without approval | What must NOT happen section |
| High-risk marketplace handling | `high_risk_marketplace_readonly` category |

---

## 3. Scenario categories

### A. synthetic

**Purpose:** Safety and redaction testing using fake URLs and fake credentials only.

Synthetic scenarios verify:
- OAuth and social login blocking
- Payment sandbox requirement enforcement
- n8n/webhook integration blocking
- Secret redaction when fake credentials are present in input
- Approval gate behavior

Synthetic scenarios verify:
- OAuth and social login blocking
- Payment sandbox requirement enforcement
- n8n/webhook integration blocking
- Secret redaction when fake credentials are present in input
- Approval gate behavior
- **Task source vs target application separation** (e.g. Linear issue URL as task source, staging URL as target)

**Task management tool URLs (Linear, Jira, ClickUp, Asana) are requirement sources — not target applications.**
When a client provides a Linear or Jira URL as the task description source, the Workbench must:
- Classify it as `task_url`, not `target_url`
- Set `task_source` to the issue tracker URL, not `target_application`
- Never treat Linear/Jira as the application under test unless the client explicitly asks to test that product itself
- Never fetch the issue URL, call the tracker API, or write back comments/status without explicit approval
- Never store a Linear token, Jira token, or API key in any scaffold file

Linear API writeback (commenting on issues, updating status) is a future optional integration that is permanently approval-gated.

**Allowed in synthetic fixtures:**
- Fake URLs: `https://demo.example.com`, `https://staging.example.com`, `https://api.example.com/openapi.json`
- Fake Linear/Jira URLs: `https://linear.app/acme/issue/QA-123/...`, `https://yourteam.atlassian.net/browse/QA-123`
- Fake secret values used explicitly as redaction test input: `FakeSecret123`, `test.user@example.com`
- Placeholder credentials only

**Forbidden in synthetic fixtures:**
- Real OAuth client secrets
- Real webhook URLs or tokens
- Real payment keys or API keys
- Real Linear tokens or Jira API keys
- Real personal credentials

---

### B. public_demo_targets

**Purpose:** Realistic QA automation planning against publicly available demo and practice targets.

These are real demo applications designed for QA practice:
- SauceDemo (`https://www.saucedemo.com`)
- OrangeHRM Open Source Demo
- The Internet / Herokuapp (`https://the-internet.herokuapp.com`)
- Restful Booker (`https://restful-booker.herokuapp.com`)
- JSONPlaceholder (`https://jsonplaceholder.typicode.com`)
- RealWorld / Conduit

**Rules:**
- Real demo URLs may appear in these fixtures.
- These are still external targets — no execution without explicit approval.
- Fixtures must not trigger URL fetching, browser execution, or test runs.
- Credentials (if any) are demo-only: `standard_user` / `secret_sauce`, etc.
- No real personal accounts or OAuth secrets.

---

### C. real_public_readonly

**Purpose:** Read-only planning scenarios for real public production sites.

Used to verify that the Workbench generates useful planning artifacts while correctly blocking any production interaction.

Examples:
- Alza.sk (`https://www.alza.sk`) — public e-commerce
- Playwright.dev (`https://playwright.dev`) — public documentation site

**Rules:**
- Read-only planning only — no login, no cart, no checkout, no payment, no account creation
- No scraping, no catalog extraction, no load testing, no security testing
- No form submissions or automated crawling without explicit written approval
- Fixtures must include a production/read-only warning
- Execution remains blocked until explicit per-run production approval

---

### D. high_risk_marketplace_readonly

**Purpose:** High-risk production marketplace scenarios used to verify strict safety blocking.

Examples:
- Amazon.com (`https://www.amazon.com`) — large public marketplace

**Rules:**
- Read-only planning only — no login, no cart, no checkout, no payment
- No scraping, no catalog extraction, no price monitoring, no review scraping
- No automated crawling, no load testing, no security testing
- No anti-bot bypass, no CAPTCHA bypass
- No session/cookie reuse
- No personal account usage
- No execution without explicit written approval
- Fixtures must include high-risk marketplace warnings

---

## 4. How to use fixtures safely

### Classify-only (implemented)

```bash
python tools/classify_inputs.py \
  --input-file fixtures/client_scenarios/public_demo_targets/01_saucedemo_ecommerce_login.md \
  --no-write
```

`classify_inputs.py` reads the file as the primary brief text, classifies it, and prints results without writing artifacts.

### Strategy generation (implemented — using --input)

```bash
# Extract the brief from the fixture and pass as --input:
python tools/build_strategy.py \
  --project-id scenario-saucedemo \
  --input "Need Playwright tests for SauceDemo. Surfaces: login, product listing, cart, checkout overview." \
  --no-write
```

`build_strategy.py` does not currently support `--input-file`. Pass the brief text directly.

### Scaffold generation (implemented — using --input)

```bash
python tools/generate_scaffold.py \
  --project-id scenario-saucedemo \
  --input "Need Playwright tests for SauceDemo. Surfaces: login, product listing, cart, checkout overview." \
  --no-write
```

`generate_scaffold.py` does not currently support `--input-file`. Pass the brief text directly.

### Static validation (implemented)

After scaffold is generated:
```bash
python tools/validate_scaffold.py \
  --project-id scenario-saucedemo
```

Or with dry run:
```bash
python tools/validate_scaffold.py \
  --scaffold-root outputs/scenario-saucedemo/03_framework/playwright \
  --no-write
```

---

## 5. What must remain blocked

Regardless of scenario category or fixture contents, the following must never happen without explicit written approval:

- URL fetching
- Browser execution
- Playwright test execution
- npm / npx execution
- Credential use (any credential — real or demo)
- Google / OAuth login
- Checkout or payment flow execution
- Account creation
- Scraping or catalog extraction
- Load testing
- Security testing
- Automated crawling
- Price monitoring
- Review scraping
- Anti-bot bypass
- CAPTCHA bypass
- n8n / webhook calls (outbound integration — not implemented; blocked by default)
- Client delivery package creation
- Any external API call

The presence of a real URL in a fixture file does not authorize execution against that URL.
Fixtures are planning inputs — not execution permissions.

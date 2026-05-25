# Client Scenario Fixtures

These are source input fixtures for evaluating the Guided QA Automation Workbench.
They are **not runtime outputs** and do not trigger any execution when read.

## What these are

Each `.md` file in this directory tree is a structured QA client brief that:
- Describes a realistic client QA task
- Documents expected Workbench behavior (classification, blueprint, strategy, scaffold, validation)
- Specifies what must be blocked and what approvals are required
- Is used as reference input for Workbench evaluation and testing

## What these are not

- Not test results
- Not execution records
- Not credential stores
- Not approved targets for execution

## No real credentials

Fixtures must never contain:
- Real OAuth client secrets
- Real API keys or tokens
- Real webhook URLs with credentials
- Real payment keys
- Real personal account credentials

Fake credentials (e.g. `FakeSecret123`, `test.user@example.com`) are allowed **only** in `synthetic/` scenarios as explicit redaction test inputs.

## Real public URLs — presence ≠ execution permission

Fixtures in `public_demo_targets/`, `real_public_readonly/`, and `high_risk_marketplace_readonly/` may reference real public URLs. This does **not** authorize:
- URL fetching
- Browser execution
- Test execution against those URLs
- Any external interaction

All external execution remains blocked until explicit per-run human approval.

## Categories

| Directory | Purpose |
|---|---|
| `synthetic/` | Fake URLs only. Safety/redaction/approval-gate testing. |
| `public_demo_targets/` | Real demo/practice apps. QA planning. Execution still approval-gated. |
| `real_public_readonly/` | Real production/public sites. Read-only planning only. |
| `high_risk_marketplace_readonly/` | High-risk marketplaces (Amazon etc.). Strict safety blocking verification. |

## How to use safely

```bash
# Classify a fixture brief (no execution, no outputs written):
python tools/classify_inputs.py --input-file fixtures/client_scenarios/public_demo_targets/01_saucedemo_ecommerce_login.md --no-write

# See docs/CLIENT_SCENARIO_FIXTURES.md for full guidance.
```

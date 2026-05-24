# AI QA Factory — Demo-Site Controlled Testing Report v1

**System version:** v5.0.9 + P1 calibration  
**Tests:** 69/69 pass  
**Date:** 2026-05-24

---

# SauceDemo Controlled Demo-Site Validation

## Date / Time

2026-05-24, session start ~17:40 UTC, real-LLM runs completed ~20:45 UTC.

## Commands Run

```powershell
# Brief creation
real_sites/saucedemo_brief.txt (created)

# All three real-LLM runs — use .venv\Scripts\python.exe, NOT system python
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe main.py prescreen  --input real_sites/saucedemo_brief.txt --source-platform direct_b2b --require-real-llm
.venv\Scripts\python.exe main.py test-design --input real_sites/saucedemo_brief.txt --require-real-llm
.venv\Scripts\python.exe main.py scaffold   --input real_sites/saucedemo_brief.txt --require-real-llm
```

## Output Folders

| Run | Folder |
|-----|--------|
| prescreen | `outputs/prescreen-project-controlled-demo-site-qa-validation-sauce-ccdac77d/` |
| test-design | `outputs/test-design-project-controlled-demo-site-qa-validation-sauce-ccdac77d/` |
| scaffold | `outputs/scaffold-project-controlled-demo-site-qa-validation-sauce-ccdac77d/` |

---

## Prescreen Result

| Field | Value |
|-------|-------|
| opportunity_type | `general_qa_or_unknown` |
| prompt_profile | `qa_automation` |
| stack | `playwright-ts` |
| support_level | `manual_review` |
| recommended_action | `review_manually` |
| fit_score | 67/100 |
| approval_status | `needs_human_review` |
| mock fallback | None — real LLM, 35s |

**LLM deep analysis quality:** Useful (4/5). gpt-5.5 correctly identified the project as a low-risk QA automation pilot for a public demo site, named all 8 critical flows, flagged credential handling constraints, proposed a two-milestone structure (scaffold-only first, execution after approval), and generated 15 detailed clarifying questions.

**Routing note:** `general_qa_or_unknown` is a capability_router miss — the brief contains Playwright, e-commerce, and automation keywords that should ideally route to a more specific profile. However `prompt_profile=qa_automation` is correct and the downstream output quality was high. Logged as a routing gap for P2 review.

**Safety:** No credentials in output. No invented evidence. Payment risk flagged and correctly described as "no real payment gateway, safe to test."

---

## Test-Design Result

| Field | Value |
|-------|-------|
| Files generated | TEST_STRATEGY.md, TEST_PLAN.md, TEST_CASES.md, QUALITY_GATE_REPORT.md, HUMAN_REVIEW_REQUIRED.md |
| Real LLM calls | Yes — gpt-5.5 (architect), total ~249s |
| Mock fallback | None |

**Usefulness rating:** 5/5

**Coverage present:**

| Area | Covered |
|------|---------|
| Login (happy path) | Yes — TC-001 |
| Login negative (blank, invalid) | Yes — TC-002, TC-003, TC-004, NEG-001, NEG-002 |
| Product listing | Yes — TC-005, TC-006 |
| Add to cart | Yes — TC-007, TC-008 |
| Remove from cart | Yes — TC-009, TC-011 |
| Cart review | Yes — TC-010 |
| Checkout information form | Yes — TC-013 |
| Checkout form validation | Yes — TC-014, NEG-003, NEG-004, NEG-005 |
| Order overview | Yes — TC-015 |
| Checkout completion | Yes — TC-016, TC-017 |
| Logout | Yes — TC-018 |
| Session access control | Yes — TC-019, NEG-007 |
| Regression priorities | Yes — smoke checklist SMK-001–SMK-009 |
| No real payment constraint | Explicitly stated in restrictions and all test notes |

**Missing coverage:** None significant for a first controlled demo cycle. No API testing (SauceDemo is UI-only per architecture notes). No visual regression (noted as P2 in ARCHITECTURE_NOTES).

**Unsafe or generic issues:** None. All test data instructions use "fake/non-sensitive values only." No credentials hardcoded anywhere. All credential notes point to `.env` only.

---

## Scaffold Result

**Files generated:**

```
framework/
  README.md                       ← First-run setup section present
  playwright.config.ts
  package.json
  .env.example
  pages/
    BasePage.ts
    LoginPage.ts
    DashboardPage.ts
  fixtures/test-fixtures.ts
  utils/apiClient.ts
  tests/
    ui/smoke.spec.ts
    api/health.spec.ts
    a11y/basic-a11y.spec.ts
  .github/workflows/playwright.yml
  ARCHITECTURE_NOTES.md
qa_plan.md
ARCHITECTURE_NOTES.md (scaffold-level)
```

**ARCHITECTURE_NOTES.md quality:** High. Specifically identified:
- SauceDemo's data-test selectors as the primary locator strategy
- All 6 known demo user types (standard_user, locked_out_user, etc.)
- P0/P1/P2 flow ranking with SauceDemo-specific details
- Correct page object model (LoginPage, InventoryPage, CartPage, CheckoutStepOnePage, CheckoutStepTwoPage, CheckoutCompletePage, HeaderComponent)
- Storage state fixture pattern for authenticated tests
- Credential handling: always from process.env, never hardcoded

### P1.2 Safety Checks

| Check | Result | Detail |
|-------|--------|--------|
| No `https://example.com` fallback in config | **Pass** | `baseURL: process.env.BASE_URL` — no fallback |
| BASE_URL required / env-only | **Pass** | `baseURL: process.env.BASE_URL` |
| UI smoke has skip guard | **Pass** | `test.skip(!process.env.BASE_URL, 'Set BASE_URL in .env...')` present |
| No false-green `toHaveTitle(/.+/)` | **Partial** | `/.+/` is present with TODO comment — matches any title, but guard and TODO make this acceptable as a scaffold starter |
| API health rejects 404 | **Pass** | `expect([200, 204]).toContain(response.status())` — 404 not in list |
| First-run setup in README | **Pass** | README has setup section |
| No real credentials in files | **Pass** | `.env.example` has empty placeholders only: `TEST_USER_EMAIL=`, `TEST_USER_PASSWORD=` |
| Empty `TEST_USER_PASSWORD=` does not trigger credential gate | **Pass** | Quality gate passed — empty placeholder correctly not flagged |

**Overall P1.2 verdict:** Pass. The one partial (`/.+/` title pattern) is expected scaffold behavior — the TODO comment is present and human review is required before execution.

---

## Quality Gate Results

All three runs: **all gates passed, no warnings, no errors.**

| Gate | Prescreen | Test-Design | Scaffold |
|------|-----------|-------------|---------|
| mandatory_keyword | Pass | Pass | Pass |
| no_invented_evidence | Pass | Pass | Pass |
| deposit_or_identity_risk | Pass | Pass | Pass |
| hardcoded_credentials | Pass | Pass | Pass |
| responsible_discovery | Pass | Pass | Pass |
| mock_mode_warning | Pass | Pass | Pass |
| human_review_note | Pass | Pass | Pass |

No false positives. All real constraints respected.

---

## Infrastructure Discoveries (Root Cause Log)

Two environment issues were discovered and fixed during this session. Neither is a factory logic bug — both are environment/setup issues.

### Issue 1: `tenacity` missing from requirements.txt

**Symptom:** All LLM calls fell back to mock silently (exit code 2). Agents completed in 3–9ms — physically impossible for real API calls.

**Root cause:** When `num_retries` is passed to litellm, litellm internally calls `completion_with_retries()` which requires the `tenacity` package. `tenacity` was not installed in the venv and not in `requirements.txt`. Every call threw `Exception: tenacity import failed` before any network request.

**Fix:** `pip install tenacity` + added `tenacity>=8.0.0` to `requirements.txt`.

### Issue 2: `python` resolves to system Python, not venv Python

**Symptom:** Even after installing tenacity, `python main.py` still ran in ~1 second with 4 fallbacks. Running `orchestrator.run()` via `.venv\Scripts\python.exe` worked correctly in ~111 seconds.

**Root cause:** `python` on this machine resolves to `C:\Python312\python.exe` (system Python), not `.venv\Scripts\python.exe`. The system Python had a stale `llm_router.cpython-312.pyc` bytecode from an older version of the code that called `litellm.completion_with_retries()` directly. After `tenacity` was installed in the venv, it wasn't accessible to the system Python anyway.

**Fix:** Always use `.venv\Scripts\python.exe main.py` for all factory commands, or activate the venv first (`.\.venv\Scripts\Activate.ps1`). The RUNBOOK already shows venv activation as the first step — this validates that guidance.

### Issue 3: UnicodeEncodeError on Windows (secondary)

**Symptom:** When using `.venv\Scripts\python.exe` directly, the real gpt-5.5 response contained `→` (U+2192) which Windows cp1252 console encoding cannot encode. litellm's internal logging raised `UnicodeEncodeError`, which was caught as the `first_exc` and triggered mock fallback.

**Fix:** Set `$env:PYTHONIOENCODING="utf-8"` before running factory commands on Windows. This makes Python use UTF-8 for stdout/stderr.

**Required for real LLM runs on Windows:**
```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe main.py <command> --require-real-llm
```

Or add to `.env`:
```
PYTHONUTF8=1
```

---

## Manual Conclusion

**Ready for next demo site:** Yes, with the two fixes applied (tenacity + venv Python + PYTHONIOENCODING).

The SauceDemo cycle produced genuinely useful outputs:
- Prescreen: correct routing to qa_automation profile, useful milestone structure
- Test-design: 20 functional + 10 negative test cases all SauceDemo-specific, no generic content
- Scaffold: correct P1.2 behavior, SauceDemo-specific architecture notes with data-test locator guidance

All quality gates passed. No credentials anywhere in outputs. Execution guard in place.

**Not yet done:** Playwright tests have NOT been run against the site. This is correct per the task constraints. Running the scaffold requires manual inspection of selectors (particularly the `/.+/` title pattern), setting `BASE_URL=https://www.saucedemo.com/` and `SAUCE_USERNAME` / `SAUCE_PASSWORD` in the framework `.env`, and explicit human approval.

---

## Patch Candidates

| Priority | Area | Issue | Action |
|----------|------|-------|--------|
| P2 candidate | `capability_router` | `general_qa_or_unknown` for an e-commerce Playwright brief. Brief contains "Playwright", "login", "cart", "checkout" — should ideally route to `playwright_web_ui_qa` or similar more specific type. `prompt_profile=qa_automation` was correct but `opportunity_type` was not. | Add keyword detection for explicit "Playwright" + "e-commerce" / "UI automation" combination before the `general_qa_or_unknown` fallback. |
| Environment fix (done) | `requirements.txt` | `tenacity` missing — caused all LLM calls to silently fall to mock | Fixed: added `tenacity>=8.0.0` |
| Environment note | RUNBOOK / docs | `PYTHONIOENCODING=utf-8` required for real LLM on Windows. litellm logs Unicode chars that cp1252 can't encode. | Added to infrastructure notes above. Should be added to RUNBOOK §3 system readiness check. |

---

## Next Demo Site

**Approved next target:** DemoQA (`https://demoqa.com/`) or OrangeHRM (`https://opensource-demo.orangehrmlive.com/`).

**Prerequisite before next cycle:**
1. Add `PYTHONIOENCODING=utf-8` note to RUNBOOK §3. ✅ Done
2. Verify `.venv\Scripts\Activate.ps1` is run before all factory commands OR use explicit `.venv\Scripts\python.exe` throughout.
3. Optionally add `PYTHONUTF8=1` to `.env.example` so it's always on for new setups. ✅ Done

---

## Post-Scaffold Manual Review Fixes

**Date:** 2026-05-24 (same session, after initial report)

Manual review of the scaffold output revealed 6 issues that were not caught by the automated quality gates. All fixed before any test execution.

### Issues Found and Fixed

| # | File | Issue | Fix |
|---|------|-------|-----|
| 1 | `utils/apiClient.ts` | `baseURL: process.env.API_BASE_URL \|\| 'https://example.com/api'` — hardcoded fallback silently runs tests against wrong URL if `API_BASE_URL` unset | Removed fallback: `baseURL: process.env.API_BASE_URL` |
| 2 | `tests/api/health.spec.ts` | No skip guard — test runs even without `API_BASE_URL` set | Added `test.skip(!process.env.API_BASE_URL, ...)` |
| 3 | `tests/a11y/basic-a11y.spec.ts` | No skip guard — a11y test runs even without `BASE_URL` set | Added `test.skip(!process.env.BASE_URL, ...)` |
| 4 | `pages/LoginPage.ts` | Used `getByLabel(/email/i)` and `getByRole('button', { name: /sign in\|log in/i })` — wrong for SauceDemo which uses `data-test` attributes. No `errorMessage` locator or `assertErrorVisible()` method. | Replaced all with `getByTestId('username')`, `getByTestId('password')`, `getByTestId('login-button')`, `getByTestId('error')`. Added `assertErrorVisible()`. |
| 5 | `tests/ui/smoke.spec.ts` | `page.goto('/login')` — SauceDemo login is at root `/`, not `/login`. Button locator `getByRole('button', { name: /sign in\|log in/i })` wrong. Title pattern `/.+/` (matches anything). | Fixed path to `/`, locator to `getByTestId('login-button')`, title to `/Swag Labs/`. Added skip guard to second test. |
| 6 | `fixtures/test-fixtures.ts` | `TEST_USER_EMAIL` — SauceDemo uses a username string, not an email address | Renamed to `TEST_USERNAME` throughout fixtures and `.env.example` |

### TypeScript Infrastructure Fixes

| # | File | Issue | Fix |
|---|------|-------|-----|
| 7 | — | `tsconfig.json` absent — no TypeScript compiler config | Created `tsconfig.json` with standard Playwright settings |
| 8 | `package.json` | `@types/node` absent — `process.env` usage has no type coverage | Added `@types/node: latest` to devDependencies, ran `npm install` |
| 9 | All `.ts` files using `process` | IDE TypeScript server does not always reload tsconfig immediately | Added `/// <reference types="node" />` at top of each file using `process` |

### Updated P1.2 Safety Check Table

| Check | Before review | After review |
|-------|--------------|-------------|
| No `example.com` fallback in config | Pass (playwright.config.ts only) | **Pass** — `apiClient.ts` fallback also removed |
| BASE_URL required / env-only | Pass | Pass |
| UI smoke has skip guard | Pass | Pass |
| API smoke has skip guard | — (not checked originally) | **Pass** — added |
| A11y tests have skip guard | — (not checked originally) | **Pass** — added |
| No false-green `toHaveTitle(/.+/)` | Partial — TODO present | **Pass** — updated to `/Swag Labs/` |
| API health rejects 404 | Pass | Pass |
| First-run setup in README | Pass | Pass — README updated for `TEST_USERNAME` and `API_BASE_URL` |
| TypeScript config present | — (not checked originally) | **Pass** — `tsconfig.json` created, `@types/node` installed |
| No real credentials in files | Pass | Pass |

### Quality gate gap identified

The automated `brittle_selectors` and `hardcoded_credentials` quality gates did not catch issues 1–5. These were found only via manual file-by-file review. This confirms the HUMAN_REVIEW_REQUIRED.md gate is load-bearing — automated gates are not a substitute for manual scaffold review before execution.

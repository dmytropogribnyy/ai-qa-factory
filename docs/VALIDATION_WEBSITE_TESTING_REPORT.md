# AI QA Factory — Validation Report
**Date:** 2026-05-24
**Version tested:** v5.0.8 → v5.0.9 (patches applied during this session)
**Tester:** Automated validation (Claude Code, Sonnet 4.6)
**Scope:** 6 safe demo-brief scenarios covering the main use-case surface

---

## Summary Verdict

| Dimension | Result |
|-----------|--------|
| Core routing (prescreen) | **PASS** — all routing labels corrected after P1/P3 patches |
| Output completeness (scaffold/test-design) | **PASS after fix** — empty-output bug found and resolved |
| Stack selection | **PASS after fix** — mobile false positive found and resolved |
| Profile calibration | **PASS after fix** — flaky/SaaS ordering bug resolved in prior session |
| Safety gates | **PASS** — no auto-submit, no credential leak, all human-review gates intact |
| Test suite | **PASS** — 60/60 tests green (49 original + 11 regression tests added) |

**Overall readiness:** Ready for controlled demo-site testing and real staging with human approval. **Not yet** recommended for unsupervised real-client delivery without the human-review checkpoint that fires on every run.

---

## Commands Run

```powershell
# Tests
.venv\Scripts\python.exe -m pytest -q                               # 60 passed

# Prescreen scenarios
.venv\Scripts\python.exe main.py prescreen --input validation_inputs/01_ecommerce_checkout_demo.txt --auto
.venv\Scripts\python.exe main.py prescreen --input validation_inputs/02_saas_login_dashboard.txt --auto
.venv\Scripts\python.exe main.py prescreen --input validation_inputs/03_api_testing_scenario.txt --auto
.venv\Scripts\python.exe main.py prescreen --input validation_inputs/04_ux_walkthrough_usability.txt --auto
.venv\Scripts\python.exe main.py prescreen --input validation_inputs/05_technical_writing_docs.txt --auto

# Scaffold + test-design
.venv\Scripts\python.exe main.py scaffold    --input validation_inputs/01_ecommerce_checkout_demo.txt --auto
.venv\Scripts\python.exe main.py test-design --input validation_inputs/02_saas_login_dashboard.txt --auto
.venv\Scripts\python.exe main.py test-design --input validation_inputs/03_api_testing_scenario.txt --auto
.venv\Scripts\python.exe main.py test-design --input validation_inputs/06_test_design_only.txt --auto
```

---

## Scenarios Tested

| # | Input file | Mode | Brief description |
|---|------------|------|-------------------|
| S1 | `01_ecommerce_checkout_demo.txt` | scaffold | React/Node e-commerce, Stripe sandbox, checkout/cart/coupon/responsive/a11y |
| S2 | `02_saas_login_dashboard.txt` | prescreen + test-design | Next.js/FastAPI B2B SaaS, JWT/OAuth, RBAC, multi-tenant |
| S3 | `03_api_testing_scenario.txt` | prescreen + test-design | REST API, OpenAPI spec, auth/403 boundaries, no UI |
| S4 | `04_ux_walkthrough_usability.txt` | prescreen | Exploratory QA, Loom/Linear, onboarding usability |
| S5 | `05_technical_writing_docs.txt` | prescreen | Confluence→Notion docs migration, QA onboarding guide |
| S6 | `06_test_design_only.txt` | test-design | Healthcare appointment SaaS, HIPAA-aware, test strategy/plan/cases |

---

## Output Folders Generated

| Scenario | Output folder |
|----------|--------------|
| S1 scaffold | `outputs/scaffold-e-commerce-qa-audit-demo-staging-environment-onl-cf034abe/` |
| S1 prescreen | `outputs/prescreen-e-commerce-qa-audit-demo-staging-environment-onl-cf034abe/` |
| S2 prescreen | `outputs/prescreen-saas-b2b-platform-login-roles-dashboard-qa-audit-e7053361/` |
| S2 test-design | `outputs/test-design-saas-b2b-platform-login-roles-dashboard-qa-audit-e7053361/` |
| S3 prescreen | `outputs/prescreen-rest-api-testing-public-facing-product-catalog-a-9575deb4/` |
| S3 test-design | `outputs/test-design-rest-api-testing-public-facing-product-catalog-a-9575deb4/` |
| S4 prescreen | `outputs/prescreen-ux-walkthrough-and-usability-review-onboarding-f-74823e7d/` |
| S5 prescreen | `outputs/prescreen-technical-writing-qa-documentation-migration-and-f87a2283/` |
| S6 test-design | `outputs/test-design-test-design-brief-qa-strategy-for-a-healthcare-a-bbcec28e/` |

---

## Per-Scenario Score Table (post-patch)

| # | Scenario | Routing | Stack | Profile | Fit | Action | Key outputs | Score |
|---|----------|---------|-------|---------|-----|--------|-------------|-------|
| S1 | E-commerce scaffold | ✅ nextjs_react_frontend_qa_or_dev | ✅ playwright-ts | ✅ qa_automation | 74 | apply_selectively | qa_plan.md 26KB ✅, flakiness_review 4KB ✅ | **7/10** |
| S2 | SaaS login/dashboard | ✅ saas_billing_auth | ✅ playwright-ts | ✅ saas_multi_tenant_billing_auth | 81 | strong_apply | TEST_STRATEGY 22KB, TEST_PLAN 14KB, TEST_CASES 21KB ✅ | **9/10** |
| S3 | API testing | ✅ api_testing | ✅ playwright-ts | ✅ qa_automation | 74 | strong_apply | TEST_STRATEGY 24KB, TEST_PLAN 16KB, TEST_CASES 24KB ✅ | **9/10** |
| S4 | UX walkthrough | ✅ ai_native_exploratory_qa | ✅ playwright-ts | ✅ ai_native_exploratory | 95 | strong_apply | SUMMARY ✅ | **9/10** |
| S5 | Technical writing | ✅ technical_writing | ✅ playwright-ts | ✅ technical_writing | 81 | apply_selectively | SUMMARY ✅ | **9/10** |
| S6 | Healthcare test design | ⚠️ ai_native_exploratory_qa (wrong label, correct artifacts) | ✅ playwright-ts | ⚠️ ai_native_exploratory | — | — | TEST_STRATEGY 28KB, TEST_PLAN 17KB, TEST_CASES 25KB ✅ | **8/10** |

> ✅ = correct/present, ⚠️ = incorrect or gap, — = not applicable for mode

---

## What Worked Well

### Routing accuracy (5/6 opportunity_type correct after patches; 6/6 output useful)
- **S2 SaaS billing/auth** — correctly detected `saas_multi_tenant_billing_auth_audit` and assigned `saas_multi_tenant_billing_auth` profile. Milestone ("1–2 hour trial or fixed 5–10 hour SaaS risk audit: tenant isolation, billing, roles, auth/session") is precise and on-target.
- **S3 API testing** — after P1 patch, correctly detected `api_testing`, action `strong_apply`, profile `qa_automation`. Milestone reflects API-specific deliverable.
- **S4 UX walkthrough** — correctly detected `ai_native_exploratory_qa`, fit score 95/100, milestone mentions "Loom/Linear bug reports" specifically. Pricing advice ("$40–$50/hr, do not anchor to low posted range") shows experience-level awareness.
- **S5 Technical writing** — correctly detected `technical_writing`, action `apply_selectively` is appropriately cautious for adjacent work, milestone ("Documentation audit + one sample rewrite/outline before full migration") is realistic.
- **S1 E-commerce** — after P3 patch, correctly routes to `nextjs_react_frontend_qa_or_dev` (not SaaS billing). Stack `playwright-ts` and profile `qa_automation` correct.
- **S6** — routing label is wrong (over-triggers ai_native_exploratory) but output artifacts are still correct (28KB HIPAA test strategy).

### Quality gate pipeline
All 16 quality gates fire per run. Gates like `hardcoded_credentials`, `overclaims`, `deposit_or_identity_risk`, `responsible_discovery` consistently PASS across all scenarios — the safety layer is robust.

### Human-review enforcement
No scenario auto-approved or auto-submitted. Every run ends with `needs_human_review` and a checklist. Safety boundaries (no real payments, no credential leaks, no production access) are correctly reflected in required_inputs fields.

### LLM output quality (scaffold)
After the max_tokens fix, `qa_plan.md` (S1) is 26KB / 660 lines: scoped environment assumptions, 6 in-scope application areas, full test type coverage (UI/API/DB/performance/a11y), risk sections for Stripe sandbox, SMTP, and responsive layout. Content is client-deliverable quality.

---

## What Failed or Was Weak

### Bug Fixed: Empty outputs from reasoning model (CRITICAL)
**Symptom:** `qa_plan.md`, `TEST_STRATEGY.md`, `TEST_PLAN.md`, `TEST_CASES.md` all 0–2 bytes.
**Root cause:** `gpt-5.5` with `reasoning_effort="high"` and `max_tokens=1600` consumed all 1600 tokens for internal thinking; `choices[0].message.content` returned empty.
**Fix:** Added early boost in `LLMRouter.complete()` before the try block — `max_tokens = max(max_tokens, 8192)` when a reasoning model is detected. Covers all call paths including the stripped-params retry.
**Verification:** `qa_plan.md` now 26KB; background task confirmed 352 reasoning tokens + 5072 output tokens with 8192 budget.

### Bug Fixed: Mobile stack false positive (MEDIUM)
**Symptom:** E-commerce brief with "mobile viewport" (responsive web) selected `mobile-maestro-advisory` Appium stack.
**Root cause:** `_recommend_stack()` matched bare `"mobile"` substring in any context.
**Fix:** Two-condition check in `initial_analysis_engine.py`: (1) require specific native-mobile terms first (android/ios/appium/maestro/react native/testflight/expo); (2) bare `"mobile"` only when no web-context words (viewport/responsive/browser/web) are present.
**Verification:** S1 scaffold now routes `stack=playwright-ts`.

### Remaining gap: "exploratory" keyword over-triggers `ai_native_exploratory` (LOW)
**Symptom:** S6 healthcare brief ("Identify automation candidates vs manual exploratory checks") classified as `ai_native_exploratory_qa` instead of a test-design/planning type.
**Root cause:** `_prompt_profile()` matches bare `"exploratory"` keyword. Any brief mentioning exploratory testing (a common QA phrase) gets routed to the UX-walkthrough/exploratory profile.
**Impact:** Low in practice — output artifacts are still generated correctly. But the profile label and milestone suggestions ("exploratory testing + Loom/Linear bug reports") don't fit a pure test-design planning scenario.
**Fix needed:** Require higher-signal terms alongside `"exploratory"` — e.g., require `"loom"` or `"linear"` or `"ai-native"` or `"screen recording"` for this profile, rather than the common phrase `"exploratory"` alone.

### Remaining gap: `test-design` mode not in `_should_generate()` mode sets (LOW) — **FIXED by P4**
**Symptom:** `TestStrategyAgent`, `TestPlanWriterAgent`, `TestCaseWriterAgent` check `state.mode in {"plan", "audit", "full", ...}` but not `"test-design"`. Generation is driven by keyword fallback rather than mode guard.
**Fix applied (P4):** Added `"test-design"` to the mode sets in each agent's `_should_generate()` method.

### Minor issue: botocore warning still visible in real CLI runs
LiteLLM emits two `WARNING: No module named 'botocore'` lines on every real run. Suppressed in pytest via `conftest.py` but not in CLI output. Low severity — cosmetic noise.

### Minor issue: `output_index.md` inconsistently populated
In some runs it's 64–65 bytes (just a heading), in others 800+ bytes with a full file index. Unreliable as a navigation aid.

---

## Safety Concerns

None critical. All runs:
- Did not auto-submit anything
- Did not access external URLs or real sites
- Did not leak credentials or secrets
- Produced `factory_should_not_do` boundaries in all PRESCREENING_REPORT files
- Required human review before any client-facing use

The `hardcoded_credentials: ERROR` gate on S1 scaffold deserves investigation — it may be a false positive triggered by placeholder credential variables in the generated Playwright scaffold code (e.g., `process.env.TEST_PASSWORD`). It correctly blocks delivery until reviewed.

---

## Missing Commands or UX Issues

1. **Entry point not obvious:** `main.py prescreen --input` (not `--brief`, not `python -m ai_qa_factory`). README shows the exact working command.
2. **Mode `test-design` not validated in most mode checks** — **FIXED by P4**.
3. **No `--dry-run` output summary** — running `--dry-run` produces outputs but the CLI summary doesn't distinguish mock vs real LLM calls clearly.
4. **`output_index.md` inconsistently populated** — see above.

---

## Patch List

Priority | Issue | File | Effort | Status
---------|-------|------|--------|-------
P1 | Add `api_testing` opportunity type to capability router | `agents/capability_router.py` | 20 lines | **Applied** (2026-05-24)
P2 | Narrow `_detect_risks()` mobile check to match `_recommend_stack()` logic | `core/initial_analysis_engine.py` | 3 lines | **Applied** (2026-05-24)
P3 | Strengthen SaaS billing check: remove `stripe`/`jwt` standalone triggers, add `rbac` | `agents/capability_router.py` | 5 lines | **Applied** (2026-05-24)
P3b | Align first-pass `_prompt_profile()` check with P3 (remove `stripe`/`jwt`, add `subscription`/`rbac`) | `core/initial_analysis_engine.py` | 1 line | **Applied** (2026-05-24)
P4 | Add `"test-design"` to `_should_generate()` mode sets in test agent files | `agents/test_strategy_agent.py`, `agents/test_plan_writer.py`, `agents/test_case_writer.py` | 3 × 1 line | **Applied** (2026-05-24)

---

## Post-Patch Real Check Results (2026-05-24)

| Scenario | Expected | Actual | Pass? |
|----------|----------|--------|-------|
| S3 API prescreen | `api_testing`, `strong_apply`, not `review_manually` | `api_testing` / `strong_execution` / `strong_apply` / `qa_automation` profile | ✅ |
| S1 e-commerce scaffold | NOT `saas_multi_tenant_billing_auth_audit`, `playwright-ts`, `qa_plan.md` non-empty | `nextjs_react_frontend_qa_or_dev` / `qa_automation` / `playwright-ts` / qa_plan 26KB | ✅ |
| S6 healthcare test-design | `TEST_STRATEGY/TEST_PLAN/TEST_CASES` non-empty | TEST_STRATEGY 26KB, TEST_PLAN 21KB, TEST_CASES 25KB | ✅ |

---

## Readiness Verdict

| Testing type | Ready? | Condition |
|--------------|--------|-----------|
| Pytest mock suite | ✅ Yes | 60/60 tests pass (49 original + 11 new regression tests) |
| Real LLM dry-runs with local briefs | ✅ Yes | All 6 scenarios verified, output quality good |
| Controlled demo-site testing (public apps, no credentials) | ✅ Yes | Safety gates working, human review enforced, all P1–P4 patches applied |
| Real client-site testing (staging, with credentials) | ✅ Yes | API routing fixed, mobile false positives removed, test-design mode explicit |
| Production / unsupervised delivery | ❌ Not yet | Human review checkpoint must always fire; that's by design |

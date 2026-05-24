# AI QA Factory — Concept, Architecture and Implementation Plan

**Version:** v7.0 — Validation-Hardened + P1 Calibration  
**Owner:** Dmytro Pogribnyy  
**System version:** v5.0.9 + P1 calibration (patches applied 2026-05-24)  
**Status:** Controlled demo-site testing ✅ · Real staging with human approval ✅ · Unsupervised production ❌  
**Previous version:** `docs/archive/AI_QA_Factory_Concept_and_Implementation_Plan_v6_model_routing.md` (archived)

---

## 0. Purpose

This document is the **single current canonical reference** for AI QA Factory. It captures:

- What the system exists for and what it deliberately does not do.
- Current operating state after validation hardening and P1 calibration.
- Which CLI commands are confirmed working.
- How routing, safety, and model routing are configured.
- What validation evidence exists and where human approval is required.
- Roadmap and strategic decision rules for future work.

> **AI drafts. Senior QA decides.**

AI generates analysis artifacts, routing decisions, proposals, test strategies, and scaffolds. Final decisions, editing, and delivery responsibility always stay with Dmytro.

---

## 1. Business and Strategic Purpose

**AI QA Factory** exists to help Dmytro Pogribnyy win and deliver QA/SDET opportunities faster, with less repeated manual work and without sacrificing judgment quality.

### What the system does

- Analyzes pasted job descriptions, client briefs, and opportunity text.
- Filters: **strong apply / apply selectively / advisory only / skip**.
- Generates platform-appropriate outputs: proposals, screening answers, QA plans, test strategies, Playwright scaffolds, technical writing pitches, and delivery summaries.
- Routes each brief to the right capability zone — Playwright execution, SaaS audit, API testing, test design, mobile advisory, or technical writing.
- Applies 16 quality gates on every run to catch overclaims, credential leaks, deposit risks, and fabricated evidence.
- Enforces human review before any output reaches a client or external system.

### Primary opportunity channels

| Channel | Status |
|---------|--------|
| Upwork QA / SDET proposals | **Current — primary** |
| Direct client briefs / QA audits | **Current** |
| Technical writing / docs migration | **Current — adjacent strong** |
| LinkedIn / direct B2B leads | **Partially supported — paste text manually** |
| AI evaluator platform analysis | **Profile prep only — not for executing paid evaluator tasks** |
| Fiverr / PPH packaged gig flows | **Future** |
| Direct B2B cold DM / one-page offer packs | **Future** |

### Core principle

> Broad intake. Focused execution. Honest routing.

Playwright + TypeScript is the strongest execution zone. The system accepts broad opportunity types but routes them honestly: **strong apply** only where delivery is fully supported; **skip** or **advisory** for everything else.

---

## 2. Multi-Platform Opportunity Intake

The system is not Upwork-only. It accepts input from any channel where Dmytro pastes the opportunity text.

### Current reliable intake

| Source | How to use |
|--------|------------|
| Upwork job description | Copy text → `python main.py prescreen --input <file> --source-platform upwork` |
| Direct client brief | Save as `.txt` → `python main.py prescreen --input <file>` |
| Manually written brief | Any format → `python main.py prescreen`, `scaffold`, or `test-design` |
| `validation_inputs/` demos | Provided in repo → run any mode |
| `sample_inputs/` examples | Provided in repo → run any mode |

### Partially supported

| Source | Notes |
|--------|-------|
| Technical writing / documentation calls | `prescreen` + `technical_writing` profile; dedicated agent active |
| LinkedIn / direct leads | Paste description text; no LinkedIn integration |
| AI automation adjacent opportunities | Routes to `ai_automation_adjacent`; analysis + advisory only |

### Future / not current

- URL-only intake — no browser or screenshot integration yet
- Screenshot-only vision intake — `vision` role reserved but not wired
- Fiverr / PPH buyer request format handling
- Aggressive scraping or auto-polling of any platform

### Evaluator platforms

The system may only help prepare profiles, organize experience, and understand platform rules. It must **not** be used to execute paid AI evaluator tasks — platform policy violation.

---

## 3. Platform-Specific Output Packs

### Current outputs by use case

#### Upwork / direct proposal pack

```
READ_ME_FIRST.md · DECISION.md · proposal.md · screening_answers.md
commercial_strategy.md · evidence_needed.md · PRESCREENING_REPORT.md
HUMAN_REVIEW_REQUIRED.md · QUALITY_GATE_REPORT.md · NEXT_ACTIONS.md
```

#### QA delivery pack (scaffold + test design)

```
TEST_STRATEGY.md · TEST_PLAN.md · TEST_CASES.md · qa_plan.md
framework/README.md · framework/playwright.config.ts
framework/tests/ui/smoke.spec.ts · framework/tests/api/health.spec.ts
ARCHITECTURE_NOTES.md · QUALITY_GATE_REPORT.md · HUMAN_REVIEW_REQUIRED.md
```

#### Technical writing / documentation

```
documentation_plan.md (where supported) · sample_doc_rewrite.md (where supported)
pitch-style proposal from proposal writer · QUALITY_GATE_REPORT.md
```

### Future / not current output packs

| Pack | Would-be command | Status |
|------|-----------------|--------|
| Fiverr gig pack (`gig_title.md`, `package_tiers.md`, `faq.md`) | `python main.py gig` | **Future — not implemented** |
| Direct B2B cold DM / one-page offer | `python main.py opportunity` | **Future — not implemented** |
| Evaluator platform profile prep | n/a | **Partial — via `prescreen`** |
| Writing platform pitch pack | n/a | **Partial — via `prescreen` + `technical_writing` profile** |

Do not use `python main.py gig` or `python main.py opportunity` — these commands do not exist.

---

## 4. Operating Status

| Layer | Status | Notes |
|-------|--------|-------|
| Pytest mock suite | ✅ **69/69 tests pass** | 49 original + 11 v5.0.9 validation + 9 P1 calibration = 69 |
| Real LLM routing | ✅ Verified | `premium_hybrid` routes gpt-5.5 / claude-sonnet-4-6 / claude-opus-4-7 correctly |
| Reasoning model output | ✅ Fixed | max_tokens boost prevents empty outputs from gpt-5.5 with reasoning_effort |
| Opportunity routing | ✅ Calibrated | P1.1 narrows exploratory/manual trigger; api_testing, SaaS, e-commerce, mobile all route correctly |
| Scaffold false-green | ✅ Fixed (P1.2) | No example.com default; BASE_URL required; API health 200/204 only; UI smoke has skip guard |
| Credential gate | ✅ Fixed (P1.3) | Empty `TEST_USER_PASSWORD=` placeholder no longer false-positive |
| Mobile prompt | ✅ Fixed (P1.4) | `mobile_release_qa.md` exists and loads correct mobile-specific content |
| Mock fallback visibility | ✅ Fixed (P1.5) | `fallback_to_mock_count` tracked; CLI warns on fallback; `--require-real-llm` exits non-zero |
| Safety gates (16 total) | ✅ Active and enforced | Human review blocks unsafe delivery; no auto-submit, no credential leak |
| Demo-site testing | ✅ Ready | No P0 blockers; all P1 patches applied |
| Real staging | ✅ Conditional | Written scope + staging credentials + sandbox payment confirmation + human approval per run |
| Unsupervised production | ❌ Not supported | By design — human review checkpoint must always fire |

---

## 5. CLI Commands (Confirmed Working)

### Tests (always mock mode — no API keys required)

```powershell
.venv\Scripts\python.exe -m pytest -q
```

### System readiness check

```bash
python main.py system-health
```

### Pre-screening (fast suitability check before spending Connects or accepting work)

```bash
python main.py prescreen --input validation_inputs/02_saas_login_dashboard.txt --auto
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --auto
```

### Scaffold (Playwright framework starter from a brief)

```bash
python main.py scaffold --input validation_inputs/01_ecommerce_checkout_demo.txt --auto
```

### Test design (TEST_STRATEGY.md + TEST_PLAN.md + TEST_CASES.md from a brief)

```bash
python main.py test-design --input validation_inputs/06_test_design_only.txt --auto
```

### Real Upwork proposal flow (requires real API keys)

```bash
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
```

### Batch filtering

```bash
python main.py batch-filter --input sample_inputs/
```

### Other confirmed modes

```bash
python main.py filter --input sample_inputs/upwork_job_saas_multitenant_billing.txt
python main.py full --input sample_inputs/client_brief.txt
python main.py review --input sample_inputs/test_to_review.ts
python main.py capabilities
python main.py agents
python main.py ask --project-id <project_id> --question "Why did you recommend this action?"
```

### Execution mode flags

```bash
python main.py full --input <file> --step           # pause between agents for inline feedback
python main.py full --input <file> --dry-run        # no final file write
python main.py full --input <file> --only proposal_writer
python main.py full --input <file> --from-step proposal_writer
```

### Commands that do NOT exist

| Wrong | Correct |
|-------|---------|
| `python -m ai_qa_factory` | `python main.py <mode>` |
| `--brief` | `--input` |
| `python main.py opportunity` | `python main.py prescreen` |
| `python main.py gig` | `python main.py prescreen` or `python main.py filter` |

---

## 6. Architecture Overview and Principles

### Core pipeline

```
Input brief / job description
        ↓
InitialAnalysisEngine  (first-pass profile + stack + risks)
        ↓
CapabilityRouterAgent  ← authoritative opportunity_type + prompt_profile
        ↓
PlatformRouterAgent    (source platform detection)
        ↓
Task-specific agents   (scaffold / test-design / prescreen / proposal / …)
        ↓
16 quality gates       (safety, credentials, overclaims, deposit risk, …)
        ↓
Human-review outputs   (needs_human_review always)
```

### Two-classifier design

`InitialAnalysisEngine` runs first and produces a candidate `prompt_profile`. `CapabilityRouterAgent` runs second and is **authoritative**: it uses `OPPORTUNITY_PROFILE_MAP` to overwrite whatever first-pass profile was set. Both classifiers must be aligned on detection logic to avoid stale first-pass values surviving into outputs.

### OPPORTUNITY_PROFILE_MAP (source of truth)

```python
OPPORTUNITY_PROFILE_MAP = {
    "saas_multi_tenant_billing_auth_audit": "saas_multi_tenant_billing_auth",
    "ai_native_exploratory_qa":             "ai_native_exploratory",
    "flaky_regression_automation":          "flaky_tests",
    "technical_writing":                    "technical_writing",
    "react_native_maestro_qa":              "mobile_release_qa",
    "api_testing":                          "qa_automation",           # added v5.0.9 P1
    "tosca_advisory":                       "skip_or_not_fit",
    "risky_identity_or_deposit_test":       "skip_or_not_fit",
    "low_value_usability_test":             "skip_or_not_fit",
    "developer_only_not_core":              "skip_or_not_fit",
}
```

### Architecture principles

| Principle | Status | How it works |
|-----------|--------|-------------|
| Human-in-the-loop | **Current** | `needs_human_review` on every run; `APPROVAL_CHECKPOINTS.md` per output |
| Deterministic scaffold + LLM notes | **Current** | `PlaywrightGeneratorAgent` writes TypeScript files deterministically; LLM provides architecture notes only |
| Safety first | **Current** | 16 quality gates; deposit/identity/credential/overclaim checks on every run |
| Registry-based workflows | **Current** | `ROUTING_CORE + TEST_DESIGN_CORE` composable lists; `test-design` = ROUTING_CORE + TEST_DESIGN_CORE |
| Prompt profiles in files | **Current** | `prompts/` directory; `PromptLoader.load(category, profile, fallback="default")` |
| Persistence and logging | **Current** | `memory/projects/` JSON; `outputs/<id>/logs/factory.jsonl` |
| Human-readable markdown first | **Current** | Every run produces `READ_ME_FIRST.md`, `DECISION.md`, `QUALITY_GATE_REPORT.md` before JSON |
| Extension packs | **Current** | `ProjectExtensionAgent` suggests stack-specific extensions without permanent changes |
| URL / browser / vision intake | **Future** | Playwright MCP, screenshot intake not yet wired |
| LangGraph / RAG / UI | **Future** | Only if CLI proves insufficient — deferred by design |

---

## 7. Capability Zones

### Strong execution

| Zone | Notes |
|------|-------|
| Playwright + TypeScript | Scaffold, CI, page objects, fixtures, smoke, API, a11y |
| Web QA / SaaS QA audit | QA plan, risk audit, bug report strategy |
| SaaS multi-tenant / billing / auth / RBAC | Black-box audit plan; triggers on: `multi-tenant`, `billing`, `subscription`, `tenant isolation`, `oauth`, `rbac` |
| API testing | API smoke, health, contract, schema, negative; triggers on: `rest api`, `openapi`, `bearer token`, `postman`, `api testing`, etc. |
| AI-native exploratory QA | Triggers on high-signal terms: `loom`, `linear`, `jam.dev`, `jam`, `screen recording`, `ai-native`, `hands-on qa`, `release qa pass`, `narrated walkthrough`, `usability walkthrough` |
| Flaky regression automation | Root-cause review, failing-test strategy, regression prioritization |
| Test design (strategy / plan / cases) | 3-file output: TEST_STRATEGY.md + TEST_PLAN.md + TEST_CASES.md via `test-design` mode |
| QA technical writing / documentation | Dedicated `technical_writing` profile; requires real writing sample before proposal |

### Supported / partial

| Zone | Status | Notes |
|------|--------|-------|
| E-commerce checkout QA | **Partial** | Routes to `nextjs_react_frontend_qa_or_dev`; no dedicated type yet (P2.2 will fix) |
| Next.js / React app QA | **Supported** | QA/automation angle; not full dev position |
| PWA / offline testing | **Supported** | Clarify devices and test data |
| UX walkthrough / recorded testing | **Supported** | Product feedback first; not automation-first |
| Documentation migration | **Supported** | Via `technical_writing` profile |
| Mobile release QA (RN / Maestro) | **Conditional** | Advisory only unless Mac, Xcode, TestFlight, emulators confirmed |
| AI automation adjacent opportunities | **Analysis only** | Routes to `ai_automation_adjacent`; discovery + advisory angle |
| Selenium → Playwright migration | **Supported** | Migration plan + starter scaffold |

### Advisory only

| Zone | Notes |
|------|-------|
| Tosca / Tricentis | Do not claim expert hands-on unless real experience confirmed |
| Formal security / pentest | Responsible discovery only; no exploit claims |
| Deep performance / load testing | Advisory; clarify load model and environment |
| Compliance / regulated testing | Advisory; no regulated-compliance claims without written scope |
| Sharetribe marketplace | Advisory |
| Native mobile (without tooling) | Advisory if Mac / Xcode / TestFlight unavailable |

### Skip / risk

| Type | Reason |
|------|--------|
| Crypto / deposit / ID testing | Safety policy — high risk of fraud or legal exposure |
| Low-budget usability ($5–$10) | Damages Senior QA positioning |
| Pure developer roles | Outside core QA/SDET positioning |
| Fake evidence / invented credentials | Forbidden — quality gate blocks; zero exceptions |
| Unauthorized production testing | Requires explicit written scope and human approval |
| Real payment flows without safe scope | Sandbox confirmation required in writing before any test run |

### Routing table

| Opportunity type | Support level | Stack | Profile | Action |
|-----------------|---------------|-------|---------|--------|
| `saas_multi_tenant_billing_auth_audit` | Strong execution | playwright-ts | `saas_multi_tenant_billing_auth` | strong_apply |
| `ai_native_exploratory_qa` | Strong execution | playwright-ts | `ai_native_exploratory` | strong_apply |
| `flaky_regression_automation` | Strong execution | playwright-ts | `flaky_tests` | strong_apply |
| `api_testing` | Strong execution | playwright-ts | `qa_automation` | strong_apply |
| `technical_writing` | Adjacent | — | `technical_writing` | apply_selectively |
| `react_native_maestro_qa` | Advisory | mobile-maestro-advisory | `mobile_release_qa` | advisory_only |
| `nextjs_react_frontend_qa_or_dev` | Supported | playwright-ts | `qa_automation` | apply_selectively |
| `tosca_advisory` | Skip | — | `skip_or_not_fit` | skip |
| `risky_identity_or_deposit_test` | Skip | — | `skip_or_not_fit` | skip |
| `low_value_usability_test` | Skip | — | `skip_or_not_fit` | skip |
| `developer_only_not_core` | Skip | — | `skip_or_not_fit` | skip |
| `general_qa_or_unknown` | Review | playwright-ts | `qa_automation` | review_manually |

---

## 8. Hardening Patches

### P1–P4: v5.0.9 validation hardening (2026-05-24)

All patches applied. Tests: 49 → 60.

#### P1 — `api_testing` opportunity type (MEDIUM)

**Problem:** Pure REST/API briefs fell through to `general_qa_or_unknown`.  
**Fix:** Added `"api_testing"` to `_detect_type()`, `OPPORTUNITY_PROFILE_MAP`, `_support_level()` strong set, and `_safe_angle()`.

#### P2 — Mobile risk flag false positive (MEDIUM)

**Problem:** `"mobile viewport"` in a responsive-web brief triggered the native-mobile risk flag.  
**Fix:** Narrowed `_detect_risks()` to require native-mobile terms (`ios`, `android`, `appium`, `maestro`, `react native`, `testflight`, `expo`) or bare `"mobile"` only when `viewport`, `responsive`, `browser`, `web` are absent.

#### P3 — SaaS billing check strengthened (MEDIUM)

**Problem:** `"stripe"` and `"jwt"` as standalone triggers misrouted e-commerce Stripe checkout briefs.  
**Fix:** Removed `"stripe"`, `"jwt"` as standalone triggers. Kept `"multi-tenant"`, `"billing"`, `"subscription"`, `"tenant isolation"`, `"oauth"`, `"rbac"`.

#### P3b — First-pass alignment (MEDIUM)

`InitialAnalysisEngine._prompt_profile()` SaaS check aligned with P3 to prevent unreconciled profile mismatches.

#### P4 — `test-design` mode explicit in agent guards (LOW)

**Fix:** Added `"test-design"` to mode set in `TestStrategyAgent`, `TestPlanWriterAgent`, `TestCaseWriterAgent`.

### P1 calibration: post-audit hardening (2026-05-24)

Applied after `docs/REPO_STRATEGIC_READINESS_AUDIT_v1.md`. Tests: 60 → 69.

#### P1.1 — Narrow `ai_native_exploratory_qa` keyword trigger

**Problem:** Plain `"manual"` or `"exploratory"` hijacked SaaS, API, and regression briefs. `_detect_type()` checked `ai_native_exploratory_qa` before the SaaS billing and API checks.

**Fixes:**
- `agents/capability_router.py` `_detect_type()`: removed `"exploratory"`, `"manual"`, `"hands-on"` as standalone triggers; new list: `["ai-native", "loom", "linear", "jam.dev", "jam", "screen recording", "hands-on qa", "release qa pass", "narrated walkthrough", "usability walkthrough"]`; moved check to run after SaaS and API checks.
- `core/initial_analysis_engine.py` `_prompt_profile()`: same keyword narrowing (ordering already correct).

**Result:** `"manual billing testing for our multi-tenant SaaS"` → `saas_multi_tenant_billing_auth_audit` ✅. `"record loom video walkthroughs"` → `ai_native_exploratory_qa` ✅.

#### P1.2 — Fix Playwright scaffold false-green assertions

**Problem:** Out-of-the-box scaffold produced apparently-passing smoke tests against `example.com`.

**Fixes in `agents/playwright_generator.py`:**
- `playwright.config.ts`: `baseURL: process.env.BASE_URL` — no fallback default.
- `smoke.spec.ts`: Added `test.skip(!process.env.BASE_URL, 'Set BASE_URL in .env before running UI smoke tests')` + TODO comment for title pattern.
- `health.spec.ts`: Narrowed `[200, 204, 404]` → `[200, 204]`.
- `README.md`: Added **First-run setup** section requiring `BASE_URL` to be set.

#### P1.3 — Fix `hardcoded_credentials` false positive

**Problem:** `r"TEST_USER_PASSWORD="` matched the empty placeholder in `.env.example`, flagging every scaffold as `ERROR`.  
**Fix in `core/quality_gate.py`:** Pattern tightened to `r"TEST_USER_PASSWORD=['\"]?[A-Za-z0-9!@#$%^&*\-_+]+"` — requires a non-empty value after `=`.

#### P1.4 — Fix mobile prompt filename mismatch

**Problem:** `OPPORTUNITY_PROFILE_MAP` maps `react_native_maestro_qa` → `mobile_release_qa`, but `prompts/qa_plan/mobile_release_qa.md` did not exist. Silent fallback to generic default prompt.  
**Fix:** Created `prompts/qa_plan/mobile_release_qa.md` with mobile-specific content.

#### P1.5 — Surface mock fallback in real-mode CLI output

**Problem:** A `--require-real-llm` run that silently degraded to mock returned exit 0 with no warning.

**Fixes:**
- `core/llm_router.py`: Added `fallback_to_mock_count: int = 0`; increments every time the mock fallback path is taken after real-call failure.
- `main.py`: After `orchestrator.run()`, checks `orchestrator.router.fallback_to_mock_count`; prints `WARNING: N LLM call(s) fell back to mock output` to stderr if > 0; returns exit code 2 under `--require-real-llm` unless `--allow-mock` is also set.

### Earlier fixes (v5.0.8, pre-validation)

- **max_tokens boost for reasoning models:** `LLMRouter.complete()` sets `max_tokens = max(max_tokens, 8192)` when a reasoning model with `reasoning_effort` is detected, before the try block.
- **Mobile stack false positive:** `_recommend_stack()` narrowed to require native-mobile terms.
- **Prompt profile calibration:** `CapabilityRouterAgent` `OPPORTUNITY_PROFILE_MAP` added as authoritative final pass.

---

## 9. Practical Validation and Demo-Site Strategy

### Completed (2026-05-24)

- 6 demo-brief scenarios validated against local briefs — full report: `docs/VALIDATION_WEBSITE_TESTING_REPORT.md`.
- Strategic readiness audit completed — `docs/REPO_STRATEGIC_READINESS_AUDIT_v1.md` — no P0 blockers.
- P1 calibration patches applied.
- 69/69 tests green.

### Controlled demo-site testing (next stage)

Safe public demo apps to use with written briefs — no real credentials:

| # | Source | Why safe | Command |
|---|--------|----------|---------|
| 1–6 | `validation_inputs/01–06` | Local briefs | any mode |
| 7 | `https://demoqa.com/` — written brief | Public learning site | `prescreen` + manual review |
| 8 | `https://www.saucedemo.com/` — written brief | QA training site, public demo accounts | `prescreen` + manual scaffold review |
| 9 | `https://opensource-demo.orangehrmlive.com/` — written brief | Public HRM demo | `prescreen` + manual review |

**On each run:** open `READ_ME_FIRST.md` → `DECISION.md` → `PRESCREENING_REPORT.md` → `QUALITY_GATE_REPORT.md` → `HUMAN_REVIEW_REQUIRED.md`. Record any misrouting as a gap; do not fix during the run.

Do **not** `npm test` against demo sites until `BASE_URL` and placeholder assertions are reviewed. P1.2 makes this safer — BASE_URL is required and the UI smoke test skips without it.

### Real staging-site testing (Conditional)

Before any real staging run, all of the following must be in place:

1. Written scope: target URL, in-scope flows, out-of-scope, timebox, stop conditions.
2. Staging URL on a different domain from production.
3. Test accounts per role — synthetic data, no PII.
4. Sandbox payment confirmation in writing (test cards only; Stripe in test mode visible in dashboard).
5. `python main.py system-health` → all checks pass.
6. `python -m pytest -q` → 69/69 green.
7. `APPROVAL_CHECKPOINTS.md` signed off per run.
8. `--require-real-llm` used; P1.5 will surface any mock fallback before the run is trusted.

See `docs/REAL_TESTING_PREPARATION.md` for the full per-run checklist.

---

## 10. Rapid Delivery Packs

A first-class `--test-depth` flag is **not yet implemented**. The system supports delivery depth through mode selection today.

### Current delivery pack equivalents

| Pack | How to produce today | Status |
|------|---------------------|--------|
| Sanity | `scaffold` → review smoke.spec.ts only | **Partial** |
| Smoke | `scaffold` → review all 3 spec files | **Good** (default scaffold depth) |
| Regression | `test-design` → TEST_STRATEGY + PLAN + CASES | **Good** |
| UI-only | `scaffold` → `tests/ui/` only | **Partial** |
| API-only | `scaffold` → `tests/api/` only | **Partial** |
| Exploratory pass | `prescreen` → `ai_native_exploratory` profile | **Good** |
| SaaS risk audit | `prescreen` or `audit` → saas profile | **Strong** |
| Test-design only | `test-design` mode | **Strong** |
| Client delivery summary | `full` → SUMMARY.md + delivery_note.md | **Good** |

### P2.1 — `--test-depth` flag (not yet implemented)

A `--test-depth {sanity,smoke,regression,full,api_only,exploratory_only}` CLI flag consumed by test-design and scaffold agents is the recommended P2 improvement. See `docs/REPO_STRATEGIC_READINESS_AUDIT_v1.md` §8 for the full design. **Future.**

---

## 11. Current Readiness Status

As of 2026-05-24 post-P1 calibration:

| Item | Status |
|------|--------|
| P0 blockers | ✅ **None** |
| P1 calibration patches | ✅ **All 5 applied** (P1.1–P1.5) |
| Tests | ✅ **69/69 pass** |
| system-health | ✅ **Pass** (all 26 checks) |
| Controlled demo-site testing | ✅ **Can start now** |
| Real staging-site testing | ✅ **Conditional** — written scope, staging credentials, sandbox confirmation, human approval per run |
| Unsupervised production delivery | ❌ **Not supported** — by design |

---

## 12. Validation Results (2026-05-24)

Full report: `docs/VALIDATION_WEBSITE_TESTING_REPORT.md`

### Summary verdict (post-patch)

| Dimension | Result |
|-----------|--------|
| Core routing (prescreen) | **PASS** — all 3 previously-wrong labels fixed by P1/P3 |
| Output completeness (scaffold/test-design) | **PASS** — max_tokens fix, all outputs non-empty |
| Stack selection | **PASS** — mobile false positive fixed |
| Profile calibration | **PASS** — SaaS billing vs flaky_tests ordering fixed |
| Safety gates | **PASS** — active and enforced; human review blocks unsafe delivery |
| Test suite | **PASS** — 60/60 at validation; 69/69 after P1 calibration |

### Per-scenario results (post-patch)

| # | Scenario | Opportunity type | Profile | Fit | Action | Score |
|---|----------|-----------------|---------|-----|--------|-------|
| S1 | E-commerce scaffold | `nextjs_react_frontend_qa_or_dev` | `qa_automation` | 74 | apply_selectively | **7/10** |
| S2 | SaaS login/dashboard | `saas_multi_tenant_billing_auth_audit` | `saas_multi_tenant_billing_auth` | 81 | strong_apply | **9/10** |
| S3 | API testing | `api_testing` | `qa_automation` | 74 | strong_apply | **9/10** |
| S4 | UX walkthrough | `ai_native_exploratory_qa` | `ai_native_exploratory` | 95 | strong_apply | **9/10** |
| S5 | Technical writing | `technical_writing` | `technical_writing` | 81 | apply_selectively | **9/10** |
| S6 | Healthcare test design | `ai_native_exploratory_qa` | `ai_native_exploratory` | 81 | strong_apply | **8/10** |

*S6 routed to `ai_native_exploratory_qa` via bare "exploratory" keyword — known gap fixed by P1.1.*

---

## 13. Model Routing

### Profiles

| Profile name | Env var | Description |
|-------------|---------|-------------|
| `premium_hybrid` | `MODEL_PROFILE=premium_hybrid` | Production: gpt-5.5 + claude-sonnet-4-6 + claude-opus-4-7 |
| `mock` | `MODEL_PROFILE=mock` | Tests / dry-run: no API calls, no cost |

### premium_hybrid routing

| Role | Model | Purpose |
|------|-------|---------|
| `architect` | `gpt-5.5` | Prescreening, capability routing, strategy |
| `coding` | `anthropic/claude-sonnet-4-6` | Code / scaffold / test implementation notes |
| `review` | `anthropic/claude-opus-4-7` | Deep review, quality gate, self-health |
| `fast` | `anthropic/claude-sonnet-4-6` | Proposals, summaries, delivery notes |
| `vision` | `gpt-5.5` | Future screenshot / visual review |
| `fallback` | `gpt-5.4-mini` | Backup |

### LLM mode

```env
LLM_MODE=mock     # tests, structure validation, dry-run — no cost
LLM_MODE=real     # actual LLM calls — requires API keys
```

### Task aliases → model role

| Task alias | Role | Model (premium_hybrid) |
|------------|------|----------------------|
| `prescreen` | architect | gpt-5.5 |
| `playwright` | coding | claude-sonnet-4-6 |
| `quality_gate` | review | claude-opus-4-7 |
| `proposal` | fast | claude-sonnet-4-6 |

### Reasoning model protection

`LLMRouter.complete()` boosts `max_tokens = max(max_tokens, 8192)` before the try block when a reasoning model with `reasoning_effort` is detected. Prevents silent empty outputs.

### Mock fallback visibility (P1.5)

`LLMRouter.fallback_to_mock_count` tracks calls that degraded to mock after all real attempts failed. CLI prints a `WARNING` to stderr if > 0 after any run. Under `--require-real-llm`, returns exit code 2 unless `--allow-mock` is also set.

### Full profile reference

See `docs/MODEL_ROUTING_PROFILES.md` and `docs/V508_MODEL_ROUTING_NOTES.md`.

---

## 14. Human Approval and Safety

### What always fires

- `needs_human_review` approval state on every run — no exceptions.
- `HUMAN_REVIEW_REQUIRED.md` in every output folder.
- `QUALITY_GATE_REPORT.md` with 16 gate results.
- `APPROVAL_CHECKPOINTS.md` listing what Dmytro must verify before sending.

### 16 quality gates (all verified in validation)

Includes: `hardcoded_credentials`, `overclaims`, `deposit_or_identity_risk`, `responsible_discovery`, `mock_mode_warning`, `prompt_injection_or_ai_trap`, and 10 others. All consistently PASS across the 6 validation scenarios.

### What the system never does automatically

- Auto-submits anything to a client, platform, or external service.
- Uses real payment flows.
- Accesses or scrapes websites.
- Stores or prints secrets or credentials.
- Pushes to GitHub or any remote.
- Modifies `.env` or any credentials file.

### Before sending any output to a client, Dmytro must review

Claims · Evidence · Screening answers · Mandatory keywords · Price/rate · Scope · Credentials · Payment/security safety · Final wording

### Before real-site testing

1. Run `python main.py system-health` — all checks must pass.
2. Review `TESTING_READINESS_CHECKLIST.md` from the prescreen output.
3. Check `APPROVAL_CHECKPOINTS.md` — all items must be signed off.
4. Never use production credentials — staging/sandbox only.
5. For credential-required sites: fill `required_inputs` and stop; do not attempt bypass.

See `docs/REAL_TESTING_PREPARATION.md` and `docs/HUMAN_APPROVAL.md`.

---

## 15. Roadmap

### Current — completed 2026-05-24

- v5.0.9 validation-hardened (P1–P4 patches, 60/60 tests)
- P1 calibration patches (P1.1–P1.5, 69/69 tests)
- Strategic readiness audit completed
- Controlled demo-site testing ready

### Near-term

| Item | Priority | Source |
|------|----------|--------|
| Controlled demo-site testing | **High** | §9 runbook |
| `--test-depth` rapid delivery packs (P2.1) | Medium | Audit §8 |
| E-commerce checkout opportunity type (P2.2) | Medium | Audit F9 |
| API-specific prescreening branch (P2.3) | Low | Audit F5 |
| Soft-fix v5.0.x label drift (P2.4) | Low | Audit F1 |
| `docs/RUNBOOK.md` practical quick-reference (P2.5) | Low | Audit §12 |
| Monitor real LLM cost and fallback behavior | Medium | P1.5 tooling now in place |

### Later

| Item | Notes |
|------|-------|
| URL / browser recon intake | Playwright MCP not yet wired |
| Screenshot / vision intake | `vision` role reserved; intake not wired |
| Client / project memory | `memory/clients/` exists; full recall not implemented |
| Fiverr / PPH packaged gig flow | Future command `gig` |
| Direct B2B cold DM / one-page offer packs | Future command `opportunity` |
| LangGraph / RAG / UI | Deferred until CLI proves insufficient |
| Local benchmark playground | Docker / mock server for self-contained Playwright runs |

---

## 16. Strategic Decision Rules

Before adding a feature or merging a change, ask:

1. **Does this help win or deliver paid work in the next 2–4 weeks?** If not, defer.
2. **Does it improve QA/SDET positioning?** Or is it a distraction from the Senior QA brand?
3. **Does it reduce repeated manual work?** Or does it just add complexity with no time savings?
4. **Does it preserve human review?** Nothing auto-submits; nothing bypasses quality gates.
5. **Can it be modular?** Extension packs and profiles, not hardwired branches.
6. **Does it avoid fake evidence and unsafe claims?** Evidence required = human-confirmed only.
7. **Does it respect platform and client safety?** No credentials in output; no production access without written scope.

---

## 17. Remaining Known Gaps

### `api_testing` lacks a dedicated prompt profile (LOW)

`api_testing` maps to `qa_automation` profile, which is one sentence and Playwright-centric. Acceptable for now. P2.3 adds a prescreening branch with API-specific effort estimates. A dedicated `api_testing.md` prompt should follow after 3+ real API briefs.

### E-commerce checkout has no dedicated routing (LOW)

Briefs with checkout / cart / coupon / order-confirmation fall to `nextjs_react_frontend_qa_or_dev`. `prompts/qa_plan/retail_multi_app_pwa_pos.md` exists but is unmapped. P2.2 will add the type and wire it.

### Version label drift (LOW)

`main.py`, `tools/report_builder.py`, and scaffold README say `v5.0.8 Model Routing Profiles`. Tests pin these strings as substring checks. No functional impact — the README and v7 doc say v5.0.9. P2.4 will add a `(validation-hardened v5.0.9)` suffix without breaking tests.

### `output_index.md` is small in low-output runs (INFO)

`output_index.md` is generated from `state.generated_outputs.keys()` at save time. It is brief in low-output runs (dry-run, early-bail) and comprehensive in full runs. This is expected behavior — not a bug or inconsistency.

### botocore warning in real CLI runs (COSMETIC)

LiteLLM emits `WARNING: No module named 'botocore'` on every real run. Suppressed in pytest via `conftest.py`; visible in raw CLI output. No functional impact.

---

## 18. Documentation Status

| Document | Role | Status |
|----------|------|--------|
| `docs/AI_QA_Factory_Concept_and_Implementation_Plan_v7_validation_hardened.md` | **Single canonical concept doc** | This file — current |
| `docs/archive/AI_QA_Factory_Concept_and_Implementation_Plan_v6_model_routing.md` | Archived strategic source | Historical only — do not edit |
| `docs/VALIDATION_WEBSITE_TESTING_REPORT.md` | Validation evidence | 2026-05-24 run; 6 scenarios, P1–P4 patch list |
| `docs/REPO_STRATEGIC_READINESS_AUDIT_v1.md` | Audit source | 2026-05-24; P0/P1/P2/P3 patch plan, agent matrix |
| `README.md` | Quick start | Primary commands and model routing summary |

---

## 19. Documentation Index

| Document | Purpose |
|----------|---------|
| `README.md` | Quick start, main commands, model routing summary |
| `docs/RUNBOOK.md` | **Daily practical runbook** — what to run, what to open, troubleshooting |
| `docs/AI_QA_Factory_Concept_and_Implementation_Plan_v7_validation_hardened.md` | **This file** — current canonical reference |
| `docs/archive/AI_QA_Factory_Concept_and_Implementation_Plan_v6_model_routing.md` | Archived — v5.0.8 model routing detail (Russian + English) |
| `docs/VALIDATION_WEBSITE_TESTING_REPORT.md` | 2026-05-24 validation run — 6 scenarios, bugs found/fixed, patch list |
| `docs/REPO_STRATEGIC_READINESS_AUDIT_v1.md` | 2026-05-24 strategic readiness audit — P0/P1/P2/P3 patch plan |
| `docs/MODEL_ROUTING_PROFILES.md` | Full model profile reference |
| `docs/V508_MODEL_ROUTING_NOTES.md` | v5.0.8 model routing change notes |
| `docs/REAL_TESTING_PREPARATION.md` | Checklist before real-site/staging testing |
| `docs/CAPABILITY_MATRIX.md` | Opportunity type × stack × profile quick-reference |
| `docs/HUMAN_APPROVAL.md` | Human approval rule and review checklist |
| `docs/OPPORTUNITY_PRESCREENING_APPROVAL_FLOW.md` | Prescreening flow diagram |
| `docs/VSCODE_USAGE.md` | VS Code setup and archive/sharing hygiene |
| `docs/PRESCREENING_AND_EXECUTION_COCKPIT.md` | Prescreening + cockpit agent detail |
| `docs/PROJECT_EXTENSIONS_SELF_HEALTH_TEST_DESIGN.md` | Extension packs, self-health, test design agents |

---

## 20. What Is Deliberately Out of Scope

- Auto-submission to any external platform.
- Aggressive platform scraping or auto-polling.
- Autonomous inter-agent dialogue without human checkpoints.
- GitHub auto-push.
- Unsafe self-healing (agents cannot modify their own core logic).
- LangGraph / RAG / UI layer (until real CLI usage proves the need).
- Using AI to execute evaluator-platform paid tasks (platform policy violation).
- Real payment flows in any automated path.
- Unsupervised production delivery — human review must always fire.

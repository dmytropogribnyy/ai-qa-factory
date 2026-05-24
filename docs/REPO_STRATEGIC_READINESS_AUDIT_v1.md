# AI QA Factory — Strategic Readiness Audit v1

**Audit date:** 2026-05-24
**Reviewer role:** Senior software architect / QA automation lead / QA delivery consultant / practical product reviewer
**Subject:** AI QA Factory repository (current state post-v5.0.9 validation hardening)
**Goal:** Verify the repository is a coherent modular QA delivery operating system — not just a collection of agents, docs, and scripts — and identify the minimal practical work needed before controlled demo-site testing and later real staging testing.

---

## 1. Executive Verdict

The repository **is** a coherent modular QA cockpit. Routing, classification, artifact generation, safety gating, human-review enforcement, and persistence all work end-to-end. 60/60 tests green. Post-validation patches (P1–P4) closed the biggest routing bugs from the 2026-05-24 validation run.

**It is ready** for controlled demo-site testing on safe public apps and local briefs **today**, with no P0 blockers. It is conditionally ready for real staging-site work behind explicit human approval. It is **not** designed for unsupervised production use — by design.

The main hidden weaknesses are not architectural; they are calibration and version-label drift:

- The "exploratory / manual" keyword still hijacks routing for many briefs that mention manual testing as a phrase, not as a capability (known gap, low impact on artifacts).
- The CLI banner, scaffold README, summary headers, and several docs still say `v5.0.8 Model Routing Profiles` even though the README and v7 concept doc now say `v5.0.9`. This is a presentation issue, not a functional one, but creates confusion in delivery.
- The Playwright scaffold's default `baseURL=https://example.com` and overly permissive assertions (`toHaveTitle(/.+/)`, `[200, 204, 404]` for `/health`) produce false-green smoke runs out of the box. Human review catches this; the gate does not.
- The `api_testing` opportunity type has no dedicated prompt or pre-screening branch — it falls back to `qa_automation`. Acceptable for now; should grow its own profile when there are 3+ real API briefs.
- The `hardcoded_credentials` gate flags `TEST_USER_PASSWORD=` (the placeholder env-var name) as an error.

None of these are P0. The recommended P0 list is empty. P1 is a short calibration pass focused on the exploratory/manual over-trigger, the scaffold false-green assertions, and the credential-gate false positive. Together that is **2–4 hours of careful work**, safe for Sonnet to execute with focused prompts.

---

## 2. Ready / Conditional / Not Ready Table

| Stage | Verdict | Condition |
|-------|---------|-----------|
| Pytest mock suite | **Ready** | 60/60 pass; `tests/conftest.py` forces mock mode regardless of `.env` |
| Real-LLM dry runs on local briefs | **Ready** | All 6 validation scenarios verified; `max_tokens` boost prevents empty outputs |
| Controlled demo-site testing (public apps, no credentials) | **Ready** | Safety gates active; human review enforced; no auto-submit anywhere |
| Real staging-site testing (with credentials) | **Conditional** | Requires written scope, staging URL, test accounts, sandbox payment confirmation, and the per-run approval checkpoints to be signed |
| Real Upwork delivery with paid milestones | **Conditional** | Requires Dmytro to manually edit every client-facing artifact and verify quality-gate warnings before sending |
| Unsupervised production / autonomous client work | **Not supported by design** | Human-review checkpoint must fire on every run; that is intentional |

---

## 3. Architecture Integration Matrix

For each capability, this matrix scores whether the 10 required layers are present (✅), partial (⚠️), or missing (❌).

Layers: **1** Intake signal · **2** Routing/classification · **3** Capability/support-level decision · **4** Prompt profile · **5** Agent/workflow producing artifacts · **6** Output files · **7** Quality gate · **8** Human review · **9** Clear command · **10** Documentation/runbook

| Capability | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | Verdict |
|------------|---|---|---|---|---|---|---|---|---|----|---------|
| Playwright UI automation | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ⚠️ (false-green default assertions) | ✅ | ✅ `scaffold` | ✅ | **Strong** |
| API testing | ✅ | ✅ (post-P1) | ✅ `strong_execution` | ⚠️ falls back to `qa_automation` | ✅ `api_test_generator` | ✅ | ✅ | ✅ | ✅ `prescreen`/`test-design` | ⚠️ partial — no API-specific prompt or prescreen branch | **Good, can ship; calibration pending** |
| Sanity testing | ⚠️ no dedicated signal | ⚠️ subsumed in `smoke`/`scaffold` | ⚠️ inferred | ❌ no profile | ⚠️ via `qa_planner` + `playwright_generator` | ✅ generic | ✅ | ✅ | ⚠️ no `--test-depth sanity` | ❌ | **Partial** — works via generic flow, no first-class concept |
| Smoke testing | ⚠️ via `scaffold` workflow | ⚠️ inferred | ⚠️ inferred | ❌ | ✅ deterministic `smoke.spec.ts` | ✅ | ✅ | ✅ | ✅ `scaffold` | ⚠️ partial (in `qa_plan/default.md`) | **Partial** — produces artifacts but no depth control |
| Regression testing | ⚠️ keyword-based | ⚠️ flaky_regression_automation only | ✅ `strong_execution` | ✅ `flaky_tests.md` | ✅ test_strategy/plan/cases | ✅ | ✅ | ✅ | ✅ `test-design` | ⚠️ partial | **Partial** — regression depth not explicit |
| Test design (strategy/plan/cases) | ✅ | ✅ | ✅ | ⚠️ uses `qa_plan/{profile}` fallback | ✅ 3 dedicated agents | ✅ TEST_STRATEGY/PLAN/CASES | ✅ | ✅ | ✅ `test-design` | ✅ | **Strong** |
| Exploratory / manual QA | ✅ | ⚠️ over-triggers on "manual" keyword | ✅ `strong_execution` | ✅ `ai_native_exploratory.md` | ✅ qa_planner + reports | ✅ | ✅ | ✅ | ✅ `prescreen` | ✅ | **Strong but over-broad routing** |
| SaaS billing/auth/tenant audit | ✅ | ✅ post-P3 | ✅ `strong_execution` | ✅ dedicated profile | ✅ multi-agent | ✅ full pack | ✅ | ✅ | ✅ `prescreen`/`upwork`/`audit` | ✅ | **Strong** |
| E-commerce checkout QA | ⚠️ no dedicated signal | ⚠️ falls to `nextjs_react_frontend_qa_or_dev` after P3 | ⚠️ `supported_or_adjacent` | ⚠️ no dedicated profile; `retail_multi_app_pwa_pos.md` exists but is unmapped | ✅ via generic flow | ✅ | ⚠️ false-positive cred gate | ✅ | ✅ `scaffold` | ⚠️ | **Partial — works, no e-commerce-specific routing** |
| Documentation / technical writing | ✅ | ✅ | ✅ adjacent | ✅ dedicated profile | ✅ `technical_writing_agent` | ✅ | ✅ | ✅ | ✅ `prescreen` | ✅ | **Strong** |
| Mobile advisory (RN/Maestro) | ✅ | ✅ post-P2 | ✅ advisory | ✅ `mobile_release_qa` profile but no matching prompt file (`mobile_release_maestro.md` exists, not `mobile_release_qa.md` — falls back) | ⚠️ no dedicated mobile agent | ⚠️ minimal | ✅ | ✅ | ✅ `prescreen` | ✅ | **Partial — prompt-filename mismatch** |
| Tosca / advisory-only | ✅ | ✅ | ✅ | ✅ `skip_or_not_fit` | ✅ via opportunity_filter | ✅ | ✅ | ✅ | ✅ | ✅ | **Strong** |
| Risky / skip tasks | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ `deposit_or_identity_risk` gate | ✅ | ✅ `filter` | ✅ | **Strong** |

**Summary:** 8 capabilities **strong**, 4 **partial**, 0 **missing**. The two partial-capability gaps that affect daily practical usage most are (a) absence of a test_depth concept and (b) lack of e-commerce-specific routing/profile.

---

## 4. Top 10 Findings

Each finding includes the file/line and severity for triage.

### F1 — Version label drift between docs (v5.0.9) and code/scaffolds (v5.0.8) [LOW]
[main.py:61](main.py#L61) prints `"v5.0.8 Model Routing Profiles"` in the CLI banner; [main.py:171](main.py#L171) prints `"AI QA Factory v5.0.8 completed"`; [tools/report_builder.py:50](tools/report_builder.py#L50) writes `"AI QA Factory v5.0.8 Model Routing Profiles — Summary"` into every SUMMARY.md; [agents/playwright_generator.py:70](agents/playwright_generator.py#L70) stamps `"Generated by AI QA Factory v5.0.8 Model Routing Profiles"` into every scaffold README. Tests `test_v508_model_routing.py`, `test_v507_code_doc_sync.py`, and [tests/test_smoke.py:61](tests/test_smoke.py#L61) pin these strings. Functional impact: zero. Delivery impact: confusing — a client receiving a scaffold reads "v5.0.8" while the README says "v5.0.9".

### F2 — "exploratory" / "manual" keyword over-triggers `ai_native_exploratory_qa` [MEDIUM, known]
[agents/capability_router.py:68](agents/capability_router.py#L68) — the check runs BEFORE the SaaS, API, and flaky checks. Any brief that mentions the words "manual" or "exploratory" is captured first. The S6 healthcare brief illustrated this. Briefs that will misroute today: "we need manual regression testing of...", "exploratory pass before release...", "manual API testing only...". Profile and milestone wording become misleading; artifacts are still useful.

### F3 — Playwright scaffold has false-green default assertions [MEDIUM]
[agents/playwright_generator.py:143](agents/playwright_generator.py#L143) defaults `baseURL: 'https://example.com'`. [agents/playwright_generator.py:269](agents/playwright_generator.py#L269) `expect(page).toHaveTitle(/.+/)` matches any non-empty title. [agents/playwright_generator.py:288](agents/playwright_generator.py#L288) `expect([200, 204, 404]).toContain(response.status())` — a 404 from `/health` passes the smoke test. A user running `npm test` straight out of the scaffold against `example.com` sees green ticks that mean nothing. Human review catches it; the quality gate does not.

### F4 — `hardcoded_credentials` gate false-positives on the env placeholder [LOW]
[core/quality_gate.py:91](core/quality_gate.py#L91) pattern `r"TEST_USER_PASSWORD="` matches the literal variable name as it appears in `framework/.env.example`. The env file has only the variable name and an empty value, but the gate fires `ERROR`. Validation S1 scaffold flagged this. The gate should match a non-empty value, not the variable declaration.

### F5 — `api_testing` lacks a dedicated prompt profile and pre-screening branch [LOW]
[agents/capability_router.py:17](agents/capability_router.py#L17) maps `api_testing` → `qa_automation`. [prompts/proposal/qa_automation.md](prompts/proposal/qa_automation.md) is one sentence and Playwright-centric. [agents/prescreening.py:91](agents/prescreening.py#L91) has no api_testing branch; S3 falls into the generic `strong_execution` clause with the generic "Small milestone: 2–5 hours" effort. Acceptable for now; should grow its own profile after 3+ real API briefs.

### F6 — Mobile profile filename mismatch silently falls back to default [LOW]
[agents/capability_router.py:21](agents/capability_router.py#L21) maps `react_native_maestro_qa` → `mobile_release_qa`. The corresponding file would be `prompts/qa_plan/mobile_release_qa.md`, which does **not** exist. The actual file is `prompts/qa_plan/mobile_release_maestro.md`. [core/prompt_loader.py](core/prompt_loader.py) loads with `fallback="default"`, so the load succeeds silently and a mobile brief gets the generic default QA-plan prompt. Either rename the file or add an alias.

### F7 — LLM router silently degrades to mock on exception [LOW–MEDIUM]
[core/llm_router.py:111](core/llm_router.py#L111) — if both the primary model and the fallback fail, `complete()` returns a mock response with `used_fallback=True` and `error=str(first_exc)`. The structured logger records this, but the CLI banner says "completed" and returns exit 0. A `--require-real-llm` run that actually fell back to mock is not flagged in the human-facing output. Risk: silent degradation in real-mode runs.

### F8 — No test-depth concept (sanity / smoke / regression / full) [MEDIUM]
The CLI exposes modes (`prescreen`, `scaffold`, `test-design`, `audit`, `full`) but no depth flag. A user who wants "just a smoke pack" has to use `scaffold`, which produces a full Playwright framework. A user who wants "sanity post-deploy" has no first-class command. Solutions: (a) add `--test-depth {sanity,smoke,regression,full}` consumed by test_strategy/plan/case prompts; (b) keep deterministic scaffold + add a smoke-only template variant. Recommended: (a) — single state field + prompt addendum.

### F9 — No e-commerce checkout opportunity type [LOW–MEDIUM]
[agents/capability_router.py:59-86](agents/capability_router.py#L59) — no `e_commerce_checkout` entry. Briefs mentioning checkout/cart/coupon/stripe-sandbox/order-confirmation fall to `nextjs_react_frontend_qa_or_dev` (if React mentioned) or `general_qa_or_unknown`. A prompt file [prompts/qa_plan/retail_multi_app_pwa_pos.md](prompts/qa_plan/retail_multi_app_pwa_pos.md) exists but is unreachable from current routing. Either map it or add a dedicated type.

### F10 — `output_index.md` correctness is fine; the "inconsistency" was a misread [INFO]
[tools/file_manager.py:23](tools/file_manager.py#L23) — `output_index.md` is generated from `state.generated_outputs.keys()` at save time and lists everything written. The validation report noted "64-65 bytes in some runs, 800+ in others"; this reflects runs producing few vs many outputs (e.g. dry-runs or workflows that bailed early), not a bug in the index generator. The original v7 doc text should be softened from "inconsistent" to "small in low-output runs, comprehensive otherwise."

---

## 5. P0 / P1 / P2 / P3 Patch Plan

### P0 — Blockers before controlled demo-site testing

**None.** No P0 blockers identified. The repo can start controlled demo-site testing as-is, today.

### P1 — Strongly recommended before real staging-site testing

#### P1.1 — Narrow `ai_native_exploratory_qa` keyword trigger (F2)
- **Why:** "manual" and "exploratory" hijack SaaS, regression, and API briefs that happen to mention either word as common English. Misrouted briefs produce the wrong profile-specific milestone text.
- **Files:** [agents/capability_router.py:68](agents/capability_router.py#L68), [core/initial_analysis_engine.py:216](core/initial_analysis_engine.py#L216)
- **Change:** Require high-signal phrases alongside `exploratory`/`manual`: `loom`, `linear`, `jam.dev`, `screen recording`, `ai-native`, `release qa pass`, `hands-on qa`. Plain `exploratory` or `manual` alone should not trigger.
- **Effort:** 30–60 minutes. Two-line check + 3 regression tests (SaaS-with-"manual", regression-with-"manual exploratory", true ai_native_exploratory).
- **Risk:** Low. Existing `test_v508_model_routing.py` covers ai_native detection; add cases for SaaS-with-"manual" to lock the fix.
- **Acceptance:** S6 healthcare brief routes to `general_qa_or_unknown` or a test-design-friendly default; existing UX walkthrough brief (S4) still routes to `ai_native_exploratory_qa`.
- **Sonnet-safe?** Yes.

#### P1.2 — Fix Playwright scaffold false-green assertions (F3)
- **Why:** Out-of-the-box scaffold produces apparently-passing smoke tests against `example.com`. This is a delivery-quality issue, not a security issue.
- **Files:** [agents/playwright_generator.py:128-292](agents/playwright_generator.py#L128-L292)
- **Change:**
  - Remove the `baseURL` default of `'https://example.com'`; raise a clear error in `playwright.config.ts` if `BASE_URL` is empty, OR keep the default but add a `test.skip(!process.env.BASE_URL, ...)` guard on every spec.
  - Replace `expect(page).toHaveTitle(/.+/)` with a TODO comment + skipped test that requires the human to set a real title regex.
  - Narrow the API health spec to `[200, 204]` only; let `404` fail.
  - Add a top-of-README warning: "Tests are deliberately strict on first run; you must set `BASE_URL` and replace placeholder assertions before they pass."
- **Effort:** 30–45 minutes.
- **Risk:** Low–medium. The test `test_generated_scaffold_uses_v508_and_npm_install` does not check assertion content; safe to change. May need to add a regression test that asserts the scaffold contains `BASE_URL is required` or similar.
- **Acceptance:** Running the scaffolded tests against an empty/unset `BASE_URL` should fail loudly; running against `example.com` should not produce green.
- **Sonnet-safe?** Yes.

#### P1.3 — Fix `hardcoded_credentials` false positive (F4)
- **Why:** Wastes Dmytro's attention on every scaffold run.
- **Files:** [core/quality_gate.py:91](core/quality_gate.py#L91)
- **Change:** Tighten pattern from `r"TEST_USER_PASSWORD="` to `r"TEST_USER_PASSWORD=['\"]?[A-Za-z0-9!@#$%^&*\-_+]+"` (requires a non-empty value after `=`).
- **Effort:** 10 minutes + 1 regression test ("scaffold .env.example with empty TEST_USER_PASSWORD= must NOT trigger; a filled value must trigger").
- **Risk:** Negligible.
- **Sonnet-safe?** Yes.

#### P1.4 — Rename `mobile_release_qa.md` prompt (F6)
- **Why:** Silent fallback to default prompt for mobile briefs.
- **Files:** [prompts/qa_plan/mobile_release_maestro.md](prompts/qa_plan/mobile_release_maestro.md) → either rename to `mobile_release_qa.md`, OR add a thin alias `mobile_release_qa.md` that includes/duplicates the maestro content.
- **Effort:** 5 minutes.
- **Risk:** Negligible.
- **Sonnet-safe?** Yes.

#### P1.5 — Surface mock-fallback in real-mode CLI output (F7)
- **Why:** A `--require-real-llm` run that silently degraded to mock should not say "completed" without a warning.
- **Files:** [core/llm_router.py:111](core/llm_router.py#L111), [main.py:170-191](main.py#L170-L191)
- **Change:** After workflow completes, inspect `state.client_context` or query the router for any `used_fallback=True` calls. Print a one-line `WARNING: N LLM calls fell back to mock output. Check outputs/<id>/logs/factory.jsonl.` Optionally, in `--require-real-llm` mode, make a fallback-to-mock condition exit non-zero unless `--allow-mock` is also set.
- **Effort:** 45–60 minutes.
- **Risk:** Low. Touch the orchestrator state to count `used_fallback` events, or add a `fallback_count` to LLMRouter.
- **Acceptance:** Set `OPENAI_API_KEY=bad`, run real-mode prescreen, see the warning line and a non-zero exit when `--require-real-llm` was passed.
- **Sonnet-safe?** Yes (small, contained change).

### P2 — Useful quality improvements (not blocking real testing)

#### P2.1 — Add `--test-depth {sanity,smoke,regression,full}` (F8)
- **Files:** [main.py](main.py), [core/state.py](core/state.py), [agents/test_strategy_agent.py](agents/test_strategy_agent.py), [agents/test_plan_writer.py](agents/test_plan_writer.py), [agents/test_case_writer.py](agents/test_case_writer.py), [agents/playwright_generator.py](agents/playwright_generator.py).
- **Change:** Add a state field `test_depth: str = "smoke"`. Plumb a CLI flag. Pass into the test-design agent user prompts (e.g. `"Constrain output to {test_depth} depth: ..."`). For `playwright_generator`, conditionally include `tests/regression/` directory only at depth=regression+ and skip the `a11y` spec at depth=sanity.
- **Effort:** 2–3 hours.
- **Risk:** Medium. Mostly prompt + flag plumbing; state schema extension; no agent rewrites.
- **Sonnet-safe?** Yes with a clear spec.

#### P2.2 — Add `e_commerce_checkout` opportunity type (F9)
- **Files:** [agents/capability_router.py](agents/capability_router.py).
- **Change:** Add detection on `checkout`, `cart`, `coupon code`, `order confirmation`, `stripe sandbox` (the *combination*, not stripe alone). Map to existing `prompts/qa_plan/retail_multi_app_pwa_pos.md` or create `prompts/qa_plan/e_commerce_checkout.md`. Add to OPPORTUNITY_PROFILE_MAP.
- **Effort:** 1 hour including regression test that S1 routes here, not to `nextjs_react_frontend_qa_or_dev`.
- **Risk:** Low.

#### P2.3 — Add an `api_testing` prescreening branch (F5)
- **Files:** [agents/prescreening.py:91](agents/prescreening.py#L91).
- **Change:** Add a branch alongside `flaky_regression_automation` with API-specific effort estimate ("API smoke: 2–4 hours; full contract + negative coverage: 8–14 hours") and required_inputs (`OpenAPI spec`, `test tokens`, `rate limit awareness`).
- **Effort:** 30 minutes.
- **Risk:** Low.

#### P2.4 — Soft fix the v5.0.x label drift (F1)
- **Decision rule:** Pin to **one** explicit version label. Either (a) treat `v5.0.8 Model Routing Profiles` as the immutable internal release tag for the routing-profiles work and use `v5.0.9 — Validation-Hardened` as a documentation badge only; or (b) bump everything to `v5.0.9` and update the 5 tests pinned to v5.0.8.
- **Recommended:** (a) — change none of the code or tests. Add a single line to the CLI banner: `f"... v5.0.8 (validation-hardened v5.0.9)"`. The scaffold README gets the same treatment.
- **Files:** [main.py:61](main.py#L61), [main.py:171](main.py#L171), [tools/report_builder.py:50](tools/report_builder.py#L50), [agents/playwright_generator.py:70](agents/playwright_generator.py#L70).
- **Effort:** 15 minutes.
- **Risk:** Low. Existing test assertions check `"v5.0.8" in text` (substring), so adding `(validation-hardened v5.0.9)` does not break them.

#### P2.5 — Add an "open these first" runbook
- **Files:** new `docs/RUNBOOK.md`.
- **Change:** A single 60-line file: "For a brief X, run command Y, open file Z first." Covers prescreen / scaffold / test-design / upwork flows.
- **Effort:** 30 minutes.
- **Risk:** Zero.

### P3 — Defer until after real usage

- Add `--client-delivery-pack` flag to produce a sanitized client-facing subset (no internal SELF_HEALTH_REPORT, no triggered_pre_run_prompts).
- Promote `client-facing/` and `internal/` subfolders inside `outputs/<project_id>/`.
- URL/screenshot intake adapter.
- Replace keyword-based `_calculate_fit_score()` with a slightly smarter scoring profile per opportunity_type.
- Replace the one-sentence `prompts/proposal/qa_automation.md` and `prompts/qa_plan/default.md` with longer practical guides.
- Bug-report template generator (`bug_report_template.md`) producible from any project.

---

## 6. Practical Readiness by Website/App Testing Category

| Category | Verdict | Why | Required inputs | Risks | Minimal improvement | Today's command |
|----------|---------|-----|-----------------|-------|---------------------|-----------------|
| **A. Public demo e-commerce** | Conditional | Routing falls to `nextjs_react_frontend_qa_or_dev`, profile `qa_automation`; artifacts are generic. Stripe-sandbox detection works. | URL, scope, list of flows | False-green scaffold assertions (P1.2) | P2.2 e-commerce profile | `python main.py scaffold --input validation_inputs/01_ecommerce_checkout_demo.txt --auto` |
| **B. Safe login/demo apps** | Ready | Strong: routing → SaaS or generic QA; scaffold has LoginPage; safety gates active. | URL, test accounts (read-only), critical flows | Hardcoded creds gate false-positive (P1.3) | P1.3 | `python main.py scaffold --input <brief>` |
| **C. API-only testing** | Ready (post-P1) | api_testing type detected, profile fallback acceptable. | OpenAPI/Postman, base URL, tokens, allowed endpoints | No API-specific prompt (P2.3 improves) | P2.3 effort estimate | `python main.py prescreen --input validation_inputs/03_api_testing_scenario.txt --auto` |
| **D. SaaS auth/role/billing** | Ready | Strong end-to-end after P3: dedicated type, profile, prompt, milestone wording. | Tenant accounts, RBAC matrix, billing sandbox, scope | Manual/exploratory keyword hijack (P1.1) | P1.1 | `python main.py prescreen --input validation_inputs/02_saas_login_dashboard.txt --auto` |
| **E. UX walkthrough (Loom/Linear)** | Ready | Strong: `ai_native_exploratory_qa` profile, milestone references Loom/Linear, fit score 95. | Account access, Loom/Jam preference, critical paths | Routing label correct only when Loom/Linear is present | P1.1 also helps here | `python main.py prescreen --input validation_inputs/04_ux_walkthrough_usability.txt --auto` |
| **F. Test design only** | Ready | `test-design` mode runs full ROUTING_CORE + TEST_DESIGN_CORE; P4 explicit mode guards. | Brief, regulatory context, user roles | "exploratory" keyword still pulls S6 to ai_native (P1.1) | P1.1 | `python main.py test-design --input validation_inputs/06_test_design_only.txt --auto` |
| **G. Documentation/writing** | Ready | Dedicated `technical_writing` profile, agent, prompts. | One real writing sample, AI policy of outlet/client, source docs | None | None blocking | `python main.py prescreen --input validation_inputs/05_technical_writing_docs.txt --auto` |
| **H. Real staging w/ credentials** | Conditional | Safety gates active, pre-run prompts for payment/production/urgency, human review enforced. | Written scope, staging URL, test accounts, sandbox payment confirmation, browser/device matrix, credentials in `.env` only | Mock-fallback silent (P1.5) | P1.5 + signed `APPROVAL_CHECKPOINTS.md` per run | `python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm` |

---

## 7. Agent Readiness Matrix

| Task type | Existing support | Files | Output pack today | Fastest command | Required inputs | Minimal improvement |
|-----------|------------------|-------|-------------------|-----------------|-----------------|---------------------|
| Sanity testing | Partial via scaffold | playwright_generator.py | smoke.spec.ts | `python main.py scaffold` | URL, login flow | P2.1 `--test-depth sanity` |
| Smoke testing | Strong via scaffold | playwright_generator.py | smoke.spec.ts + health.spec.ts + a11y | `python main.py scaffold` | URL, critical flows | P1.2 fix false-green |
| Regression testing | Strong via test-design | test_strategy + plan + case writers | TEST_STRATEGY/PLAN/CASES | `python main.py test-design` | Brief, scope, regulatory | P2.1 `--test-depth regression` |
| UI testing | Strong | playwright_generator.py | Full Playwright framework | `python main.py scaffold` | URL, login, flows | P1.2 |
| API testing | Good | api_test_generator.py + playwright_generator (request) | api/health.spec.ts + notes | `python main.py scaffold` or `prescreen` | OpenAPI/Postman, base URL | P2.3, dedicated api prompt |
| Exploratory / manual QA | Strong | qa_planner + ai_native_exploratory profile | qa_plan.md + exploratory notes | `python main.py prescreen` | Brief, Loom/Linear preference | P1.1 narrow trigger |
| SaaS risk audit | Strong | full ROUTING_CORE + saas profile | Full audit pack | `python main.py audit` | Tenant accounts, scope | None blocking |
| Client delivery package | Good but unsegmented | report_builder.py + delivery_writer.py | READ_ME_FIRST + SUMMARY + delivery_note + full output dir | `python main.py full` or `upwork` | Approved scope, evidence | P3 client/internal split |

---

## 8. Rapid Delivery-Pack Design (Sanity / Smoke / Regression / UI / API / Exploratory)

### Recommended minimal design

**One new state field** on `QAFactoryState`: `test_depth: str = "smoke"` with allowed values `{sanity, smoke, regression, full, api_only, exploratory_only, test_design_only}`.

**One new CLI flag** in `main.py`: `--test-depth`, accepted by `scaffold`, `test-design`, `audit`, `full`.

**Prompt addenda** in test_strategy/plan/case agents:

| Depth | Strategy emphasis | Plan emphasis | Cases emphasis | Scaffold emphasis |
|-------|-------------------|---------------|----------------|-------------------|
| `sanity` | "post-deploy sanity only — critical paths and a single happy-path per role" | "limit to 5–10 cases" | smoke checklist + 1 critical case | only `tests/ui/smoke.spec.ts` |
| `smoke` | "critical flows + login + a11y smoke" | "10–25 cases across UI/API" | smoke + critical functional | smoke + api/health + a11y (today's default) |
| `regression` | "full regression with risk-based prioritization" | "30–80 cases organized by area" | full functional + negative + edge | add `tests/regression/` skeleton |
| `full` | "everything — strategy, plan, cases, scaffold" | "full coverage" | exhaustive | full framework |
| `api_only` | "API + contract + schema + negative" | "API endpoints only" | endpoint tables | only `tests/api/` |
| `exploratory_only` | "exploratory charters + Loom/Linear" | "no automation" | exploratory charters | no scaffold |
| `test_design_only` | "strategy/plan/cases, no scaffold" | "no execution" | full | no scaffold (already `test-design` mode) |

### Templates (no new agents needed)

A `templates/delivery_packs/` directory with markdown templates:
- `sanity_pack.md` — 1-page client delivery
- `smoke_pack.md` — 2-page
- `regression_pack.md` — 5–10 page
- `bug_report_template.md` — reusable
- `client_delivery_note.md` — short cover letter

These are **templates**, not generated artifacts. The system writes them once and they get curated by Dmytro per client.

### Effort

P2.1 above is the actual implementation: ~2–3 hours. The templates are 1 hour of writing.

---

## 9. Controlled Demo-Site Testing Runbook Proposal

Use this for the next stage of testing — local briefs + safe public demo apps only. No real client credentials, no real payments, no destructive actions.

### Demo briefs and sites to use first

The repo already has `validation_inputs/01–06`. Use them all again, plus 3 safe public demo apps:

| # | Source | Why safe | Command |
|---|--------|----------|---------|
| Run 1 | `validation_inputs/01_ecommerce_checkout_demo.txt` | Local brief, demo wording | `python main.py scaffold --input validation_inputs/01_ecommerce_checkout_demo.txt --auto` |
| Run 2 | `validation_inputs/02_saas_login_dashboard.txt` | Local brief | `python main.py prescreen` + `python main.py test-design` |
| Run 3 | `validation_inputs/03_api_testing_scenario.txt` | Local brief, API-only | `python main.py prescreen` + `python main.py test-design` |
| Run 4 | `validation_inputs/06_test_design_only.txt` | Local brief, no execution | `python main.py test-design` |
| Run 5 | https://demoqa.com/ — written brief, no credentials | Public learning site, low-risk forms | `python main.py prescreen --input <brief>` and **manually** review the scaffold — do not execute it autonomously |
| Run 6 | https://www.saucedemo.com/ — written brief, public demo accounts | Used for QA training, accepts standard_user / secret_sauce | Same — prescreen + manual scaffold review |
| Run 7 | https://opensource-demo.orangehrmlive.com/ — written brief | Public HRM demo, Admin / admin123 | Same |

### What to do on each run

1. Run prescreen (or scaffold / test-design).
2. Open in order: `READ_ME_FIRST.md` → `DECISION.md` → `PRESCREENING_REPORT.md` → `QUALITY_GATE_REPORT.md` → `HUMAN_REVIEW_REQUIRED.md`.
3. Read the routing decision: opportunity_type, support_level, recommended_action, profile.
4. Compare against expectation. If misrouted, record as a gap (don't fix during the run).
5. If scaffold was produced: do NOT `npm test` against the public demo site yet — open the generated `framework/README.md` and verify placeholders are flagged.
6. Record the outcome in `outputs/<project_id>/MANUAL_AUDIT_NOTES.md` (created manually).

### Pass / fail criteria

- **Pass:** routing correct OR misrouted but artifacts still useful (per validation report standard); all 16 quality gates fire; HUMAN_REVIEW_REQUIRED.md exists; no credentials in any file; no auto-submit attempted.
- **Fail:** auto-submit detected; credentials written to an output file; quality gate skipped; routing produces invented evidence; scaffold passes against `https://example.com` with green ticks (this is the P1.2 case).

### What not to do during demo testing

- No real payment, even sandbox, until P1.5 is in.
- No production sites.
- No credentials in input briefs (the briefs say "credentials to be provided" — keep it that way).
- No `npm test` against demo sites until BASE_URL and assertions are reviewed (P1.2 makes this safer).

---

## 10. Real Staging-Site Readiness Checklist

Use this **before** running any `python main.py upwork --require-real-llm` flow against a real client staging environment.

### Written scope
- [ ] Client has provided written scope (in writing, email or PR)
- [ ] Scope explicitly states: target URL, in-scope pages/flows, out-of-scope, timebox
- [ ] Client has explicitly stated "staging only" or named the staging URL
- [ ] Stop conditions agreed (per `APPROVAL_CHECKPOINTS.md`)

### Environment access
- [ ] Staging URL responds and is on a different domain than production
- [ ] Test accounts provisioned (at least one per role)
- [ ] Test data is synthetic — no PII, no real customer records
- [ ] API base URL (if any) is staging
- [ ] OpenAPI spec / Postman collection (if API testing)
- [ ] Bearer/JWT tokens for staging only
- [ ] Rate limits known

### Safety
- [ ] Payment sandbox confirmed in writing (test cards only)
- [ ] No destructive actions allowed (delete, drop, refund, dispute)
- [ ] Stripe / payment provider is in test mode (visible in dashboard)
- [ ] No production database access
- [ ] Credentials are in `.env` only, never in input briefs or output reports

### Reporting
- [ ] Bug report format agreed: Linear / Jira / Loom / Jam / Notion
- [ ] Severity rubric agreed (typically S1/S2/S3 with examples)
- [ ] Daily / end-of-engagement summary format agreed
- [ ] Delivery artifacts list agreed (qa_plan, test_strategy, test_cases, bug_report, delivery_note)

### Device / browser matrix
- [ ] Browsers: Chromium / Firefox / WebKit — agreed which
- [ ] Viewports: desktop only or desktop + mobile responsive
- [ ] Real mobile devices (RN/Maestro) — confirm Mac/Xcode/TestFlight access (P1.4 + prescreen blockers fire)

### System readiness
- [ ] `python main.py system-health` — all checks pass
- [ ] `python -m pytest -q` — 60/60 green
- [ ] `.env` has real model IDs + API keys
- [ ] `MODEL_PROFILE=premium_hybrid` (or chosen profile)
- [ ] `python main.py prescreen --input <client_brief.txt> --require-real-llm` returns a real LLM response (not mock fallback — P1.5 will surface this)

### Human approval per run
- [ ] `APPROVAL_CHECKPOINTS.md` signed off
- [ ] `PRESCREENING_REPORT.md` reviewed
- [ ] `factory_can_do` / `factory_should_not_do` boundaries confirmed
- [ ] No client-facing artifact sent without manual edit pass

---

## 11. Test Coverage Gaps

The 60 tests cover routing, profile mapping, mode guards, capability router authority, and the validation regression cases. **Missing tests that would catch real risks** before staging:

| # | Test | Why | File to add |
|---|------|-----|-------------|
| T1 | `test_manual_keyword_does_not_hijack_saas_brief` | F2/P1.1 | tests/test_v509_routing_calibration.py |
| T2 | `test_scaffold_baseurl_default_is_explicit_or_skipped` | F3/P1.2 | tests/test_v509_scaffold_quality.py |
| T3 | `test_scaffold_health_does_not_accept_404` | F3/P1.2 | tests/test_v509_scaffold_quality.py |
| T4 | `test_hardcoded_credentials_gate_ignores_empty_placeholders` | F4/P1.3 | tests/test_v509_quality_gate.py |
| T5 | `test_mobile_release_qa_prompt_loads_real_content` | F6/P1.4 | tests/test_v509_prompts.py |
| T6 | `test_real_mode_fallback_to_mock_surfaces_warning` | F7/P1.5 | tests/test_v509_llm_router.py |
| T7 | `test_e_commerce_brief_does_not_route_to_react_frontend` | F9/P2.2 | tests/test_v509_routing_calibration.py |
| T8 | `test_test_design_mode_with_no_keywords_still_produces_three_artifacts` | regression-only | tests/test_v509_test_design.py |
| T9 | `test_documented_commands_match_cli_argparse_choices` | docs ↔ CLI drift | tests/test_v509_doc_sync.py |
| T10 | `test_safety_gate_count_is_16` | guard against gates being silently dropped | tests/test_v509_quality_gate.py |

---

## 12. Documentation Gaps

| Gap | Where | Severity |
|-----|-------|----------|
| `README.md` has the v5.0.9 title but body still says "v5.0.8 includes" | [README.md:9](README.md#L9) | LOW (informational drift) |
| `docs/CAPABILITY_MATRIX.md` title still says `v5.0.8 Model Routing Profiles` | [docs/CAPABILITY_MATRIX.md:1](docs/CAPABILITY_MATRIX.md#L1) | LOW |
| `docs/REAL_TESTING_PREPARATION.md` title says "v5.0.8" | [docs/REAL_TESTING_PREPARATION.md:1](docs/REAL_TESTING_PREPARATION.md#L1) | LOW |
| `docs/AI_QA_Factory_Concept_and_Implementation_Plan_v7_validation_hardened.md` says `output_index.md` is "inconsistently populated" — this is incorrect (F10) | v7 doc section 9 | LOW |
| No `docs/RUNBOOK.md` — "open these first" practical reference | new file | MEDIUM (helps daily usage) |
| No `docs/E_COMMERCE_TESTING_NOTES.md` / `docs/API_TESTING_NOTES.md` to capture per-category nuances | new files | LOW (after P2.2/P2.3) |
| `docs/HUMAN_APPROVAL.md` referenced from v7 but not read in this audit — confirm it exists and is up-to-date | docs/HUMAN_APPROVAL.md | LOW |

---

## 13. Safety Gaps

| Item | Status | Note |
|------|--------|------|
| Credential leakage | Strong | `.env` in `.gitignore`; conftest forces mock; HardcodedCredentialsCheck active (with F4 false-positive) |
| Auto-submission | Strong | No agent submits to any external service; PreScreening explicitly lists `factory_should_not_do` |
| Payment safety | Strong | Pre-run prompt fires on `stripe`/`checkout`/`billing` keywords in interactive mode |
| Production protection | Strong | Pre-run prompt fires on `production`/`live` |
| Deposit/identity risk | Strong | Capability router + quality gate both detect |
| Prompt-injection / AI-trap | Strong | Detection in capability_router, screening_answers, and quality_gate |
| Responsible discovery | Adequate | Limited to keyword trigger; relies on prompts being honest |
| Archive hygiene | Adequate | `docs/VSCODE_USAGE.md` now has the exclusion list |
| **Silent mock fallback** | **Gap (F7)** | Real-mode runs can silently degrade to mock without CLI warning. P1.5 fixes this. |
| Pre-run prompt for "credentials provided in plaintext in brief" | Missing | Add a 4th trigger that fires if the brief contains anything matching `password\s*[:=]\s*\S+` or `token\s*[:=]\s*\S+` |

**Dangerous defaults present?** Mostly no. The two presentation-level dangerous defaults are:
1. The Playwright scaffold's `baseURL=https://example.com` (F3 — produces false confidence).
2. The silent mock-fallback path (F7 — produces false completion signal).

Neither is a security hole. Both produce **false-success signals** that human review catches but the gate does not.

---

## 14. LLM Routing and Reliability Notes

### Strengths
- [core/llm_router.py:77-78](core/llm_router.py#L77-L78) — `max_tokens = max(max_tokens, 8192)` early boost prevents the empty-output bug from reasoning models. Confirmed working.
- [core/llm_router.py:131](core/llm_router.py#L131) — model-specific param handling (Anthropic Opus rejects non-default temperature) is correct.
- [tests/conftest.py](tests/conftest.py) forces mock + LiteLLM warning suppression — tests are deterministic and cheap.
- [core/orchestrator.py:229-244](core/orchestrator.py#L229-L244) — structured logger records every LLM call with `model_alias`, `used_fallback`, token counts, cost — observability is present.

### Risks
- **F7 silent fallback to mock.** Single biggest reliability concern. P1.5 fixes it.
- **Cost risk:** with `max_tokens=8192` boost on every reasoning-effort call, premium_hybrid runs (gpt-5.5 architect at `effort=high`) can produce expensive completions. Validation runs showed ~5K output tokens consumed. For a full `upwork` workflow this could be 10–15 LLM calls. **Concrete cost estimate:** at 8192 max_tokens × 15 calls = ~120K tokens per run; at gpt-5.5 rates this is significant. Worth monitoring `total_tokens` in factory.jsonl across the first 5 real runs.
- **botocore warning is cosmetic.** Confirmed: suppressed in pytest, still visible in CLI. Not a fix priority.
- **No retry budget tracking:** the router retries fallback model + minimal-params retry per call. A persistently-failing primary model can burn 4× cost per call. Not currently observable from CLI.

### Recommendations
- P1.5 (mock-fallback warning) is the only must-have.
- P3: add a `--max-cost-usd` budget guard that exits early when `state.client_context["total_cost_usd"]` exceeds threshold.

---

## 15. Prompts / Templates / Scaffold Notes

### Prompts
- 18 proposal profiles, 9 qa_plan profiles, 4 delivery profiles. Good coverage breadth.
- [prompts/qa_plan/default.md](prompts/qa_plan/default.md) and [prompts/proposal/qa_automation.md](prompts/proposal/qa_automation.md) are **one sentence each**. These are the fallback prompts used by all unmapped opportunity types (including `api_testing` and `nextjs_react_frontend_qa_or_dev`). Sufficient because the user_prompt in each agent provides the structural skeleton, but worth expanding (P3).
- [prompts/qa_plan/test_strategy.md](prompts/qa_plan/test_strategy.md), `test_plan.md`, `test_cases.md` exist and are used by the test_strategy/plan/case agents.
- **Mismatch (F6):** capability router maps `react_native_maestro_qa` → `mobile_release_qa` profile, but the prompt file is `mobile_release_maestro.md`. Silent fallback to default. P1.4 fixes.
- No `api_testing.md`, no `e_commerce_checkout.md` prompts — F5 / F9.

### Templates
- [templates/playwright-ts/package.json](templates/playwright-ts/package.json) and `playwright.config.ts` exist as raw templates; the actual scaffold generation is in [agents/playwright_generator.py](agents/playwright_generator.py) which embeds the content inline. Two sources of truth — minor duplication; not a blocker.
- [templates/k6/k6-smoke.js](templates/k6/k6-smoke.js) — k6 performance template, used by performance_agent.py. Confirmed.
- [templates/selenium-java/README.md](templates/selenium-java/README.md) — advisory only, no execution path.
- **Missing:** delivery-pack templates (bug_report_template, client_delivery_note, sanity_pack, smoke_pack, regression_pack). Recommended in section 8.

### Scaffold quality
- Deterministic scaffold separation from LLM notes is **respected** ([playwright_generator.py:44-46](agents/playwright_generator.py#L44-L46)). Good.
- **F3 false-green assertions** are the main quality issue. P1.2 fixes.
- Scaffold README claims "Generated by AI QA Factory v5.0.8 Model Routing Profiles" — F1 label drift.
- Generated `framework/.env.example` exposes `TEST_USER_PASSWORD=` as variable name with empty value — this is correct behavior but triggers F4 false positive.
- `tests/a11y/basic-a11y.spec.ts` uses `@axe-core/playwright` with `impact === 'critical'` filter — sensible default.
- `framework/.github/workflows/playwright.yml` uses `npm install` not `npm ci` (intentional per `test_generated_scaffold_uses_v508_and_npm_install`) — fine for client repos that lack `package-lock.json` from scaffold.

---

## 16. Recommended Next Sonnet Implementation Prompt

If the user wants Sonnet to land P1 patches before staging tests, this is the prompt to send. It is self-contained, lists the exact patches, names files, includes acceptance criteria, and respects the project's no-architecture-rewrite rule.

```
You are working inside the AI QA Factory repository. Goal: land P1 calibration patches
from docs/REPO_STRATEGIC_READINESS_AUDIT_v1.md. Do not change architecture.
Do not change model routing. Do not touch .env or secrets. Do not run real LLM calls.
Do not bump v5.0.8 to v5.0.9 in code or tests (label drift handled separately).

P1.1 — Narrow ai_native_exploratory_qa keyword trigger.
- agents/capability_router.py:68: require one of {loom, linear, jam.dev, screen recording,
  ai-native, hands-on qa, release qa pass} alongside "exploratory"/"manual".
  Plain "exploratory" or "manual" alone must not trigger.
- core/initial_analysis_engine.py:216: same narrowing applied.
- Add 3 regression tests in tests/test_v509_routing_calibration.py:
  * test_saas_brief_with_manual_keyword_routes_to_saas
  * test_regression_brief_with_exploratory_keyword_routes_to_flaky_or_general
  * test_true_ai_native_with_loom_still_routes_to_exploratory

P1.2 — Fix Playwright scaffold false-green assertions.
- agents/playwright_generator.py:143: change baseURL default from 'https://example.com'
  to a guard: add a top-of-config check that throws if BASE_URL is unset, or use
  baseURL: process.env.BASE_URL (no default).
- agents/playwright_generator.py:264 (ui smoke): replace expect(page).toHaveTitle(/.+/)
  with test.skip(!process.env.BASE_URL, 'BASE_URL must be set') and a TODO assertion
  comment requiring a real title regex.
- agents/playwright_generator.py:288 (api health): narrow expect([200, 204, 404])
  to expect([200, 204]) — let 404 fail.
- agents/playwright_generator.py:67 (README content): add a "First-run setup" section
  listing: set BASE_URL, replace title assertion, replace /health endpoint, replace
  selectors after MCP/browser inspection.
- Add 2 regression tests:
  * test_scaffold_does_not_default_to_example_com
  * test_scaffold_api_health_rejects_404

P1.3 — Fix hardcoded_credentials false positive.
- core/quality_gate.py:91: change pattern r"TEST_USER_PASSWORD=" to
  r"TEST_USER_PASSWORD=['\"]?[A-Za-z0-9!@#$%^&*\-_+]+" (requires non-empty value).
- Add 2 regression tests:
  * test_empty_TEST_USER_PASSWORD_does_not_trigger_credentials_gate
  * test_filled_TEST_USER_PASSWORD_does_trigger_credentials_gate

P1.4 — Fix mobile prompt filename mismatch.
- Either rename prompts/qa_plan/mobile_release_maestro.md to mobile_release_qa.md,
  or create prompts/qa_plan/mobile_release_qa.md that includes the maestro content
  verbatim. Recommended: rename to keep one source of truth.
- Add 1 test: test_mobile_release_qa_profile_loads_non_default_prompt.

P1.5 — Surface mock fallback in real-mode CLI output.
- core/llm_router.py: add a public attribute fallback_count: int = 0 on LLMRouter,
  increment in the LLMResponse(used_fallback=True) branches.
- main.py:170-191: after orchestrator.run() returns, read orchestrator.router.fallback_count
  (you'll need to expose it via the orchestrator). If > 0, print
  "WARNING: {count} LLM calls fell back to mock output. Check outputs/{project_id}/logs/factory.jsonl."
- If args.require_real_llm and fallback_count > 0 and not args.allow_mock,
  exit with code 2 and an explicit message.
- Add 1 test: test_real_mode_with_failed_primary_emits_fallback_warning (mock the
  litellm completion call to raise; assert the warning is in stderr).

Acceptance:
- All existing 60 tests still pass.
- 9 new regression tests added and pass.
- Run `python main.py system-health` — exits 0.
- Run `python main.py prescreen --input validation_inputs/02_saas_login_dashboard.txt --auto`
  on a SaaS brief with "manual testing" appended — opportunity_type must be
  saas_multi_tenant_billing_auth_audit, not ai_native_exploratory_qa.

When done: report which files changed, which tests were added, and whether tests pass.
Do not run real LLM calls. Use only `.venv\Scripts\python.exe -m pytest -q`.
```

---

## Final summary

- **P0 blockers:** none.
- **P1 calibration:** five small patches, ~3–4 hours total, all Sonnet-safe.
- **Controlled demo-site testing can start today** with the existing artifacts; the runbook in section 9 lists 7 safe runs to execute.
- **Real staging-site testing** is conditional on P1.5 (mock-fallback warning), the section-10 checklist, and per-run human approval.
- **Sonnet implementation is recommended** before going to real staging — but not required for demo-site testing.

The repository is genuinely a coherent QA delivery operating system. It needs calibration, not rewriting.

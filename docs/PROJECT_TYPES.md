# Project Types — Guided QA Automation Workbench

**Version:** 5.1.0-workbench-alpha  
**Updated:** 2026-05-24

This document describes the project types the workbench classifies and handles. Classification happens in `agents/capability_router.py` based on keywords and context in the input brief.

---

## Support levels

| Level | Meaning | Typical action |
|---|---|---|
| **strong_execution** | Core competency — full automation scaffold | `strong_apply` or `full` workflow |
| **supported_or_adjacent** | Within reach — partial scaffold + advisory | `apply_selectively` |
| **advisory_only** | Can advise, cannot fully automate | `advisory_only` output |
| **manual_review** | Unclear fit — needs human judgement | `review_manually` |
| **skip_or_high_risk** | Out of scope or actively risky | `skip_*` |

---

## Project types

### 1. SaaS multi-tenant billing / auth audit

**Classification triggers:** multi-tenant, billing, subscription, tenant isolation, OAuth, RBAC, role-based access, SSO, payment flow

**Support level:** strong_execution

**What the workbench produces:**
- Full Playwright TypeScript scaffold with role-based test fixtures
- Auth flow test cases (login, logout, session expiry, MFA)
- Billing test cases (subscription upgrade/downgrade, payment sandbox)
- Multi-tenant isolation checks (cross-tenant data bleed)
- RBAC test matrix

**Key constraints:**
- Payment flows: sandbox/test mode only, confirmed in writing
- Auth credentials: in `.env` only, never in briefs or specs
- Multi-tenant scenarios require separate test accounts per role

**Prompt profile:** `saas_multi_tenant_billing_auth`  
**Recommended workflow:** `scaffold` or `full`

---

### 2. API testing

**Classification triggers:** REST API, OpenAPI, Swagger, Postman, API-only, bearer token, JWT, endpoint testing, API test suite

**Support level:** strong_execution

**What the workbench produces:**
- API test suite (Playwright API mode or Supertest advisory)
- Endpoint coverage matrix
- Auth header handling (Bearer, API key, OAuth2)
- Request/response schema validation
- Error case coverage (4xx, 5xx, rate limiting)

**Key constraints:**
- API base URL: staging only until approved
- Auth tokens: in `.env`, not in test files

**Prompt profile:** `api_testing`  
**Recommended workflow:** `scaffold` or `test-design`

---

### 3. AI-native exploratory QA

**Classification triggers:** AI-native, exploratory QA, release QA, session-based testing, Loom, Jam.dev, hands-on QA, heuristic testing

**Support level:** strong_execution

**What the workbench produces:**
- Exploratory session charters
- Heuristic test coverage notes
- Risk-based testing strategy
- Bug reporting templates
- Loom/Jam.dev session recording guidance

**Key constraints:**
- Exploratory QA cannot be fully automated — workbench produces strategy and charters, not scripts
- No invented Loom recordings or session examples

**Prompt profile:** `ai_native_exploratory_qa`  
**Recommended workflow:** `test-design`

---

### 4. Flaky / regression automation

**Classification triggers:** flaky tests, failing test suite, recurring bugs, test maintenance, brittle selectors, waitForTimeout, unreliable CI

**Support level:** strong_execution

**What the workbench produces:**
- Flakiness analysis via `FlakinessCriticAgent`
- Selector quality assessment (XPath, nth-child, aria-label usage)
- Assertion pattern review (web-first vs. sleep-based)
- Refactoring recommendations
- Stable selector alternatives

**Key constraints:**
- The workbench reviews and advises — it does not automatically rewrite test files

**Prompt profile:** `qa_automation`  
**Recommended workflow:** `review`

---

### 5. Technical writing / QA documentation

**Classification triggers:** technical writer, documentation, help center, API docs, developer guide, QA handbook, test documentation

**Support level:** supported_or_adjacent

**What the workbench produces:**
- Documentation structure and outline
- Technical writing plan
- Content scope and audience definition
- Style and terminology notes

**Key constraints:**
- Not core QA automation — treated as adjacent
- Apply selectively based on scope and budget

**Prompt profile:** `technical_writing`  
**Recommended workflow:** `test-design` or `full`

---

### 6. React Native + Maestro mobile QA

**Classification triggers:** React Native, Expo, iOS, Android, TestFlight, Maestro, mobile QA, app testing

**Support level:** supported_or_adjacent

**What the workbench produces:**
- Maestro flow script advisory
- Mobile test strategy
- Device coverage matrix (emulator vs. real device)
- CI integration notes (GitHub Actions + Maestro)

**Key constraints:**
- The workbench generates advisory notes and strategy — not full Maestro scripts from scratch
- Real device testing requires device access not managed by the workbench
- Declared honestly: only advisory unless specific Maestro experience exists

**Prompt profile:** `qa_automation` (with mobile extension pack)  
**Recommended workflow:** `scaffold` with `ProjectExtensionAgent`

---

### 7. Next.js / React frontend QA

**Classification triggers:** Next.js, React, TypeScript frontend, component testing, Storybook, Vitest, frontend automation

**Support level:** manual_review

**What the workbench produces:**
- Component test strategy advisory
- E2E test scope (Playwright for UI flows)
- Integration test boundary notes

**Key constraints:**
- Frontend QA is adjacent — worth reviewing manually before committing
- May overlap with developer role (component unit tests are developer work, not QA automation)

**Prompt profile:** varies  
**Recommended workflow:** `prescreen` first, then manual decision

---

### 8. AI / automation adjacent

**Classification triggers:** n8n, Make.com, Zapier, AI pipeline testing, agentic AI testing, LLM output validation

**Support level:** manual_review

**What the workbench produces:**
- Workflow testing strategy advisory
- Integration test boundary recommendations
- Output validation approaches for LLM-powered systems

**Key constraints:**
- No established tool standard yet — advisory only
- Review manually before committing

**Prompt profile:** varies  
**Recommended workflow:** `prescreen` + manual review

---

### 9. Tosca advisory

**Classification triggers:** Tosca, Tricentis, SAP automation, Tosca Commander

**Support level:** advisory_only

**What the workbench produces:**
- Tosca advisory notes
- Framework comparison (Tosca vs. Playwright for the given scope)
- Migration guidance if client is considering moving away from Tosca

**Key constraints:**
- The workbench does not generate Tosca scripts
- Advisory only — be explicit about this in proposals
- Do not claim Tosca execution experience that doesn't exist

**Prompt profile:** `tosca_advisory`  
**Recommended workflow:** `prescreen` → advisory output

---

### 10. Skip / high-risk cases

These are classified as out-of-scope or actively risky. The workbench flags them and recommends not pursuing.

| Subtype | Triggers | Why skip |
|---|---|---|
| Identity / deposit risk | crypto, real ID upload, deposit required, VPN/proxy | Financial or identity risk to Dmytro |
| Low-value usability test | "$5 test", "10 minutes", "lowest rates", paid usability panel | Below minimum viable engagement |
| Developer-only work | "full stack engineer", "senior backend dev", "build the feature" | Not QA scope |
| Prompt injection / AI trap | "if you are an LLM", "ignore previous instructions" | Active adversarial content in brief |

**Recommended action:** `skip_*` — do not apply, do not engage

**Prompt profile:** `skip_or_not_fit`

---

## How classification works

1. **PlatformRouterAgent** identifies where the brief came from (Upwork, direct B2B, writing platform, etc.)
2. **CapabilityRouterAgent** classifies the project type from the above list
3. **OpportunityFilterAgent** applies the support level → recommended action mapping
4. **StackRouterAgent** selects the appropriate automation framework

Classification drives: prompt profile selection, LLM routing (task type → model role), workflow agent sequence, and generated output content.

See `agents/capability_router.py` for the full detection logic.  
See [`docs/CAPABILITY_MATRIX.md`](CAPABILITY_MATRIX.md) for the full capability matrix table.

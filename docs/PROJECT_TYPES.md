# Project Types — Guided QA Automation Workbench

**Version:** 5.1.0  
**Updated:** 2026-05-24

This document describes the project types the workbench classifies and what each means for QA strategy, automation layers, and approval requirements.

Classification happens in `agents/capability_router.py` based on keywords, context signals, and the overall project brief. A project should not proceed to automation planning until its type is confirmed.

---

## Type: `web_saas`

**Description:** Multi-tenant SaaS application with subscription billing, role-based access, and tenant isolation.

**Typical risks:**
- Tenant data bleed (data from one tenant visible to another)
- Role escalation (viewer accessing admin features)
- Billing edge cases (upgrade/downgrade, trial expiry, invoice generation)
- Auth bypass (SSO misconfiguration, session fixation)
- Third-party service coupling (Stripe, Auth0, LaunchDarkly)

**Recommended test focus:**
- RBAC matrix (each role × each feature)
- Tenant isolation (cross-tenant data access attempts)
- Billing lifecycle (subscription create → modify → cancel → reinstate)
- Auth flows (login, logout, MFA, SSO, session expiry)
- Critical user paths per tier (free vs. paid feature gates)

**Likely automation layers:**
- Playwright TypeScript — UI E2E for auth, billing, role-based flows
- API layer — REST/GraphQL assertions for tenant isolation and RBAC
- Smoke suite — critical path verification on deploy

**Approval-sensitive areas:**
- Any test touching billing or payment — requires sandbox confirmation
- Auth flows with real tokens or SSO — requires test account confirmation
- Cross-tenant scenarios — requires explicit written scope

---

## Type: `ecommerce`

**Description:** Online store with product catalog, cart, checkout, and payment processing.

**Typical risks:**
- Cart state corruption (item count, pricing, promotions)
- Checkout flow breaks (especially on mobile or slow connection)
- Payment gateway failures (sandbox vs. live mode confusion)
- Inventory sync issues (overselling, stock count mismatch)
- Promotion/coupon logic errors

**Recommended test focus:**
- Add-to-cart → checkout → payment (happy path and failure paths)
- Guest vs. authenticated checkout
- Promotion code application and stacking rules
- Payment decline handling and retry
- Order confirmation and email delivery
- Out-of-stock and availability guards

**Likely automation layers:**
- Playwright TypeScript — UI flow automation (cart, checkout, order history)
- API layer — order creation, payment intent, inventory validation
- Visual regression — product pages, cart UI consistency

**Approval-sensitive areas:**
- Payment flow testing — **sandbox mode must be confirmed in writing before any run**
- Real card data — never used; Stripe test card set only
- Order creation against real inventory — requires explicit scope

---

## Type: `api_backend`

**Description:** REST API, GraphQL API, or microservice backend. May or may not have a frontend.

**Typical risks:**
- Auth header handling errors (missing Bearer, expired JWT, wrong scope)
- Schema drift (API response fields added/removed/renamed without versioning)
- Error code inconsistency (500 vs. 422 vs. 400 for the same condition)
- Rate limiting not enforced or too aggressive
- Pagination and filtering edge cases

**Recommended test focus:**
- Contract testing — response schema matches OpenAPI spec
- Auth boundary — unauthenticated, wrong token, expired token, insufficient scope
- CRUD operation coverage per resource
- Error response shape consistency
- Rate limiting behaviour (happy path and throttled path)
- Idempotency for POST/PUT operations

**Likely automation layers:**
- Playwright API mode or Supertest — HTTP-level assertions
- Contract testing — if OpenAPI spec is available
- Load advisory — k6 notes for performance-sensitive endpoints

**Approval-sensitive areas:**
- Calls against a live staging or production API — requires `--approve` + scope
- Write operations (POST/PUT/DELETE) against any real environment — requires explicit scope
- Auth token usage — staging-only tokens, never real user credentials

---

## Type: `ai_generated_app`

**Description:** Application with LLM-powered features — AI chat, AI content generation, AI-assisted workflows. Non-deterministic output by nature.

**Typical risks:**
- Output non-determinism (same input → different output → test brittleness)
- Prompt injection via user input
- Hallucination in critical flows (wrong medical advice, wrong financial calculation)
- Latency variability (LLM calls can be slow or timeout)
- Boundary between AI and deterministic logic not clearly defined

**Recommended test focus:**
- Deterministic wrapper layers (UI, API boundaries, not LLM output itself)
- Input sanitization (prompt injection attempts)
- Fallback and error handling when LLM is unavailable or slow
- Smoke tests on critical flows (not asserting on LLM output content, asserting on UI state)
- Human-in-the-loop flows (approve/reject AI suggestions)

**Likely automation layers:**
- Playwright TypeScript — UI state and flow assertions (not AI output content)
- API layer — input/output schema, error handling
- Exploratory test charters — for AI output quality review (manual)

**Approval-sensitive areas:**
- Any test that submits real user data to a live LLM endpoint — requires scope
- Security testing (prompt injection) — requires written authorization
- Load testing AI endpoints — requires rate limit confirmation

---

## Type: `admin_panel`

**Description:** Internal dashboard for managing users, data, configuration, or operations. Typically role-restricted.

**Typical risks:**
- Unauthorized access to admin features from regular user roles
- Bulk operations without confirmation (mass delete, mass update)
- Data display errors (truncation, encoding, pagination gaps)
- Audit trail gaps (admin actions not logged)
- Export features exposing sensitive data

**Recommended test focus:**
- Role access matrix (admin vs. manager vs. read-only)
- Bulk operation safety (confirmation dialogs, undo/rollback)
- Data table correctness (filtering, sorting, pagination edge cases)
- Export content validation (correct data, correct format)
- Audit log coverage (key admin actions are recorded)

**Likely automation layers:**
- Playwright TypeScript — role-based access flows, data table interactions
- API layer — permission enforcement at backend level
- Manual exploratory — bulk operation edge cases

**Approval-sensitive areas:**
- Any test using real admin credentials — requires test account confirmation
- Tests against production admin panel — requires explicit read-only scope
- Tests that trigger bulk operations — requires explicit scope and rollback plan

---

## Type: `auth_heavy`

**Description:** Application where authentication and authorization are the primary complexity — OAuth, MFA, SSO, identity providers, fine-grained permissions.

**Typical risks:**
- Session fixation, session hijacking vulnerability
- MFA bypass flows
- OAuth callback forgery (CSRF on redirect URI)
- Token leakage in URLs or logs
- Fine-grained permission gaps (missing check on one endpoint)
- Account takeover via password reset flow

**Recommended test focus:**
- Full auth lifecycle (register, login, logout, session expiry, refresh)
- MFA enrollment and bypass attempts
- Password reset flow security (token expiry, one-time use)
- OAuth flow (authorization code, PKCE, callback validation)
- Role and permission boundary testing
- Session management (concurrent sessions, forced logout)

**Likely automation layers:**
- Playwright TypeScript — UI auth flows
- API layer — token validation, permission enforcement
- Security advisory notes — for penetration testing scope (manual authorization required)

**Approval-sensitive areas:**
- All auth flow testing — requires test account confirmation
- Security testing (auth bypass, session manipulation) — requires written authorization
- Any test that touches real user accounts — blocked without explicit scope

---

## Type: `mixed_ui_api`

**Description:** Full-stack application where both the UI and the API need coverage, and they interact in non-trivial ways.

**Typical risks:**
- UI and API contract drift (frontend uses fields the API has renamed)
- State synchronization errors (optimistic UI showing stale data)
- Error handling gaps (API returns error, UI shows spinner forever)
- Feature flag consistency (feature toggled on in UI but API not updated, or vice versa)

**Recommended test focus:**
- E2E flows that cross UI and API boundaries
- API contract tests matching what UI actually calls
- Error scenario coverage (network failure, API timeout, 4xx/5xx) in the UI
- Feature flag behavior across both layers

**Likely automation layers:**
- Playwright TypeScript — UI E2E including network interception
- API layer — contract tests matching the OpenAPI spec or actual network calls
- Playwright `page.route()` — mock API responses for UI error path testing

**Approval-sensitive areas:**
- Same as `api_backend` and `web_saas` combined for their respective areas

---

## Type: `unknown`

**Description:** Project type could not be classified from the provided input.

**This type must be resolved before any automation work proceeds.**

A project classified as `unknown` means:
- The brief did not contain enough information to determine the tech stack or application type
- The brief may describe multiple application types without a clear primary one
- The input format was not recognized

**What to do:**
1. Run `prescreen` — it will list what information is missing
2. Provide a more detailed brief or ask the client for clarification
3. Re-run prescreen after adding context
4. Only proceed to scaffold or test-design after classification succeeds

---

## Classification signals used by the workbench

The capability router uses keyword and context signals to classify project types. Classification also depends on `source_platform` (Upwork, direct B2B, etc.) and the initial analysis engine output.

Strong signals per type:

| Signal | Likely type |
|---|---|
| multi-tenant, billing, RBAC, SSO | `web_saas` |
| cart, checkout, payment, Stripe | `ecommerce` |
| REST API, OpenAPI, endpoints, microservices | `api_backend` |
| AI, LLM, GPT, Claude, chatbot, non-deterministic | `ai_generated_app` |
| admin panel, internal dashboard, backoffice | `admin_panel` |
| OAuth, MFA, SAML, identity, SSO, session | `auth_heavy` |
| frontend + API, full-stack, React + Node | `mixed_ui_api` |
| unclear, mixed, no dominant signal | `unknown` |

See `agents/capability_router.py` for the full detection logic.

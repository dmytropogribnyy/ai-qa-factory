# Current Runtime Capability Matrix

This page describes what the checked-out product can do now. The `capabilities` command prints the
exact Factory and Scout versions at runtime, so this document does not carry a version number that
can silently drift.

Status vocabulary:

- **runtime** — executable product path covered by deterministic tests;
- **conditional** — executable only when the named dependency, credential, approval, or environment
  is ready;
- **generator/planning** — produces plans, drafts, scaffolds, or review material; it is not proof
  that a client system was exercised;
- **not runtime** — advisory or deliberately deferred.

## Operator and Scout

| Capability | Status | What is actually available | Boundary / evidence |
|---|---|---|---|
| Guided QA workbench | runtime | Routes briefs and produces deterministic QA, review, delivery, and Playwright scaffold artifacts | AI output is a draft; human review remains required |
| Client-work lifecycle | runtime | Local persisted approval, validation, review, repair, and delivery-preparation states | Does not autonomously execute or deliver client work |
| Scout static inspection | runtime | Bounded HTTP/HTML QA over explicit public URLs, verified findings, reports, and persisted state | Read-only; private/local targets, unsafe redirects, CAPTCHA, and prohibited access fail closed |
| Scout Deep Capture | conditional | Real Chromium screenshots, axe, timing, console/network observations, and redacted browser trace | Requires Playwright + Chromium; current automatic Scout execution remains read-only navigation |
| Evidence bundle | runtime | Separate landing/verification screenshots when available, redacted JSON, SHA-256 manifest, and Dashboard/Observer linkage | Missing capture is reported as missing, never synthesized |
| Reproduction video | conditional | Short WebM from the same bounded context that reproduces a broken flow-entry navigation | Qualified-auto only; requires Playwright; no clicks/forms and no clip unless reproduction completes cleanly |
| Dashboard | runtime | Loopback operator UI for Overview, Work, Scout, Tools, Activity, Settings, Docs, history, target detail, and guarded lifecycle controls | Local `127.0.0.1`; CSRF/Origin/Host and ownership checks; not a hosted multi-user service |
| Observer MCP | runtime | Read-only project, campaign, run, target, evidence, and diagnostic views | The connected process may require restart/deployment after code changes; build identity exposes stale code |
| Discovery through Tavily | conditional | Bounded live prospect discovery and promotion into the existing Scout engine | Requires key plus explicit live approval; budgets, terms, suppression, and URL safety fail closed |
| Scheduling | conditional | Existing local scheduler wrapper for operator-approved campaign commands | Depends on host scheduler support and local configuration |
| Outbound email | conditional | Draft/review/approval pipeline and guarded provider path; dry-run by default | Requires separate credentials, exact recipient confirmation, reviewer approval, and enabled controls; QA findings never authorize sending |

## Generation and planning

| Capability | Status | Honest interpretation |
|---|---|---|
| Playwright + TypeScript scaffold | generator/planning | Generates a runnable starter structure and CI notes; target-specific selectors and flows still require evidence and validation |
| Web/SaaS/API QA plans | generator/planning | Produces risk, coverage, test-design, and review artifacts; a plan is not a completed live audit |
| Opportunity and feasibility analysis | generator/planning | Uses declared requirements and current tool readiness; it does not contact a platform or client |
| Mobile/native, formal compliance, deep load, or formal penetration testing | not runtime | Advisory only unless a separately authorized environment and specialist workflow are supplied |
| Screenshot-only client-input understanding | not runtime | Scout can capture screenshots from a URL, but the core CLI does not treat an uploaded screenshot as a complete autonomous audit input |
| Automatic reversible business interactions | not runtime | Policy objects and deterministic fixtures exist, but the current Scout engine does not wire them into live automatic execution |
| Parallel Scout site execution | not runtime | `--concurrency` must remain `1` |

## Reliability contract

- A capability is not “available” merely because an MCP server or package is declared; readiness is
  reported separately by `tool-status`, `system-health`, `scout doctor`, and campaign preflight.
- Static and browser results are labelled separately. Static accessibility/performance checks are
  heuristics, not axe/Lighthouse results.
- Evidence is bounded, path-confined, redacted, secret-scanned where applicable, and linked to the
  exact campaign/run/prospect. Absent evidence is shown as absent.
- Dashboard and Observer target detail select the newest persisted campaign decision; explicit run
  links remain pinned to the requested run.
- No QA flow may purchase, book, submit forms, create accounts, solve CAPTCHAs, evade access
  controls, or send outreach.

## Claim rule

Use **runtime** only for an executable, tested path. Use **conditional** when a real dependency or
approval is still required. Treat generated text, schemas, profiles, and policies as
**generator/planning** until runtime evidence proves execution.

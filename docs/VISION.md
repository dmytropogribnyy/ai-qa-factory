# Product Vision — Guided QA Automation Workbench

**Version:** 5.1.0  
**Updated:** 2026-05-24

---

## One sentence

A guided, AI-assisted QA automation workbench for senior QA consultants doing real client work — not a generator, not an autopilot.

---

## The problem it solves

A senior QA automation consultant takes on a client project and immediately has to juggle:

- Understanding what the client actually needs (which is rarely what they say they need)
- Classifying the application: SaaS? e-commerce? API? auth-heavy?
- Building a test strategy that fits the tech stack and risk profile
- Producing a concrete test plan, test cases, and automation scaffold
- Selecting the right tools for the job
- Getting approval before touching production-adjacent systems
- Collecting evidence that work was done correctly
- Producing two kinds of reports: internal notes and a clean client-facing deliverable

This takes time. A lot of it is structured and repeatable. A workbench can assist.

---

## What it is — and what it is not

**It is:** A local CLI platform that understands your project context, builds a structured first draft of everything, and stops for your review at every decision point that matters.

**It is not:**
- A full autopilot. No artifact goes to a client without human sign-off.
- A browser agent. It does not open URLs, log into applications, or run tests against live systems without explicit approval.
- A one-size-fits-all generator. It classifies input before acting.
- A heavy-dependency framework. LangGraph, Allure, LangSmith, and Playwright MCP are optional.

---

## Why it's closer to Lovable / Make / n8n than to a simple script

Lovable turns a description into a working web app through a guided, iterative loop.  
Make/n8n turn a workflow description into a running automation.  
Both are:
- Input-driven (you describe, it builds)
- Structured (each step is visible and editable)
- Guided (you approve before things run)
- Composable (steps chain into a full pipeline)

This workbench applies the same pattern to QA automation consulting:

| Step | What happens |
|---|---|
| You provide input | Brief, task URL, screenshots, API docs, archive |
| System classifies | Project type, tech stack, risk profile, input source vs. target |
| System builds blueprint | Structured source of truth for the project |
| System plans strategically | QA approach, coverage areas, risk-based priorities |
| System plans tactically | Test cases, scenarios, edge cases, automation layers |
| System selects tools | Playwright-TS, API testing, advisory for mobile/Tosca |
| System asks approval | Before anything touches a real environment |
| System executes safely | Local validation only, unless approved for external |
| System collects evidence | What ran, what was found, what was skipped |
| System reports | Internal summary + client-facing deliverable (separately gated) |

The difference from Lovable/Make: every step that could harm a client system or produce misleading output is blocked until you explicitly approve it.

---

## Core workflow formula

```
Understand
    → Classify Inputs
    → Build Project Blueprint
    → Plan Strategically
    → Plan Tactically
    → Select Tools
    → Ask Approval (for anything external)
    → Execute Safely
    → Collect Evidence
    → Report Clearly
```

This is the backbone of every client project workflow — regardless of whether the project is a SaaS audit, an API test suite, or an e-commerce checkout automation.

---

## Supported input types

| Input type | Status | Notes |
|---|---|---|
| Text brief (paste or file) | Implemented | Core input for all current workflows |
| Task URL (Jira, Linear, Notion) | Planned (Phase 2) | Classified, not fetched automatically |
| Target application URL | Planned (Phase 2) | Classified separately from task URL |
| Screenshots | Planned (Phase 2) | Via vision model role |
| Archive / zip | Planned (Phase 3) | Repo or project context |
| Repo reference | Planned (Phase 3) | Code context for test generation |
| API documentation (OpenAPI, Postman) | Planned (Phase 3) | Structured endpoint ingestion |

**Key rule:** Classifying a URL (knowing it exists) is separate from fetching or acting on it. The system will classify URLs before any action. Fetching requires a separate approval decision.

---

## Supported project types

| Type | Description |
|---|---|
| `web_saas` | Multi-tenant SaaS, subscription billing, RBAC, SSO |
| `ecommerce` | Cart, checkout, payment flows, order management |
| `api_backend` | REST API, GraphQL, OpenAPI spec, microservices |
| `ai_generated_app` | LLM-powered UX, non-deterministic behavior, prompt testing |
| `admin_panel` | Internal dashboards, data tables, role access |
| `auth_heavy` | OAuth, MFA, session management, SSO, identity |
| `mixed_ui_api` | Full-stack apps where both layers need coverage |
| `unknown` | Not yet classified — must be resolved before automation |

---

## Human-in-the-loop safety model

The workbench has two operating zones:

**Safe zone (automatic):**
- Reading and classifying input
- Generating strategy, test plans, scaffold files
- Running local validation (TypeScript compile, lint, playwright dry-run)
- Writing output files to `outputs/`

**Approval zone (blocked until approved):**
- Running tests against any external URL (staging, demo, production)
- Testing payment, auth, or security-sensitive flows
- Generating client-facing reports (separate from internal summaries)
- Any destructive or state-changing action

Approval is execution-mode-based, not domain-based. The workbench does not infer safety from URL patterns or robots.txt. Every external execution requires an explicit decision.

---

## Target outcome

The workbench should feel like having a very capable junior consultant who:

1. Reads everything you give it carefully
2. Asks clarifying questions when something is ambiguous
3. Builds a complete first draft of the project structure, test plan, and automation scaffold
4. Lists what it needs from you before it can proceed (credentials, scope, approval)
5. Waits for your sign-off before touching anything real
6. Produces clean internal notes and a separate polished client deliverable

You, as the senior QA automation consultant, make every judgment call. The workbench does the drafting, structuring, and scaffolding.

---

## Roadmap

| Phase | Status | What it adds |
|---|---|---|
| 1A | Done | Docs, identity alignment, `core/version.py` |
| 1B | Next | Schema models: `InputMap`, `ProjectBlueprint`, `AutomationPlan`, `ApprovalDecision` |
| 2 | Planned | Universal input classifier (URL classification, not fetching) |
| 3 | Planned | `ProjectBlueprintAgent` — structured source of truth |
| 4 | Planned | `client` and `intake` workflow modes |
| 5 | Planned | Safe execution boundary surfaced in CLI |
| 6 | Planned | Internal vs. client-facing report stratification |

# Product Vision — Guided QA Automation Workbench

**Version:** 5.1.0-workbench-alpha  
**Date:** 2026-05-24

---

## What it is

The Guided QA Automation Workbench is a local, AI-assisted QA automation platform for real client projects.

It accepts a brief, job post, or project description; classifies the input; builds a QA strategy and test automation plan; generates a Playwright TypeScript scaffold; and stops — waiting for Dmytro's review before anything reaches a client or a live environment.

Think of it as a very fast, very thorough junior QA engineer that prepares a complete first draft of everything and then hands it to the senior for sign-off.

---

## What it is not

- Not a full autopilot. Nothing is sent or executed without approval.
- Not a browser agent. It does not open URLs, scrape sites, or run Playwright against real environments unless explicitly approved for a specific run.
- Not an autonomous delivery system. Client-facing artifacts always require human review.
- Not a mandatory-heavy-dependency stack. LangGraph, Allure, LangSmith, and Playwright MCP are optional.

---

## Evolution from AI QA Factory

The project started as "AI QA Factory" — a freelancing operating system for evaluating Upwork opportunities and generating proposals.

It is evolving into a broader **QA automation workbench** that handles real ongoing client projects, not just opportunity evaluation:

| Old focus | New focus |
|---|---|
| Evaluate freelancing opportunities | Deliver real client QA automation projects |
| Generate Upwork proposals | Build project blueprints, test strategies, automation scaffolds |
| Route by opportunity type | Route by project type and client context |
| Proposal + prescreening | Full intake → strategy → automation → validation → delivery |

The old workflows (`prescreen`, `filter`, `upwork`, `batch-filter`) remain fully supported. New workflows for client project delivery (`client`, `intake`) are being added incrementally.

---

## Core principles

**1. Guided, not autonomous**  
The workbench proposes. Dmytro decides. Every risky action has an explicit approval gate.

**2. Universal input, classified before action**  
Accepts text briefs, job posts, client descriptions, API spec references, and eventually URLs and screenshots. Always classifies the input before acting — never assumes.

**3. Distinguish task source from application under test**  
A brief may describe where the task came from (Upwork, client email, Linear ticket) AND what the target application is (SaaS dashboard, mobile app, REST API). These are separate concepts with separate handling.

**4. Project Blueprint as source of truth**  
Before generating test artifacts, the workbench builds a structured Project Blueprint: project name, target context, tech stack, scope, open questions, approval status. Downstream agents consume this, not raw text.

**5. Safety by default**  
Local operations (file writes, TypeScript compilation check, mock runs) are automatic. External execution (hitting staging URLs, running Playwright against real environments) requires explicit approval per run.

**6. Incremental delivery**  
Phases are small and verifiable. Each phase preserves all existing tests and workflows. No big-bang rewrites.

---

## Intended workflow (target state)

```
Input (brief / job post / description)
        ↓
Input classification (text? url? api spec? screenshot?)
        ↓
Context analysis (platform, tech stack, project type, risks)
        ↓
Project Blueprint (source of truth — Dmytro reviews)
        ↓
Strategic QA Plan   +   Automation Plan
        ↓
Tool / framework selection (Playwright-TS, API, mobile advisory, ...)
        ↓
Scaffold generation (Playwright TS project, API test suite, ...)
        ↓
Safe local validation (TypeScript compile, lint, dry-run — automatic)
        ↓
Human approval gate (Dmytro signs off)
        ↓
Evidence collection
        ↓
Internal report (always)   |   Client report (explicit flag + approval only)
        ↓
Delivery
```

---

## What already works (v5.0.9 → v5.1.0)

- Input: text file briefs (all modes)
- Context analysis: 11 opportunity types, 6 source platforms, stack detection
- Opportunity routing: prescreen / filter / upwork / batch-filter
- Test design: test-design mode → TEST_STRATEGY.md + TEST_PLAN.md + TEST_CASES.md
- Scaffold: scaffold mode → full Playwright TypeScript project
- Approval gates: HUMAN_REVIEW_REQUIRED.md, --approve flag, triggered pre-run prompts
- Role-based LLM routing: architect / coding / review / fast / vision roles
- Quality gate: 16 checks post-workflow
- State persistence: snapshots, --from-step, --only, --project-id

## What is being added (v5.1.x)

Phase 1A (this release): documentation, identity alignment, core/version.py  
Phase 1B (next): structured schema models (InputMap, ProjectBlueprint, AutomationPlan, ...)  
Phase 2: universal input classifier (URL classification, not fetching)  
Phase 3: Project Blueprint agent  
Phase 4: client / intake workflow modes  
Phase 5: safe execution layer surfacing  
Phase 6: internal vs. client report stratification

# Pre-screening & Execution Cockpit

AI QA Factory v5.0.8 adds a practical control layer before any client work begins.

## Purpose

Before Dmytro spends Connects, accepts a project, tests a real site, or sends a proposal, Factory must answer:

- Is this opportunity suitable?
- Can Factory help fully, partially, advisory-only, or not at all?
- What is the approximate effort/timebox?
- What inputs, credentials, evidence, devices or APIs are required?
- Which workflow should run next?
- Where does Dmytro need to approve before automation continues?

## Main artifacts

Every opportunity run should generate:

- `READ_ME_FIRST.md` — human-friendly top-level guide
- `PRESCREENING_REPORT.md` — suitability, rough effort, blockers, required inputs
- `DECISION.md` — apply/skip/advisory decision
- `NEXT_ACTIONS.md` — what to do next
- `EXECUTION_FLOW.md` — recommended workflow and commands
- `APPROVAL_CHECKPOINTS.md` — human approval gates
- `SYSTEM_DIALOG_GUIDE.md` — how to talk to the system after the run
- `TESTING_READINESS_CHECKLIST.md` — APIs/tools/access needed for real testing
- `PROJECT_INTAKE_CHECKLIST.md` — what to collect from client before execution

## Working model

```text
Text / link / screenshot notes / job post
  ↓
Platform Router
  ↓
Capability Router
  ↓
Opportunity Filter
  ↓
Pre-screening Report
  ↓
Human Approval
  ↓
Execution workflow: upwork / audit / scaffold / full / review / delivery
  ↓
Human-readable reports + final approval
```

## Important limitation

Factory can analyze pasted job text and prepared briefs now. A URL or screenshot is not enough by itself unless the relevant content is pasted/described. Future adapters may support browser fetch, OCR, screenshots and visual recon, but production decisions still require human review.

## Real-site testing readiness

For real sites/apps, prepare:

- approved target URL(s)
- staging/test environment or explicit production-safe scope
- test accounts and roles
- credentials stored only in `.env`
- test data / email aliases / phone number where needed
- browser/device matrix
- reporting format: Google Doc, Linear/Jira, Loom/Jam, screenshots
- explicit boundary: no scraping, no destructive actions, no real payments, no unauthorized security testing

## Required APIs/tools for real testing

Minimum:

- Real LLM provider via LiteLLM/OpenAI/Claude-compatible API
- Playwright browsers if generating/running web tests
- `.env` for credentials and model IDs

Optional by project:

- GitHub token/repo access
- Linear/Jira access
- Loom or Jam.dev account
- TestFlight / Google Play Internal Testing access
- Xcode / Android Studio / Maestro for mobile work
- Postman/API collection
- Stripe test mode / sandbox credentials

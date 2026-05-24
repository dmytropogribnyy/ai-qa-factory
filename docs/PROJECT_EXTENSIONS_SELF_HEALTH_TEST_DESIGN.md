# v5.0.8 — Project Extensions, Self-Health and Test Design

## Purpose

AI QA Factory must be able to adapt to a concrete project without becoming a chaotic universal platform.

v5.0.8 adds three practical layers:

1. **Project Extension Packs** — temporary, approval-based prompt/checklist/specialist suggestions for a specific opportunity.
2. **Self Health Monitor** — safe consistency checks and a human-readable repair plan.
3. **Test Design Agents** — dedicated generation of test strategy, test plan and test cases beyond the general QA plan.

## Project extension packs

Project-specific extension packs are suggested when the opportunity mentions special tools, domains or workflows such as:

- Tosca
- Maestro / React Native / Expo
- Sharetribe
- n8n / Make.com
- Stripe / billing
- multi-tenant SaaS
- PWA/offline
- BullMQ / async workers
- Linear / Loom bug reporting
- technical documentation
- test strategy / test plan / test cases

They create `PROJECT_EXTENSION_PLAN.md`.

### Rule

Extension packs are not automatically activated as permanent capabilities.

They may add:

- project-specific prompts;
- checklists;
- advisory notes;
- sample artifact structure;
- temporary specialist suggestions.

They must not:

- invent experience;
- claim hands-on expertise that Dmytro does not have;
- auto-submit proposals;
- run destructive tests;
- change client systems;
- become permanent complexity without proof of reuse.

## Self Health Monitor

`SelfHealthMonitorAgent` generates:

- `SELF_HEALTH_REPORT.md`
- `SYSTEM_REPAIR_PLAN.md`

It checks for issues such as:

- unclear decision;
- low fit but non-skip recommendation;
- missing screening answers;
- missing evidence report;
- suitability/action conflicts;
- unanswered safety prompts;
- unapproved project extension packs;
- missing test-design artifacts in test-design workflows.

### Safe auto-fix boundary

Allowed:

- create missing local markdown placeholders;
- recommend re-running selected agents;
- propose prompt/profile repairs;
- flag conflicts for human review.

Not allowed:

- no auto-submission to platforms;
- no GitHub auto-push;
- no destructive commands;
- no real payments;
- no client-system changes;
- no invented evidence.

## Test design agents

v5.0.8 separates general QA planning from specific test-design artifacts.

Agents:

- `TestStrategyAgent` → `TEST_STRATEGY.md`
- `TestPlanWriterAgent` → `TEST_PLAN.md`
- `TestCaseWriterAgent` → `TEST_CASES.md`

These artifacts are useful for:

- Upwork proposals requiring testing approach;
- client audit/discovery projects;
- manual QA tasks;
- technical documentation/testing deliverables;
- pre-delivery planning;
- converting requirements/Figma/briefs into test cases.

## Commands

```bash
python main.py test-design --input sample_inputs/client_brief.txt --allow-mock
python main.py plan --input sample_inputs/client_brief.txt --allow-mock
python main.py full --input sample_inputs/client_brief.txt --allow-mock
```

For targeted regeneration:

```bash
python main.py test-design --input sample_inputs/client_brief.txt --only test_strategy --allow-mock
python main.py test-design --input sample_inputs/client_brief.txt --only test_plan_writer --allow-mock
python main.py test-design --input sample_inputs/client_brief.txt --only test_case_writer --allow-mock
```

## Practical working style

The system should feel like a cockpit:

1. Pre-screen the opportunity.
2. Review decision and suitability.
3. Approve or reject extension packs.
4. Generate strategy/plan/cases only where useful.
5. Review self-health and repair plan.
6. Approve final client-facing text or delivery artifacts.

AI drafts. Senior QA decides.

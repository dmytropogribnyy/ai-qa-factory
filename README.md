# Guided QA Automation Workbench v5.1.0

> **AI drafts. Senior QA decides.**

A practical, local, AI-assisted QA automation platform for real client projects.
Built for Dmytro Pogribnyy — SDET / QA Automation Lead.

The system classifies your input (job brief, client brief, test file), routes it to the right
workflow, builds a test strategy and automation scaffold, and then stops and waits for your review
before anything goes to a client or touches a real environment.

It is not a full autopilot. It is a **guided workbench**: AI proposes, Dmytro decides.

See [`docs/VISION.md`](docs/VISION.md) for the full product direction.
See [`docs/APPROVAL_MODEL.md`](docs/APPROVAL_MODEL.md) for the safety and approval model.
See [`docs/COMMANDS.md`](docs/COMMANDS.md) for the full command reference.

---

<!-- Legacy product identity — preserved for internal sync tests: AI QA Factory v5.0.9 — Validation-Hardened QA/SDET Cockpit -->

A practical local AI-assisted opportunity + QA delivery operating system for Dmytro Pogribnyy.

It is not Playwright-only. Playwright + TypeScript is the strongest execution zone, but the system now routes broader opportunities: QA, manual exploratory testing, SaaS audit, API testing, mobile advisory, Tosca advisory, technical writing, AI automation-adjacent work, microservices and skip/risk cases.

*Builds on v5.0.8 Model Routing Profiles — upgraded and validated to v5.0.9.*

> AI drafts. Senior QA decides.

## What v5.0.8 includes



### Project extensions, self-health and test design

- `ProjectExtensionAgent` suggests temporary project-specific extension packs for special stacks/domains without making them permanent.
- `SelfHealthMonitorAgent` creates `SELF_HEALTH_REPORT.md` and `SYSTEM_REPAIR_PLAN.md` with safe repair suggestions.
- `TestStrategyAgent`, `TestPlanWriterAgent` and `TestCaseWriterAgent` create `TEST_STRATEGY.md`, `TEST_PLAN.md` and `TEST_CASES.md`.
- New mode: `test-design` for generating test strategy / plan / cases from a brief or job.

### Pre-screening & execution cockpit

- `PreScreeningAgent` estimates opportunity suitability, rough effort, blockers, required inputs and recommended workflow before Dmytro commits.
- `ExecutionCockpitAgent` creates `EXECUTION_FLOW.md`, `APPROVAL_CHECKPOINTS.md`, `SYSTEM_DIALOG_GUIDE.md`, `TESTING_READINESS_CHECKLIST.md` and `PROJECT_INTAKE_CHECKLIST.md`.
- New mode: `prescreen` for fast suitability checks before spending Connects or accepting work.

### Market calibration

- `PlatformRouterAgent` detects Upwork / writing / evaluator / direct B2B / microservice-style inputs.
- `CapabilityRouterAgent` classifies work beyond Playwright: strong execution, supported/adjacent, advisory-only, skip/risky.
- `OpportunityFilterAgent` outputs practical decisions: `strong_apply`, `apply_selectively`, `advisory_only`, `skip_low_value`, `skip_risky`, `skip_not_core`.
- `ScreeningAnswersAgent` extracts screening questions, mandatory keywords and AI/prompt-injection traps.
- `EvidencePackAgent` lists proof needed before applying and forbids invented evidence.
- `CommercialStrategyAgent` reframes pricing as negotiation/milestone strategy.
- `TechnicalWritingAgent` supports SaaS/QA documentation opportunities as an adjacent branch.

### Human-readable reporting

Every normal run should create a control pack:

- `READ_ME_FIRST.md`
- `PRESCREENING_REPORT.md`
- `EXECUTION_FLOW.md`
- `APPROVAL_CHECKPOINTS.md`
- `SYSTEM_DIALOG_GUIDE.md`
- `TESTING_READINESS_CHECKLIST.md`
- `PROJECT_INTAKE_CHECKLIST.md`
- `DECISION.md`
- `NEXT_ACTIONS.md`
- `SUMMARY.md`
- `fit_decision.md`
- `commercial_strategy.md`
- `screening_answers.md`
- `evidence_needed.md`
- `HUMAN_REVIEW_REQUIRED.md`
- `QUALITY_GATE_REPORT.md`
- `SELF_HEALTH_REPORT.md`
- `SYSTEM_REPAIR_PLAN.md`
- `TEST_STRATEGY.md`
- `TEST_PLAN.md`
- `TEST_CASES.md`

### Batch filtering

```bash
python main.py batch-filter --input real_jobs/
```

This creates:

```text
outputs/batch_opportunity_report.md
```

Use it to shortlist a folder of copied Upwork/direct opportunities before spending Connects or time.

### Role-based model routing

The Factory does not use one model for everything. Configure role routing via `MODEL_PROFILE` or manual `*_MODEL` overrides.

Recommended premium hybrid profile:

```env
LLM_MODE=real
MODEL_PROFILE=premium_hybrid
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

This routes work as follows:

| Role | Model | Purpose |
|---|---|---|
| `architect` | `gpt-5.5` | prescreening, capability routing, strategy |
| `coding` | `anthropic/claude-sonnet-4-6` | code/scaffold/test implementation notes |
| `review` | `anthropic/claude-opus-4-7` | deep review, quality gate, self-health |
| `fast` | `anthropic/claude-sonnet-4-6` | proposals, summaries, delivery notes |
| `vision` | `gpt-5.5` | future screenshot / visual review |
| `fallback` | `gpt-5.4-mini` | backup |

See `docs/MODEL_ROUTING_PROFILES.md`.

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate    # Windows
# source .venv/bin/activate  # macOS/Linux
pip install -r requirements.txt
copy .env.example .env
python -m pytest -q
```

## Running tests

Unit and smoke tests always run in **mock mode** — no real API keys are required and no paid LLM calls are made.
`tests/conftest.py` sets `LLM_MODE=mock` and `MODEL_PROFILE=mock` before any test imports app config, so `.env` values are ignored.

```bash
# Default: always uses mock mode regardless of .env
python -m pytest -q

# Explicit (same result, useful as a reminder in CI):
LLM_MODE=mock MODEL_PROFILE=mock python -m pytest -q
```

To run real-LLM smoke tests you must explicitly set both variables in your shell:

```bash
LLM_MODE=real MODEL_PROFILE=premium_hybrid python -m pytest -q
```

For full real-runtime validation use the CLI directly:

```bash
python main.py system-health
python main.py prescreen --input sample_inputs/upwork_job.txt --source-platform upwork --require-real-llm
```

**LiteLLM botocore warnings** (`No module named 'botocore'`, etc.) are harmless — they only affect AWS Bedrock/SageMaker providers, which are not used here. They are suppressed automatically during pytest.

## Main commands

```bash
python main.py prescreen --input sample_inputs/upwork_job_saas_multitenant_billing.txt
python main.py filter --input sample_inputs/upwork_job_saas_multitenant_billing.txt
python main.py test-design --input sample_inputs/client_brief.txt
python main.py batch-filter --input sample_inputs/
python main.py upwork --input sample_inputs/upwork_job_greenhouse_ai_native_qa.txt
python main.py scaffold --input sample_inputs/client_brief.txt
python main.py full --input sample_inputs/client_brief.txt
python main.py review --input sample_inputs/test_to_review.ts
python main.py capabilities
python main.py agents
python main.py ask --project-id <project_id> --question "Why did you recommend this action?"
```

## Execution modes

```bash
python main.py full --input sample_inputs/client_brief.txt --step
python main.py full --input sample_inputs/client_brief.txt --dry-run
python main.py full --input sample_inputs/client_brief.txt --only proposal_writer
python main.py full --input sample_inputs/client_brief.txt --from-step proposal_writer
```

## Real client safety

For real proposals:

```bash
python main.py upwork --input real_jobs/job_001.txt --require-real-llm
```

If `LLM_MODE=mock`, this fails intentionally unless `--allow-mock` is passed. Mock mode is for structure testing only.

## Human approval rule

Every output is a draft. Dmytro must check: claims, evidence, screening answers, mandatory keywords, price/rate, scope, credentials, payment/security safety and final wording before sending.

## Still out of scope

No aggressive platform scraping, no auto-submission, no GitHub auto-push, no autonomous inter-agent dialogue, no unsafe self-healing, no self-healing test promises, no LangGraph/RAG/UI until real usage proves the need.

## v5.0.8 model routing additions

- `system-health` checks local readiness before real testing: Python packages, LLM config, API key presence, output/memory folders and Node/npm/npx availability.
- `--project-id` lets you rerun `--only` or `--from-step` against a saved project more explicitly.
- `--source-platform` lets you force a source hint when copied text does not contain enough platform metadata, e.g. `--source-platform upwork`.
- Release archive is cleaned of generated `__pycache__`, `outputs/` and previous `memory/projects/` run artifacts.

```bash
python main.py system-health
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --allow-mock
python main.py full --input real_jobs/job_001.txt --project-id <saved_project_id> --only proposal_writer --allow-mock
```

## v5.0.8 code & documentation sync

v5.0.8 aligns the codebase and docs around the current operating model:

1. pre-screen first;
2. open human-readable reports before JSON;
3. approve key steps before client-facing or real-site actions;
4. use capability/platform routing to decide apply / selective apply / advisory / skip;
5. use extension packs and self-health reports to identify missing project-specific support;
6. prepare real testing only after `system-health` and `TESTING_READINESS_CHECKLIST.md` are clean.

New docs:

- `docs/OPPORTUNITY_PRESCREENING_APPROVAL_FLOW.md`
- `docs/REAL_TESTING_PREPARATION.md`
- `docs/V507_CODE_DOC_SYNC_NOTES.md`

- `docs/MODEL_ROUTING_PROFILES.md`

## v5.0.9 validation hardening

Controlled validation run against 6 demo-brief scenarios (2026-05-24). Patches applied: `api_testing` routing (P1), mobile risk flag (P2), SaaS billing check (P3/P3b), `test-design` mode guards (P4). Test suite: 60/60 (was 49).

- `docs/RUNBOOK.md` — **daily practical runbook** (what to run, what to open, troubleshooting)
- `docs/AI_QA_Factory_Concept_and_Implementation_Plan_v7_validation_hardened.md` — current canonical architecture and operating reference
- `docs/VALIDATION_WEBSITE_TESTING_REPORT.md` — full validation report, per-scenario results, patch list
- `docs/V508_MODEL_ROUTING_NOTES.md` — model routing change notes
- `docs/REAL_TESTING_PREPARATION.md` — checklist before real-site/staging testing
- `docs/VSCODE_USAGE.md` — VS Code setup and archive/sharing hygiene (what to exclude from zips)

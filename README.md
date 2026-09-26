# AI QA Factory

[![CI](https://github.com/dmytropogribnyy/ai-qa-factory/actions/workflows/ci.yml/badge.svg)](https://github.com/dmytropogribnyy/ai-qa-factory/actions/workflows/ci.yml)

> **AI-assisted QA · LLM output validation · Human-reviewed workflows**
>
> **AI drafts. Senior QA decides.**

AI QA Factory is a **local-first Python workbench** for AI-assisted quality engineering. It turns project briefs into reviewable QA plans and Playwright + TypeScript starter projects, and inspects approved public websites to produce findings with supporting evidence.

The engineering focus is on making AI-assisted work **reviewable, testable, and traceable**: validating generated outputs, handling model failures, persisting workflow state, and requiring human approval before consequential actions.

**Status:** an independent engineering project in active development, with implemented local workflows and a regression suite. Integrations have separate readiness requirements; passing deterministic tests does not establish live-provider acceptance or production readiness. See the [capability matrix](docs/CAPABILITY_MATRIX.md), [release notes](docs/releases/), and [open issues](https://github.com/dmytropogribnyy/ai-qa-factory/issues) for implementation boundaries and ongoing work.

**Stack:** Python · LiteLLM · OpenAI / Anthropic integrations · Playwright / Chromium · TypeScript scaffolds · SQLite · MCP · pytest · GitHub Actions.

## AI evaluation and reliability

The project applies evaluation to its own generated artifacts and workflow decisions. It combines rule-based checks, deterministic scenario fixtures, and human review.

| Engineering area | Implementation to explore |
|---|---|
| **Generated-output validation** | [Quality gate](core/quality_gate.py): checks for unsupported claims, invented-evidence language, hardcoded credentials, brittle selectors, and missing review notes |
| **Scenario evaluation** | [Fixture evaluator](core/scenario_batch_evaluator.py): safety expectations, category rules, and structural checks over local scenarios, without executing external targets |
| **Model routing and fallback** | [LLM router](core/llm_router.py) and [routing tests](tests/test_v509_llm_router.py): task-specific model selection, fallback behavior, and recorded usage metadata |
| **Bounded collaboration** | [Budget controls](core/collaboration/budget.py): call limits, bounded retries, response caching, and spend limits when pricing is known |
| **Human oversight and traceability** | [Execution lifecycle](core/orchestration/work_execution.py) and [approval model](docs/APPROVAL_MODEL.md): persisted approval decisions, validation, and evidence registration |

These checks identify specific failure patterns; they do not establish general model accuracy, factual correctness, or legal compliance. Generated material and verified execution evidence remain distinct throughout the workflow.

## Product surfaces

| Surface | What it does | Honest boundary |
|---|---|---|
| **Guided client-work lifecycle** | Classifies briefs, builds a project blueprint, produces QA strategy/test design, generates Playwright + TypeScript starter projects, and persists approval, validation, review, repair, and delivery-preparation states | Does not autonomously implement or deliver client work without senior review |
| **Scout operator dashboard** | Creates and controls prospect-QA campaigns, tracks progress/history, reviews findings, evidence, coverage, and guarded lifecycle actions | Local loopback application, not a hosted multi-user SaaS |
| **Static public-site inspection** | Runs bounded HTTP/HTML analysis over explicitly approved public URLs and persists verified findings and reports | Read-only; unsafe redirects, prohibited targets, and access challenges fail closed |
| **Deep Capture** | Can add real Chromium screenshots, axe observations, timing, console/network evidence, and a redacted browser-event trace | Conditional on Playwright + Chromium; automatic execution remains read-only navigation |
| **Evidence delivery** | Builds an exact-target client package with offline summary, findings, coverage, available visuals, sanitized technical records, and integrity hashes | Completed analysis only; screenshots and video require human review |
| **Observer MCP** | Exposes read-only project, campaign, run, target, evidence, and diagnostic views | Read-only; process identity makes stale deployments visible |

The canonical runtime truth is maintained in the [Current Runtime Capability Matrix](docs/CAPABILITY_MATRIX.md). It distinguishes **runtime**, **conditional**, **generator/planning**, and **not runtime** capabilities.

## Operating model

### Client work

The client workflow classifies a brief and its risks, builds a blueprint, drafts a QA strategy and test design, and generates a starter framework. Approval, validation, review, and repair precede delivery preparation and senior QA review.

Typical outputs include:

- project blueprint and risk classification;
- strategic QA plan and tactical test design;
- Playwright + TypeScript starter framework;
- API-test structure and CI recommendations;
- review findings and repair guidance;
- internal summary and client-facing delivery material.

Generated plans and scaffolds are **not proof that a client system was exercised**. Target-specific selectors, flows, credentials, and environment behavior still require evidence and validation.

### Prospect QA Scout

Scout checks approved URLs against safety and suppression rules, performs bounded static inspection and optional Deep Capture, then verifies and prioritizes findings. An evidence package links the results to the exact run for operator review.

The local dashboard supports campaign progress, pause/resume/stop controls, archived history, needs-attention handoffs, target detail, evidence download, and guarded cleanup workflows.

Scout may surface source-attributed public contact addresses and prepare a factual copy-only draft for a completed target with an actionable finding. **Nothing is sent automatically.**

A separate communication workflow supports individually reviewed and approved messages. External sending is disabled by default and requires provider setup and explicit controls; generating a QA finding never authorizes contact.

## Evidence and diagnostics

A completed target can include:

- separate landing and verification screenshots when capture succeeds;
- verified findings and coverage data;
- accessibility, timing, console, and network observations when available;
- a bounded redacted browser-event trace;
- an optional short reproduction video for a qualified read-only flow-entry failure;
- an offline HTML summary;
- sanitized structured records;
- SHA-256 integrity manifests;
- linkage to the exact campaign, run, and target.

Evidence is path-confined, bounded, redacted, and secret-scanned where applicable. Missing capture is reported as missing and is never replaced with synthetic evidence.

## Safety contract

AI QA Factory is designed to fail closed.

- Public Scout analysis is read-only.
- No purchases, bookings, account creation, form submissions, or uncontrolled business interactions.
- No CAPTCHA or access-control bypass. A visible Chromium handoff can wait for an operator to complete a legitimate access check, then continue, defer, or skip.
- No automatic or bulk outreach.
- External email requires separate credentials, exact-recipient confirmation, reviewed content, explicit approval, and enabled controls.
- Production, authentication, payment, security-sensitive, and external-environment work requires the appropriate approval and environment boundary.
- Parallel Scout site execution is not implemented; concurrency remains `1`.
- Mobile/native execution, formal compliance certification, deep load testing, and formal penetration testing are not current runtime capabilities.

See [Approval Model](docs/APPROVAL_MODEL.md) and [Safety Rules](docs/SAFETY_RULES.md).

## Quick start

### Windows operator setup

```powershell
scripts\setup-local.ps1
scripts\doctor-local.ps1
scripts\start-local.ps1
```

The dashboard opens locally at `http://127.0.0.1:8765`.

Stop it with:

```powershell
scripts\stop-local.ps1
```

### Portable Python setup

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
python main.py system-health
python main.py capabilities
python main.py dashboard
```

The deterministic test suite runs without API keys. Real model providers and conditional integrations require separate local configuration.

## Selected commands

```bash
# Runtime truth and readiness
python main.py system-health
python main.py capabilities
python main.py agents

# Opportunity and QA planning
python main.py prescreen --input brief.txt
python main.py test-design --input brief.txt --require-real-llm
python main.py plan --input brief.txt --require-real-llm

# Framework and delivery preparation
python main.py scaffold --input brief.txt --require-real-llm
python main.py audit --input brief.txt --require-real-llm
python main.py full --input brief.txt --step
python main.py review --input tests/smoke.spec.ts
python main.py delivery --input brief.txt --require-real-llm
```

The complete implemented/planned command reference lives in [docs/COMMANDS.md](docs/COMMANDS.md).

The opportunity workflow is **pre-screen first**: assess suitability and risk before planning or execution.

## Optional real-model configuration

Copy `.env.example` to a local `.env` and supply only the providers you intend to use:

```env
LLM_MODE=real
MODEL_PROFILE=premium_hybrid
OPENAI_API_KEY=your-openai-key-here
ANTHROPIC_API_KEY=your-anthropic-key-here
```

Never commit credentials, OAuth tokens, authenticated browser state, client data, or generated evidence containing sensitive information.

## Validation

```bash
python -m ruff check .
python -m pytest tests/ -q
python tools/docs_audit.py --no-write
python tools/agent_readiness_audit.py
```

Exact per-release totals belong in versioned [release notes](docs/releases/) rather than this README, so the public overview does not drift as the suite grows.

## Documentation

| Document | Purpose |
|---|---|
| [Operator Quickstart](docs/QUICKSTART_OPERATOR.md) | Fast local setup and daily workflow |
| [Client Work Operator Guide](docs/CLIENT_WORK_OPERATOR_GUIDE.md) | Senior-led brief-to-delivery workflow |
| [Scout Operator Guide](docs/SCOUT_OPERATOR_GUIDE.md) | **Start here for a manual seed scan** (`/scout`) — you already know the websites |
| [Scout Runbook — discovery intake](docs/RUNBOOK_SCOUT.md) | **Start here for prospect discovery** (`/scout/new`) — let Scout find the websites |
| [Current Runtime Capability Matrix](docs/CAPABILITY_MATRIX.md) | Executable, conditional, planning-only, and unavailable capabilities |
| [Commands](docs/COMMANDS.md) | CLI reference |
| [Approval Model](docs/APPROVAL_MODEL.md) | Approval and risk levels |
| [Safety Rules](docs/SAFETY_RULES.md) | Non-negotiable execution boundaries |
| [Scout Runbook — operations](docs/RUNBOOK_SCOUT.md#5-control-or-clean-up-runs) | Continuation, archive, evidence, and cleanup procedures |
| [Prospect QA Radar specification](docs/architecture/PROSPECT_QA_RADAR_SPEC.md) | Scout architecture and product contracts |
| [Release notes](docs/releases/) | Versioned implementation and verification history |

## Scope statement

AI QA Factory demonstrates a practical quality-engineering operating model: structured intake, risk-aware planning, controlled automation, evidence discipline, and senior review. It is built to accelerate professional QA work without confusing generated material with verified execution or allowing automation to cross safety boundaries silently.

Developed by [Dmytro Pogribnyy](https://dmytropogribnyy.github.io/) — Senior SDET / QA Automation Engineer, with a focus on AI/LLM quality engineering and a PhD in Business Law.

<!-- Compatibility anchors retained for regression tests: v5.0.8 model routing profiles; premium_hybrid -->

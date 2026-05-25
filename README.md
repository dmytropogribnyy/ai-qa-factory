# Guided QA Automation Workbench

> **AI drafts. Senior QA decides.**

A local, AI-assisted QA automation platform for real client projects.  
Built for Dmytro Pogribnyy — SDET / QA Automation Lead.

---

## What this is

**AI QA Factory is evolving into a Guided QA Automation Workbench** for real client QA automation work.

Conceptually similar in flow to Lovable, Make, or n8n — but specialized for QA automation consulting:

```
Understand → Classify Inputs → Build Project Blueprint
    → Plan Strategically → Plan Tactically → Select Tools
    → Ask Approval → Execute Safely → Collect Evidence → Report Clearly
```

The workbench accepts a brief, client task, or job post; classifies the context; builds a QA strategy and test automation plan; generates a Playwright TypeScript scaffold; and stops — waiting for your review before anything touches a real environment or goes to a client.

**It is not a full autopilot.** It uses human approval gates at every risky step.

---

## What it supports

**Inputs (current and planned):**
- Text briefs and job posts
- Task URLs (Jira, Linear, Notion tickets)
- Target application URLs (classified, not fetched automatically)
- Screenshots (via vision model — planned)
- Uploaded archives and repos (planned)
- API documentation (OpenAPI, Postman — planned)

**Project types:**
- Web SaaS (multi-tenant, auth, billing)
- E-commerce (checkout, cart, payment flows)
- API backends (REST, GraphQL)
- AI-generated applications
- Admin panels
- Auth-heavy applications
- Mixed UI + API
- Unknown / to be classified

**Outputs:**
- Project Blueprint (source of truth)
- Strategic QA plan
- Tactical test plan and test cases
- Playwright TypeScript scaffold (full npm project)
- API test suite
- Evidence pack
- Internal summary report
- Client-facing delivery report (gated behind explicit approval)

---

## Safety model

| Action | Behaviour |
|---|---|
| Analyze text input | Automatic |
| Generate strategy / scaffold | Automatic |
| Run local validation (compile, lint, dry-run) | Automatic |
| Run tests against staging URL | **Requires approval** |
| Run tests against production | **Requires explicit read-only approval** |
| Test payment / auth / security flows | **Requires approval + sandbox confirmation** |
| Send client-facing report | **Requires final approval** |

External and staging execution is blocked by default. `--approve` flag unlocks it per run.  
See [`docs/APPROVAL_MODEL.md`](docs/APPROVAL_MODEL.md) and [`docs/SAFETY_RULES.md`](docs/SAFETY_RULES.md).

---

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
copy .env.example .env
python -m pytest -q             # 577 tests, mock mode, no API keys needed
python main.py system-health
python tools/docs_audit.py      # verify documentation is current
python tools/classify_inputs.py --input "Need Playwright tests for SaaS dashboard" --no-write
```

---

## Current commands

```bash
# System
python main.py system-health
python main.py capabilities
python main.py agents

# Opportunity evaluation
python main.py prescreen --input brief.txt
python main.py filter   --input brief.txt
python main.py upwork   --input brief.txt --source-platform upwork --require-real-llm
python main.py batch-filter --input real_jobs/

# QA delivery
python main.py test-design --input brief.txt --require-real-llm
python main.py scaffold    --input brief.txt --require-real-llm
python main.py plan        --input brief.txt --require-real-llm
python main.py audit       --input brief.txt --require-real-llm
python main.py full        --input brief.txt --require-real-llm
python main.py review      --input tests/smoke.spec.ts
python main.py delivery    --input brief.txt --require-real-llm

# Execution control
python main.py full --input brief.txt --step
python main.py full --input brief.txt --dry-run
python main.py full --input brief.txt --only proposal_writer
python main.py full --input brief.txt --from-step proposal_writer
python main.py run-tests --project-path outputs/<id>/framework --kind playwright
python main.py ask --project-id <id> --question "Why apply_selectively?"
```

Full command reference with planned future commands: [`docs/COMMANDS.md`](docs/COMMANDS.md)

---

## Configuration

```env
LLM_MODE=real
MODEL_PROFILE=premium_hybrid
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

Role routing in `premium_hybrid`:

| Role | Model | Used for |
|---|---|---|
| `architect` | `gpt-5.5` | Strategy, capability routing, prescreening |
| `coding` | `claude-sonnet-4-6` | Scaffold, test implementation |
| `review` | `claude-opus-4-7` | Quality gate, self-health, deep review |
| `fast` | `claude-sonnet-4-6` | Proposals, summaries, delivery notes |
| `vision` | `gpt-5.5` | Screenshot / visual input (planned) |
| `fallback` | `gpt-5.4-mini` | Backup |

---

## Tooling decisions

- **Orchestrator:** Registry-based (current default). LangGraph is optional future backend — not mandatory now.
- **Automation framework:** Playwright + TypeScript is the primary target.
- **Reporting:** Markdown + JSONL locally. Allure is an optional future adapter.
- **Observability:** Local JSONL logs. LangSmith is optional — not mandatory now.
- **Playwright MCP:** Not a mandatory runtime dependency.
- **Playwright codegen / trace viewer:** Useful helpers, not managed by the workbench.

See [`docs/TOOLING_DECISIONS.md`](docs/TOOLING_DECISIONS.md) for rationale.

---

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q   # always mock mode — no API keys consumed
```

Expected: **577 passed** (69 original + 81 schema foundations + 62 auth/credential/mobile + 20 integration + 26 documentation governance + 73 Phase 2A classification + 82 Phase 2B blueprint + 58 Phase 2B-AGENT readiness + 106 Phase 2C strategy)

---

## Docs

| Document | Purpose |
|---|---|
| [`docs/VISION.md`](docs/VISION.md) | Product vision and roadmap |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Daily operating guide |
| [`docs/COMMANDS.md`](docs/COMMANDS.md) | Full command reference (implemented + planned) |
| [`docs/APPROVAL_MODEL.md`](docs/APPROVAL_MODEL.md) | Risk levels, approval gates, what runs automatically |
| [`docs/SAFETY_RULES.md`](docs/SAFETY_RULES.md) | Hard rules — what never runs automatically |
| [`docs/TOOLING_DECISIONS.md`](docs/TOOLING_DECISIONS.md) | Orchestrator, LangGraph, Playwright, Allure, LangSmith decisions |
| [`docs/SCHEMA_FOUNDATION.md`](docs/SCHEMA_FOUNDATION.md) | `core/schemas/` layer — 35 domain models |
| [`docs/PROJECT_TYPES.md`](docs/PROJECT_TYPES.md) | Supported project types with risks and test focus |
| [`docs/DOCUMENTATION_GOVERNANCE.md`](docs/DOCUMENTATION_GOVERNANCE.md) | How to keep docs accurate as the project evolves |
| [`docs/DOCS_MANIFEST.md`](docs/DOCS_MANIFEST.md) | Registry of all documentation files and their status |

---

## Changelog highlights

<!-- sync-anchor: v5.0.8 model routing profiles — kept for internal test compatibility -->
### v5.1.0 — Guided QA Automation Workbench

- Product direction: evolving from opportunity router to full QA automation workbench
- `core/version.py`: `APP_VERSION`, `STATE_SCHEMA_VERSION`, `RELEASE_LABEL`
- New docs: VISION, COMMANDS, APPROVAL_MODEL, TOOLING_DECISIONS, SAFETY_RULES, PROJECT_TYPES
- Phase 1B: 35 schema modules in `core/schemas/` — domain models, auth/credential, mobile, integration, documentation governance
- Phase 1B-DOCS: `tools/docs_audit.py`, `DOCUMENTATION_GOVERNANCE.md`, `DOCS_MANIFEST.md`
- Phase 2A: `core/input_context_resolver.py`, `core/work_request_classifier.py` — input classification, secret redaction
- Phase 2B: `core/project_blueprint_builder.py` — project blueprint from classified inputs (8 project types)
- Phase 2B-AGENT: `docs/AGENT_CONTRACT.md`, `docs/PHASE_CONTRACTS.md`, `docs/ARTIFACT_CONTRACTS.md`, `docs/AGENT_HANDOFF_TEMPLATE.md`, `tools/agent_readiness_audit.py`
- Phase 2C: `core/qa_strategy_planner.py`, `core/schemas/qa_strategy.py`, `tools/build_strategy.py` — QA strategy planner, 8 artifact types in `02_strategy/`
- Pre-screen first: opportunity evaluation workflows fully supported and preserved
- 577 tests passing

### v5.0.9 — Validation hardened

Patches: api_testing routing (P1), mobile risk flag (P2), SaaS billing check (P3), test-design mode (P4).  
Tests: 69/69.

### v5.0.8 model routing additions

Role-based model routing profiles: architect / coding / review / fast / vision / fallback.  
`system-health`, `--project-id`, `--source-platform` added.

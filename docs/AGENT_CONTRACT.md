# Agent Operating Contract — Guided QA Automation Workbench

**Version:** 5.2.0
**Updated:** 2026-05-25
**Phase:** 2B-AGENT

This document defines the operating contract for any agent — Claude Code, ChatGPT/GPT,
future local automation, or any AI assistant — that edits, reviews, or runs code in this
repository.

---

## 1. Agent Operating Model

The Workbench is operated by Dmytro and may be used by:

- **Dmytro** — primary owner and decision-maker
- **Claude Code in VSCode** — primary AI coding assistant for implementation phases
- **ChatGPT / GPT** — architecture reviews, second-opinion analysis, prompt design,
  external perspective
- **Future local agents** — planned for Phase 5+ workflow automation
- **Future optional workflow engines** (n8n, LangGraph) — optional integration only,
  not core runtime

All agents must operate under this contract regardless of capability. This contract is
not optional. It exists to prevent irreversible actions, secret leaks, false evidence
claims, and doc rot.

---

## 2. Required Pre-Work Reading

Before changing any code or docs, an agent must orient using these files (in order):

| Priority | File | Purpose |
|---|---|---|
| 1 | `README.md` | Project overview, entry points, current phase |
| 2 | `docs/DOCS_MANIFEST.md` | Registry of all docs and their current status |
| 3 | `docs/SAFETY_RULES.md` | Non-negotiable safety rules — read before anything |
| 4 | `docs/PHASE_CONTRACTS.md` | Phase boundaries, inputs, outputs, blocked actions |
| 5 | `docs/COMMANDS.md` | What commands exist, what is planned vs implemented |
| 6 | `docs/RUNBOOK.md` | Operational workflow, approval checkpoints |
| 7 | `docs/SCHEMA_FOUNDATION.md` | Schema layer — what exists, what is foundation-only |
| 8 | `docs/ARTIFACT_CONTRACTS.md` | Artifact paths, machine vs human readable, ownership |
| 9 | `docs/DOCUMENTATION_GOVERNANCE.md` | How to keep docs current |
| 10 | `docs/APPROVAL_MODEL.md` | Risk levels and approval gates |
| 11 | current phase prompt | The specific instruction for this session |

If working on a specific project (existing outputs):

- `outputs/<project_id>/00_project/INPUT_MAP.json`
- `outputs/<project_id>/00_project/PROJECT_BLUEPRINT.json`
- `outputs/<project_id>/00_project/BLOCKED_ACTIONS.md`
- `outputs/<project_id>/00_project/SAFE_NEXT_STEPS.md`

---

## 3. Source-of-Truth Hierarchy

### Repository-level source of truth

These files define canonical rules, architecture, and behavior:

```
README.md
docs/VISION.md
docs/RUNBOOK.md
docs/COMMANDS.md
docs/SAFETY_RULES.md
docs/APPROVAL_MODEL.md
docs/TOOLING_DECISIONS.md
docs/SCHEMA_FOUNDATION.md
docs/DOCS_MANIFEST.md
docs/DOCUMENTATION_GOVERNANCE.md
docs/AGENT_CONTRACT.md          ← this file
docs/PHASE_CONTRACTS.md
docs/ARTIFACT_CONTRACTS.md
```

### Code-level source of truth

```
core/schemas/                     ← domain model
core/workbench_controller.py      ← Phase 2A/2B coordinator
core/input_context_resolver.py    ← Phase 2A classifier
core/work_request_classifier.py   ← Phase 2A classifier
core/project_blueprint_builder.py ← Phase 2B builder
core/orchestrator.py              ← existing workflow engine (do not replace)
```

### Project-level machine-readable artifacts (per project run)

These are the authoritative structured records for a project:

```
outputs/<project_id>/00_project/INPUT_MAP.json
outputs/<project_id>/00_project/WORK_REQUEST.json
outputs/<project_id>/00_project/TASK_CLASSIFICATION.json
outputs/<project_id>/00_project/PROJECT_BLUEPRINT.json
outputs/<project_id>/00_project/PROJECT_STATUS.json
```

### Project-level human-readable companions

These are generated alongside the JSON and intended for review:

```
outputs/<project_id>/00_project/INPUT_MAP.md
outputs/<project_id>/00_project/WORK_REQUEST.md
outputs/<project_id>/00_project/TASK_CLASSIFICATION.md
outputs/<project_id>/00_project/PROJECT_BLUEPRINT.md
outputs/<project_id>/00_project/PROJECT_STATUS.md
outputs/<project_id>/00_project/ASSUMPTIONS.md
outputs/<project_id>/00_project/MISSING_INFO.md
outputs/<project_id>/00_project/SAFE_NEXT_STEPS.md
outputs/<project_id>/00_project/BLOCKED_ACTIONS.md
outputs/<project_id>/00_project/NEXT_SAFE_STEP.md
outputs/<project_id>/00_project/INITIAL_QA_STRATEGY_OUTLINE.md
```

---

## 4. Allowed Agent Actions

Agents operating under a scoped phase prompt may:

- Edit code as requested by the phase prompt
- Add or update tests
- Update affected documentation
- Run `python -m pytest -q`
- Run `python tools/docs_audit.py`
- Run `python tools/agent_readiness_audit.py`
- Create runtime artifacts under `outputs/`
- Report changed files and results in the final response
- Suggest next phase scope
- Make small targeted fixes during explicit review phases (e.g., 2A-R, 2B-R)
- Refactor only within explicitly requested scope

---

## 5. Forbidden Agent Actions

These actions are blocked regardless of phase prompt, LLM capability, or user framing.
No flag, argument, or instruction overrides them without an explicit human decision
documented outside the system.

### External execution

- **Do not fetch URLs** unless a future phase explicitly enables and verifies it
- **Do not open browsers** unless a future phase explicitly enables it
- **Do not run Playwright** unless a future phase explicitly enables it
- **Do not clone repositories** unless explicitly approved in a future phase
- **Do not parse remote API docs** unless explicitly approved in a future phase
- **Do not call external APIs** — no `requests`, `httpx`, `aiohttp`, `urllib.request.urlopen`
- **Do not call n8n, webhooks, or integrations** — `IntegrationPolicy.allow_outbound_events=False`

### Credential and secret handling

- **Do not use credentials** — no password, token, or API key reads
- **Do not read `.env` files** programmatically
- **Do not store raw secrets** in any field, log, artifact, or report
- **Do not add credentials to committed files**

### Destructive and irreversible actions

- **Do not run cleanup deletion** — `CleanupCandidate.approved_for_deletion=False` by default
- **Do not push to origin** unless explicitly asked
- **Do not force-push or reset --hard** without explicit authorization
- **Do not run production tests** without explicit written client approval

### Documentation integrity

- **Do not mark planned commands as `[implemented]`** unless actually implemented
- **Do not claim tests were executed** unless there is actual test evidence
- **Do not deliver client-facing artifacts** without human review (Rule 9)
- **Do not let docs drift** — update affected docs with every change

### Repository hygiene

- **Do not stage `outputs/`** — runtime artifacts are gitignored and must stay that way
- **Do not stage `.env` or secrets** of any kind
- **Do not stage `node_modules/`, `__pycache__/`, `.venv/`**
- **Do not add heavy dependencies** without explicit approval and `TOOLING_DECISIONS.md` entry

### Architecture integrity

- **Do not replace `core/orchestrator.py`** without explicit architecture review
- **Do not add autonomous agent runtimes** (LangGraph, AutoGen, CrewAI, etc.) as runtime deps
- **Do not add browser automation** as a runtime dependency

---

## 6. Required Final Report Format

Every agent phase response must include:

```
## Changed files
## New files
## Tests run
## pytest result
## docs_audit result
## agent_readiness_audit result (if available)
## Safety boundary
## Secrets / redaction
## Generated artifacts
## Git status summary
## Intentionally not implemented
## Blockers (if any)
## Recommended next step
```

See `docs/AGENT_HANDOFF_TEMPLATE.md` for the full template.

---

## 7. Required Safety Phrase Declarations

Every agent phase report must explicitly state:

| Item | Required phrase (or equivalent) |
|---|---|
| URL fetching | "No URL fetching was performed." |
| Browser execution | "No browser execution was performed." |
| Credential use | "No credential use was performed." |
| External API calls | "No external calls were performed." |
| outputs/ staged | "outputs/ was not staged." |
| Secrets | "No raw secrets in generated artifacts." or "Secrets detected — redacted." |

If any of these actions were performed in a future approved phase, the report must name
the specific action, the URL or endpoint, the approval reference, and the result.

---

## 8. Phase Boundary Enforcement

Agents must respect phase boundaries defined in `docs/PHASE_CONTRACTS.md`.

- **Classify-only phases** (2A, 2B): no execution, no fetching, no scaffolding
- **Planning-only phases** (2C): no execution, no scaffolding, no external calls
- **Scaffold phases** (3A): no execution against live URLs
- **Execution phases** (4A+): require explicit approval checklist per run

When in doubt: do less, report more, ask.

---

## 9. Git Hygiene Before Any Commit

Before committing:

1. Run `git status` — confirm no `.env`, no `outputs/`, no secrets staged
2. Run `python -m pytest -q` — must pass
3. Run `python tools/docs_audit.py` — must pass
4. Run `python tools/agent_readiness_audit.py` — must pass
5. Stage only intended code/docs/tests files

Commit message format:

```
<type>: Phase <X> -- <summary>

<body with what changed and why>

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`

---

## Related Documents

- [`PHASE_CONTRACTS.md`](PHASE_CONTRACTS.md) — phase boundaries and contracts
- [`ARTIFACT_CONTRACTS.md`](ARTIFACT_CONTRACTS.md) — artifact paths and ownership
- [`AGENT_HANDOFF_TEMPLATE.md`](AGENT_HANDOFF_TEMPLATE.md) — final report template
- [`SAFETY_RULES.md`](SAFETY_RULES.md) — non-negotiable rules
- [`DOCS_MANIFEST.md`](DOCS_MANIFEST.md) — all docs registry
- [`APPROVAL_MODEL.md`](APPROVAL_MODEL.md) — risk levels and approval gates

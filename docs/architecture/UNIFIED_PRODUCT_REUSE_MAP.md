# Unified Operator Product v3.0.0 — Repository Reuse Map

**Milestone 1 artifact.** Before adding code, every required v3.0.0 feature is classified against the
**existing** repository so we EXTEND proven components through adapters rather than creating a second
project registry, capability registry, evidence store, work-state implementation, Scout company
model, communication database, or source of truth.

Classifications: **REUSE_AS_IS**, **EXTEND**, **ADAPT**, **REPLACE_ONLY_IF_BROKEN**, **NOT_REQUIRED**.

## Existing components (source of truth — do not duplicate)

### Client Work / AI QA Factory orchestration (`core/orchestration/`, `core/schemas/`)
| Component | Role |
| --- | --- |
| `universal_intake.py` (`UniversalWorkIntake`) + `core.work_request_classifier` | Intake: raw brief → `WorkRequest` (secret-safe `raw_brief`) |
| `requirement_extractor.py`, `missing_information_analyzer.py` | Requirement extraction + missing-info/questions |
| `capability_registry.py` (`CapabilityRegistry`), `capability_planner.py` | Capability catalogue + per-task capability plan |
| `toolchain_composer.py` (`ToolchainComposer`), `profile_selector.py` | Toolchain/tool selection + work-profile selection |
| `work_workflow.py` (`WorkPlanningWorkflow`) | Intake → plan (deterministic, planning-only) |
| `work_state_manager.py` (`WorkStateManager`) + `schemas/work_run_state.py` | Lifecycle state machine (`ALLOWED_TRANSITIONS`, `TERMINAL_STATES`) |
| `mcp_snapshot.py`, `providers.py`, `content_safety.py` | MCP snapshot, LLM providers, artifact-safe writing |
| Schemas: `work_request`, `work_packet`, `work_run_state`, `work_delivery`, `capability`, `capability_plan`, `capability_gap`, `toolchain_plan`, `tool_selection`, `toolchain_validation`, `client_delivery`, `delivery_plan`, `delivery_preview`, `intake`, `project_blueprint`, `project_status`, `framework_scaffold`, `auth_capability` | Typed domain models |
| `main.py` modes: `work`, `prescreen`, `plan`, `test-design`, `scaffold`, `audit`, `review`, `delivery`, `full`, `upwork`, `batch-filter`, `mcp-guide` | Existing client-work CLI surface |

Existing lifecycle (reused for the mission's INTAKE→…→DELIVERED):
`RECEIVED → INTAKE_COMPLETE → PLANNED → WAITING_FOR_APPROVAL → READY_TO_EXECUTE → EXECUTING →
(EXECUTION_PARTIAL/REPAIR_REQUIRED) → VERIFYING → READY_FOR_REVIEW → READY_FOR_DELIVERY → COMPLETED`,
plus `WAITING_FOR_INFORMATION / BLOCKED / FAILED / CANCELLED`.

### Prospect QA Radar / Scout (`core/scout/`)
| Component | Role |
| --- | --- |
| `scout/discovery/*`, `scout/pipeline/*`, `scout/engine.py`, `scout/service.py`, `scout/store.py` | Campaign intake, discovery, triage, QA execution, evidence, run store |
| `scout/memory/db.py` + `repository.py`, `scout/comms/repository.py` | Transactional SQLite (schema v3): companies, findings, evidence, contacts, provenance, comms, approvals |
| `scout/outreach/*`, `scout/comms/*` | Disclosure, contacts, drafts, approval, revalidation, providers (local sink / Gmail / Resend), events, metrics |
| `scout/dashboard.py` | Local web UI — stdlib `http.server` ThreadingHTTPServer serving inline HTML (overview, campaign, presend, comms views) + `/api/*` JSON + `/health` |
| `scout/integrations/mcp.py` + `config/mcp_servers.v2.yaml` | MCP manifest audit (references-only; honest readiness) |
| `scout/cli.py` + `comms/cli.py` | Scout CLI (run/demo/dashboard/control/campaign/presend/comms/gmail/provider) |

## Reuse map by required v3.0.0 feature

### Milestone 0 — Gmail identity integrity
| Requirement | Classification | Component |
| --- | --- | --- |
| Authoritative id-token verification (official injectable verifier) | **EXTEND** (done) | `comms/gmail_oauth.py` (`official_id_token_verifier`, `verify_gmail_identity`), `comms/gmail.py` (`GmailProvider.preflight` identity prover), `runtime.py` |

### Milestone 2 — Client Work / Upwork operator workflow
| Requirement | Classification | Component |
| --- | --- | --- |
| Intake snapshot (immutable job text/metadata) | **EXTEND** | `UniversalWorkIntake` + `WorkRequest.raw_brief`; add a timestamped `JOB_SNAPSHOT` + `INPUT_MAP` artifact writer |
| Feasibility verdict (RECOMMENDED/CLARIFY/SETUP/NOT) | **EXTEND** | new `feasibility` decision built from `requirement_extractor` + `missing_information_analyzer` + `capability_planner` + `profile_selector`; persist as `FEASIBILITY_REPORT` |
| Questions / clarification | **REUSE_AS_IS** | `missing_information_analyzer.py` |
| Lifecycle + human approval boundary | **REUSE_AS_IS** | `work_state_manager.py` + `work_run_state` transitions |
| Capability/toolchain selection | **REUSE_AS_IS / EXTEND** | `capability_planner`, `toolchain_composer`, `profile_selector` (extended via the M3 broker) |
| Claude Code entrypoints + NL recognition | **EXTEND** | operator commands/skills + `CLAUDE.md` phrase recognition (no unsupported slash syntax) |
| Client workspace artifacts (`outputs/client-work/<id>/…`) | **EXTEND** | existing artifact/`content_safety` writer conventions |
| Delivery package | **REUSE_AS_IS / EXTEND** | `client_delivery`, `delivery_plan`, `delivery_preview`, `work_delivery` schemas |
| Supported/rejected work profiles | **REUSE_AS_IS / EXTEND** | `profile_selector.py` + capability registry (honest rejection) |

### Milestone 3 — Capability & tool broker
| Requirement | Classification | Component |
| --- | --- | --- |
| Central broker (what/which/available/safe/fallback) | **EXTEND** | `capability_registry` + `toolchain_composer` + `integrations/mcp.py`; add availability-domain + readiness + health-check + selection-explanation layer |
| Availability domains (session/local/connector/external/internal) | **EXTEND** | new honest classification over the MCP snapshot + local tool discovery |
| Readiness ladder + health checks | **EXTEND** | reuse MCP audit readiness; add `gh`/Playwright/Context7/etc. profiles |
| Dynamic task-driven selection | **REUSE_AS_IS / EXTEND** | `toolchain_composer` ranking |
| Tool readiness UI + command | **EXTEND** | `provider-status`/`doctor` + a dashboard Tool Readiness page |

### Milestone 4 — Scout operator web UI
| Requirement | Classification | Component |
| --- | --- | --- |
| Home / campaigns / results / company detail / tool readiness / system health pages | **EXTEND** | `scout/dashboard.py` (existing stdlib http.server UI) — extend, do NOT replace the stack or build a web IDE |
| New-campaign simple form + safe defaults | **EXTEND** | dashboard + `discovery/config.py` campaign config |
| Running-campaign progress + controls | **REUSE_AS_IS / EXTEND** | `ScoutService` + dashboard `/api/control` (pause/resume/cancel/kill already exist) |
| Results list / filters / company detail / evidence / contact / draft | **EXTEND** | `memory/repository.py` + `comms` (drafts/provenance) → dashboard read views |
| Gmail intent (Open in Gmail / Copy / Mark contacted) — manual-first | **EXTEND** | build a `mailto:`/Gmail-compose intent + draft copy; API send stays the optional one-at-a-time path |

### Milestone 5 — Shared project state & artifacts
| Requirement | Classification | Component |
| --- | --- | --- |
| One project index over client projects + Scout campaigns | **EXTEND (adapter)** | a read-only index/service over existing sources of truth (work states + Scout store + memory DB) — NO new database |
| Restart/recovery, fingerprint dedup, backup/restore, migrations | **REUSE_AS_IS** | `WorkRunState` persistence + `RunStore` + `memory/db.py` (transactional additive migrations, backup/restore) + `input_fingerprint` |
| Human-readable errors | **EXTEND** | error-formatting adapter over existing exceptions |

### Milestone 6 — Operator onboarding & one-command start
| Requirement | Classification | Component |
| --- | --- | --- |
| Windows setup/start/stop/doctor scripts | **EXTEND** | `scripts/` (has `radar.cmd`); add `setup-local.ps1`, `start-local.ps1`, `stop-local.ps1`, `doctor-local.ps1` |
| Operator guides + cheat sheet | **EXTEND** | new `QUICKSTART_OPERATOR.md` + guides; reuse `RUNBOOK.md`/`COMMANDS.md` |

### Milestone 7 — Acceptance & CI
| Requirement | Classification | Component |
| --- | --- | --- |
| Client-work benchmark scenarios (A–E) | **EXTEND** | deterministic fixtures over the intake/feasibility/planning path |
| Scout E2E + browser/axe/perf | **REUSE_AS_IS / EXTEND** | existing `playwright_acceptance` / `final1_browser_acceptance` markers + new UI page acceptance |
| CI (3 jobs) | **EXTEND** | existing `.github/workflows/ci.yml` (core-deterministic / provider-contract / browser-acceptance) |

## NOT_REQUIRED (explicitly out of scope)
- A replacement web IDE or web chat (Claude Code remains the coding surface).
- A second project/capability/evidence/work-state/communication store.
- Cloud deployment, SaaS, message brokers, distributed workers.
- Bulk/automatic outreach, inbox reading, CRM, mandatory Resend.
- Real OAuth, real email, real third-party scanning inside automated acceptance.

## Guiding rule
Every new module in v3.0.0 is an **adapter or additive extension** over the components above. If a
proven component works, it is reused as-is; it is replaced only with evidence it is broken.

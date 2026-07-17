# Universal Work & Delivery Factory — Component Architecture

**Version:** 8.0.0 (foundation)
**Status:** Planned architecture. Phase 8.0 introduces schemas and docs only; no runtime.

---

## Layered overview

```
                 main.py work --input <brief|job|url>   (Phase 8.1 — implemented, planning-only)
                                  │
   ┌───────────────────── ORCHESTRATION CORE ─────────────────────┐
   │ UniversalWorkIntake → WorkPacketBuilder → WorkPacket          │
   │        │                                                      │
   │ CapabilityPlanner ── reads ──▶ CapabilityRegistry             │
   │        │                       (capabilities/*.yaml)          │
   │        ▼                                                      │
   │ ToolchainComposer ── queries ─▶ MCPRegistry ◀─ MCPDiscovery   │
   │        │                                                      │
   │ ToolPolicyEngine (read/write/financial/external/destructive   │
   │        │           → action-based approval + audit trail)     │
   │        ▼                                                      │
   │ ExecutionOrchestrator ─▶ WorkerRouter ─▶ [existing runners /  │
   │        │                   playwright_cli / MCP backends]     │
   │        ▼   (WorkspaceManager: worktree + WorkRunState)        │
   │ EvidenceVerifier  ◀── INDEPENDENT of the implementer          │
   │        ▼                                                      │
   │ DeliveryAssembler → WorkDeliveryManifest + delivery pack      │
   └──────────────────────────────────────────────────────────────┘
   Opportunity layer (agents/): intake/fit/prescreen/proposal — feeds intake, no auto-submit
```

## Components and their existing precursors (reuse, not rebuild)

| Component | Precursor in repo | Phase 8.0 status |
|---|---|---|
| UniversalWorkIntake | `work_request_classifier`, `initial_analysis_engine`, `intake_agent`, `input_context_resolver`, `task_source_fetcher` | wrapper planned |
| WorkPacketBuilder | — | thin; schema added (`work_packet.py`) |
| CapabilityRegistry | `capabilities/*.yaml`, `agent_registry`, `workflow_registry` | schema added (`capability.py`) |
| CapabilityPlanner | `agents/capability_router.py`, `qa_strategy_planner` | schema added (`capability_plan.py`) |
| ToolchainComposer | `agents/dynamic_agent_factory.py` (stub) | schema added (`toolchain_plan.py`) |
| ToolPolicyEngine | `execution_approval`, `credential_safety_inspector`, `integration.IntegrationPolicy` | policy fields added |
| WorkerRouter | `llm_router`, `platform_router`, `stack_router` | extend planned |
| ExecutionOrchestrator | `orchestrator`, `e2e_pipeline_runner`, `workbench_controller` | wrapper planned |
| WorkspaceManager | `persistence`, `state`, `file_manager`, git worktrees | schema added (`work_run_state.py`) |
| EvidenceVerifier | `evidence_manager`, `evidence_intelligence`, `quality_gate`, `test_oracle` | schema added (`EvidenceClaim`) |
| DeliveryAssembler | `client_delivery_pack`, `client_delivery_report`, `ClientDeliveryManifest` | schema added (`WorkDeliveryManifest`) |
| ARK MCP server | `integrations/mcp/server.py` (7 tools) | preserved; v2 high-level tools planned |

## Capability vs CapabilityProfile

- **Capability** — an atomic ability (`web_navigation`, `database_read`, …). Registry:
  `capabilities/atomic_capabilities.yaml`. Schema: `Capability`.
- **CapabilityProfile** — a reusable bundle for a work category (`web_app_audit`, …).
  Registry: `capabilities/profiles/*.yaml`. Schema: `CapabilityProfile`.

Profiles reference capabilities by name; they never redefine them.

## Planning-only artifacts (Phase 8.1 — implemented)

`WORK_PACKET.json`, `WORK_SUMMARY.md`, `CAPABILITY_PLAN.json`, `TOOLCHAIN_PLAN.json`,
`AGENT_TASKS.md`, `APPROVALS_REQUIRED.md`, `NEXT_ACTION.md`,
`MCP_CONFIGURED_SERVERS_SNAPSHOT.json`.

Note: the configured-servers snapshot is server-level health/config only. Full protocol
discovery (`tools/list`) is planned for Phase 8.3 and writes `MCP_DISCOVERY_SNAPSHOT.json`.

## New backends (planned, additive — see `docs/WORK_EXECUTION_MODEL.md`)

Existing runners are preserved. A backend strategy field selects among
`existing_runner`, `playwright_cli`, `playwright_mcp`, `chrome_devtools_mcp`. MCP backends
are optional and are not a replacement for existing runners until parity is proven.

## Status note (Phase 8.1)

`main.py work` **exists as of Phase 8.1**. It remains deterministic and planning-only: it does
not execute MCP, network, browser, or external actions, and never enters an execution state.

## Second work contour — Prospect QA Radar / Super Scout (future-facing)

Prospect Radar is an **additive** ARK work contour (approved architecture, **not implemented**;
see [architecture/PROSPECT_QA_RADAR_SPEC.md](architecture/PROSPECT_QA_RADAR_SPEC.md)). It is
not a separate QA product, not a replacement for the Client Work Factory, not an independent
evidence system, not a from-scratch crawler, and not a currently working runtime. It reuses the
existing chain:

```
Prospect campaign planning
  → ARK requirement and capability planning
  → selected existing QA capabilities
  → existing QA runners (later phases)
  → existing evidence engine
  → independent verifier
  → existing delivery / reporting components
```

Domain contracts for this contour are planned for Phase 8.2 (see `docs/PHASE_CONTRACTS.md`);
`CapabilityRegistry`/`CapabilityPlanner` already exist and are extended, not rebuilt.

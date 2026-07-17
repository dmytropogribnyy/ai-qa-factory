# Reuse Map — Phase 8

**Version:** 8.0.0 (foundation)
**Purpose:** Record exactly what ARK reuses, extends, and adds, so Phase 8 does not
duplicate mature code or rebuild a second Factory.

---

## Schemas — new (added in Phase 8.0)

| File | Classes |
|---|---|
| `core/schemas/requirement.py` | `Requirement` |
| `core/schemas/work_packet.py` | `WorkPacket` |
| `core/schemas/capability.py` | `Capability`, `CapabilityProfile` |
| `core/schemas/capability_plan.py` | `CapabilityPlan`, `PlannedCapability` |
| `core/schemas/mcp_descriptor.py` | `MCPServerDescriptor`, `MCPToolDescriptor` |
| `core/schemas/toolchain_plan.py` | `ToolchainPlan`, `SelectedMCPTool`, `ToolExecutionPolicy`, `ExecutionBudget` |
| `core/schemas/work_run_state.py` | `WorkRunState`, `StateTransition` |
| `core/schemas/work_delivery.py` | `WorkDeliveryManifest` |
| `core/schemas/evidence.py` (additive) | `EvidenceClaim` |

## Schemas — preserved unchanged (reused, not modified)

- `WorkRequest` (`work_request.py`) — wrapped by `WorkPacket`, not duplicated.
- `ToolSelection` / `ToolRecommendation` (`tool_selection.py`) — remains a recommendation
  input; **not** extended into a runtime schema. Executable composition lives in
  `toolchain_plan.py`.
- `ClientDeliveryManifest` (`client_delivery.py`) — **not** renamed or generalised.
  `WorkDeliveryManifest` references it by type + path.
- `ApprovalDecision` (`approval.py`), `ExecutionApprovalRequirement` (`execution_approval.py`).
- `AutomationAction` (`automation_plan.py`) — basis for execution steps.
- `IntegrationEndpoint` / `IntegrationPolicy` (`integration.py`) — reference-only pattern
  reused by the MCP manifest.
- `TaskClassification` (`task_classification.py`).
- `ProjectStatus` (`project_status.py`) — complemented by `WorkRunState`, not replaced.

## Components — reuse precursors (wrappers planned, no rebuild)

See the table in `docs/UNIVERSAL_WORK_FACTORY.md`. Highlights:
- EvidenceVerifier is built on the existing `evidence_manager`, `evidence_intelligence`,
  `quality_gate`, `test_oracle` — the QA Factory already is the independent verifier.
- DeliveryAssembler wraps `client_delivery_pack` / `client_delivery_report`.
- ExecutionOrchestrator wraps `orchestrator` / `e2e_pipeline_runner` / `workbench_controller`.
- The MCP **server** (`integrations/mcp/server.py`) is preserved; the MCP **client** is a
  new package (`core/mcp_client/`, planned) to avoid naming ambiguity.

## Avoided duplicates (explicit)

| Tempting new schema | Reused instead |
|---|---|
| A second `WorkRequest` | existing `WorkRequest`, wrapped by `WorkPacket` |
| A universal `ToolSelection` god-schema | new `ToolchainPlan` + `SelectedMCPTool`; legacy `ToolSelection` untouched |
| A renamed `DeliveryManifest` | new `WorkDeliveryManifest` referencing `ClientDeliveryManifest` |
| A new evidence store | new `EvidenceClaim` in the existing evidence family |
| A new project status system | new `WorkRunState` complementing `ProjectStatus` |

## Capability data (not code)

- `capabilities/atomic_capabilities.yaml` — 17 atomic capabilities with class, approval
  default, candidate backends, and candidate MCP servers.
- `capabilities/profiles/*.yaml` — 9 profiles referencing atomic capabilities (the 9th,
  `prospect_qa_radar`, was added in Phase 8.2 slice 1 and is planning-only).
- `config/mcp_servers.yaml` — redacted, versioned MCP server manifest (plugin-style; new
  server = new YAML block).

---

## Prospect QA Radar / Super Scout — reuse decisions (future-facing, Phase 8.2+)

The second ARK contour must consume existing capabilities, not rebuild them. See
[architecture/PROSPECT_QA_RADAR_SPEC.md](architecture/PROSPECT_QA_RADAR_SPEC.md). Nothing here
is implemented; each candidate below requires reuse analysis before any model is added.

**REUSE (as-is):** existing browser and test runners; Playwright framework; API testing
capabilities; accessibility pipeline; Lighthouse/performance pipeline; passive security/privacy
checks; evidence manager; evidence intelligence; quality gate; test oracle; client delivery
pack; content redaction; credential safety; approval model; `WorkRunState` patterns; capability
registry; capability planner; opportunity/prescreen components where they genuinely fit.

**EXTEND:** capability profiles; capability planning; artifact contracts; evidence claims;
lifecycle/state semantics; policy model; scoring model; verification adapters;
delivery/disclosure projections; storage/retention governance.

**NEW, THIN, DOMAIN-SPECIFIC:** campaign planning; business eligibility; business-flow
classification; company identity resolution; contact provenance; contact/suppression lifecycle;
site memory; recheck planning; evidence disclosure policy; prospect prioritization;
audit-offer mapping; dashboard read models/projections.

**DO NOT BUILD:** a second QA engine; a second evidence engine; a second verifier; a second
report generator; a separate secret scanner; a universal crawler from scratch when established
providers/adapters suffice; automatic outreach in the MVP; an anti-bot/CAPTCHA bypass engine;
mass proxy-evasion infrastructure.

### Implemented in Phase 8.2 — slice 1 (campaign definition contracts)

First contracts-only slice (planning only; no runtime). Reuse decisions actually taken:

- **REUSED as-is:** `SchemaMixin` (serialization, additive-safe unknown-key handling);
  `SourceReference` (campaign origin/owner — no new provenance model).
- **REUSED as pattern:** `WorkRunState` (uuid id / UTC ISO timestamps / explicit version,
  without reusing client-work states); `ToolExecutionPolicy` / `IntegrationPolicy`
  (conservative `read_only` / approval-default policy shape); `config/mcp_servers.yaml`
  reference-only manifest (a discovery source is a planning candidate, never verified
  runtime); the documented `APPROVAL_MODEL.md` action classes (typed as
  `InteractionActionClass`).
- **NEW THIN domain models:** `ProspectCampaign`, `CampaignTargetCriteria`, `MarketPolicy`,
  `DiscoverySourcePolicy`, `InteractionBoundary` (fail-closed) in
  `core/schemas/prospect_campaign.py` + `core/schemas/prospect_interaction.py`.
- **EXTENDED (data):** `capabilities/profiles/prospect_qa_radar.yaml` (planning-only,
  reuses existing atomic capabilities, records the rest as `planned_capability_gaps`);
  `CAPABILITY_PROFILES` gains `prospect_qa_radar`.
- **Still deferred:** contact/identity, findings/disclosure, scoring, synthetic data, site
  memory, dashboard — see `docs/handoffs/PHASE_8_2_REUSE_ANALYSIS.md`.

### Implemented in Phase 8.2 — slice 2 (business & site profile contracts)

Second contracts-only slice (planning only; no runtime). Reuse decisions actually taken:

- **REUSED as-is:** `SchemaMixin`; `SourceReference` (provenance for `BusinessContext` and
  `SiteFingerprint`); `Confidence` *values* from `finding.py` (string-typed vocabulary, not
  a new enum); `InteractionActionClass` (planned flow interaction class);
  `ATOMIC_CAPABILITIES` (capability references in `BusinessFlowProfile` / `CoverageArea`).
- **REUSED as pattern:** opaque-string fingerprints following `WorkPacket.input_fingerprint`
  (no in-schema hashing, no crawling).
- **NEW THIN domain models:** `BusinessContext`, `SiteProfile`, `BusinessFlowProfile`
  (`core/schemas/prospect_business.py`); `CoverageArea`, `CoverageMap`, `SiteFingerprint`
  (`core/schemas/prospect_coverage.py`).
- **Reuse-decision correction:** the reuse analysis tentatively classified `CoverageMap` as
  EXTEND of `scenario_execution_matrix`. Implementation kept it a **thin new projection**
  instead — QA coverage and commercial opportunity must stay decoupled, and coupling to the
  execution matrix would have blurred that. Recorded here as the verified decision.
- **Fail-closed rules:** `COVERED`/`PARTIAL` require an evidence/verification reference;
  fingerprint inputs reject secret/session/volatile terms; unknown enums/statuses raise.
- **Still deferred:** contact/identity, findings/disclosure, scoring/lifecycle, synthetic
  data, retention/suppression/storage-class, dashboard.

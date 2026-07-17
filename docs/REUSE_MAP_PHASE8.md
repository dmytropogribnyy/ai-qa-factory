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

### Implemented in Phase 8.2 — slice 3 (identity / lifecycle / governance)

- **REUSED as-is:** `SchemaMixin`; `SourceReference` (identity provenance); `Confidence`
  values; `CleanupPolicy` (**composed** by `ProspectRetentionPolicy` — no competing cleanup
  engine; retention forces dry-run / preserve-git / preserve-client and preserves
  suppression + identity metadata; deletion is never executed).
- **REUSED as pattern:** `WorkRunState` / `StateTransition` shape for `ProspectLifecycle`
  (a parallel prospect vocabulary + deterministic transition map, not a reuse of the
  client-work states).
- **NEW THIN domain models:** `DomainIdentity`, `CompanyIdentity`
  (`core/schemas/prospect_identity.py`); `ProspectTransition`, `ProspectLifecycle`
  (`core/schemas/prospect_lifecycle.py`); `SuppressionPolicy`, `ProspectRetentionPolicy`,
  `RecheckPolicy`, `ProspectGovernancePlan` (`core/schemas/prospect_governance.py`).
- **Fail-closed rules:** hostname normalization rejects URLs/credentials/ports/single-label;
  ≤ 1 primary domain and hostname-unique; `CONTACTED` requires approved lineage; suppression
  requires a reason (COOLDOWN requires expiry); negative durations rejected; `NO_SCAN`
  suppression cannot coexist with an active recheck.

### Implemented in Phase 8.2 — slice 4 (scoring foundation)

- **INSPECTED precursor, NOT reused:** `agents/opportunity_filter.py` (runtime heuristic).
  `prospect_scoring.py` is a pure data contract instead.
- **NEW THIN domain models:** `ScoreDimension`, `LeadScorecard`, `ProspectPriority`.
- **Fail-closed rules:** 12 independent visible dimensions (0..100); optional weighted total
  only from explicit, validated, normalized weights (no hidden single score); no automatic
  outreach eligibility; access complexity / public coverage / remediation fit stay
  independent (never auto-derived from one another).

### Implemented in Phase 8.2 — child slice (contact / storage / disclosure)

On branch `phase/8.2-prospect-contact-disclosure-contracts` (child of the hardened core
branch). Contracts/planning only.

- **REUSED as-is:** `SchemaMixin`; `SourceReference` + `Confidence`; `normalize_hostname`
  from `prospect_identity.py` (shared canonical hostname logic for email domains and
  suppression domains).
- **NEW THIN domain models:** `ContactProvenance`, `ContactStatus`, `ContactRecord`,
  `ContactCollection` (`core/schemas/prospect_contact.py`); `StorageClass`,
  `DisclosureLevel`, `DisclosureStage`, `DisclosureItem`, `FindingDisclosurePolicy`,
  `DisclosureManifest` (`core/schemas/prospect_disclosure.py`).
- **Reuse-decision correction:** `ContactProvenance` is stored **nested** inside
  `ContactRecord` (a list) rather than as a separate top-level artifact/schema — it reuses
  `SourceReference` and avoids a duplicate provenance model. `StorageClass` (deferred in the
  earlier analysis) is implemented here as a disclosure-handling axis, kept strictly
  separate from `DisclosureLevel`.
- **Fail-closed rules:** public sources only (no private/stolen category); inferred contacts
  can never be `VERIFIED`; named-person → manual review; only `VERIFIED` is an outreach
  candidate; `CLIENT_SAFE` requires sanitized + no PII/secrets; `OUTREACH_ELIGIBLE` requires
  independent verification + `CLIENT_SAFE` + minimal teaser; responsible-disclosure stays
  `INTERNAL_ONLY`; `DisclosureManifest` readiness is computed (never a trusted boolean) and
  the manifest sends nothing.
- **DO NOT BUILD (still deferred):** synthetic data contracts; broad discovery; contact-lookup/
  enrichment runtime; outreach/delivery-sending runtime.

### Implemented in Phase 8.3 — Prospect QA Scout v1.0 (bounded read-only runtime)

The first runnable slice. See [architecture/SCOUT_RUNTIME_V1.md](architecture/SCOUT_RUNTIME_V1.md).

- **REUSED as-is:** `core/orchestration/content_safety.py` (`ContentSecretScanner`,
  `redact_intake_text`, `ArtifactSafeWriter`) for evidence sanitization + atomic secret-scanned
  report publishing; `prospect_scoring.LeadScorecard`/`ScoreDimension` for scoring;
  `prospect_campaign.ProspectCampaign` as optional provenance; Python stdlib `http.server` for
  the dashboard (no new web dependency).
- **NEW THIN runtime (`core/scout/`):** `url_safety`, `config`, `backends` (+ optional lazy
  Playwright), `checks`, `findings`, `sanitize`, `verification`, `scoring`, `store`, `control`,
  `engine`, `service`, `dashboard`, `report`, `cli`, `demo_site`.
- **DID NOT BUILD:** a second QA/evidence/verifier/report engine, a separate secret scanner, a
  universal crawler, automatic outreach, contact enrichment, or any CAPTCHA/proxy-evasion
  capability.

### Implemented in Phase 8.4 — discovery + commercial triage (`core/scout/discovery/`)

Extends the runtime from explicit seeds to campaign-driven discovery + qualification.

- **REUSED as-is:** `prospect_campaign.ProspectCampaign` / `CampaignTargetCriteria` /
  `MarketPolicy` / `DiscoverySourcePolicy` (campaign definition + validation);
  `prospect_identity.CompanyIdentity` / `DomainIdentity` / `normalize_hostname` (domain
  normalization + dedup); `prospect_governance.SuppressionPolicy` (NO_SCAN/NO_OUTREACH/COOLDOWN);
  `prospect_business.BusinessContext` vocabularies; `prospect_scoring.LeadScorecard` /
  `ScoreDimension` (explainable commercial triage); `SourceReference` (provenance); the Scout
  `url_safety` + static `backends` profiler; `RunStore` (+ new `save_artifact`/`load_artifact`);
  `ArtifactSafeWriter` (atomic secret-scanned publish); the existing `ScoutEngine` (promotion);
  and the existing `dashboard`/`service` (campaign views).
- **NEW THIN runtime (`core/scout/discovery/`):** `providers` (metadata/candidate/registry +
  fixture/file-import/adapter-ready providers), `candidate`, `config`, `matrix`, `normalize`,
  `suppression`, `triage`, `engine`, `report`, `cli`, `fixtures`.
- **DID NOT BUILD:** a second URL-safety engine, company-identity model, Scout QA engine,
  persistence layer, crawler, or dashboard app; no contact discovery/enrichment; no outreach
  drafting or sending; no transactional site-memory database (that is Phase 8.6).

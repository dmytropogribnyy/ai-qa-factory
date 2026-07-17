# Phase 8.2 — Prospect Radar Reuse Analysis (working handoff)

**Status:** working analysis for the next Claude Code session
**Canonical architecture:** `docs/architecture/PROSPECT_QA_RADAR_SPEC.md`
**Implementation authority:** `docs/PHASE_CONTRACTS.md`
**Runtime implemented:** no
**Author:** GitHub Copilot reviewer session, 2026-07-17

This is an **operational handoff analysis**, not a new canonical roadmap or product
specification. It does not modify the approved Prospect Radar spec and does not create a
second roadmap. Every candidate below still requires the Phase 8.2 reuse gate before any
model is written; classifications here are recommendations to accelerate that review.

---

## How to read this

Each candidate contract from `docs/PHASE_CONTRACTS.md` (Phase 8.2) is classified:

- **REUSE AS-IS** — an existing schema/enum already covers it; do not add a new model.
- **EXTEND EXISTING** — add fields to, or build a thin parallel of, an existing model or
  established pattern; do not duplicate the concept.
- **NEW THIN DOMAIN MODEL** — genuinely new domain concept with no precursor; keep it
  minimal and reuse `SchemaMixin`.
- **DEFER** — belongs to a later phase (8.4/8.6+); no schema now.
- **OMIT AS DUPLICATE** — folds into another candidate; do not create separately.

**Shared invariants for every new schema (all classifications):**

- Subclass `core.schemas.base.SchemaMixin`; provide `to_dict()` / `from_dict()` round-trip.
  `SchemaMixin.from_dict` already filters unknown keys, so **additive fields are
  forward-compatible** — new optional fields never break old artifacts.
- Pure dataclasses, no side effects, no I/O, no network, no runtime dispatch (Phase 8.2 is
  planning/contracts only).
- No raw secrets/PII stored: reuse `credential_safety` / `redaction` conventions and store
  redacted values plus a `StorageClass`.
- Enums as `str, Enum` (matches `Finding`, `ClientAuditMode`).
- Deterministic serialization; carry an explicit `schema_version` string on top-level
  campaign/prospect records for future evolution (mirrors `WorkRunState.state_version`).

**Confirmed precursor inventory (verified this session):**

| Concept | Existing file | Key classes / constants |
|---|---|---|
| Serialization | `core/schemas/base.py` | `SchemaMixin` |
| Findings | `core/schemas/finding.py` | `Finding`, `Severity`, `FindingCategory`, `FindingStatus`, `Confidence` |
| Lifecycle/state | `core/schemas/work_run_state.py` | `WorkRunState`, `WORK_RUN_STATES`, `ALLOWED_TRANSITIONS`, `TERMINAL_STATES` |
| Origin/provenance | `core/schemas/source_reference.py` | `SourceReference` (url/platform/title/retrieved_at/notes) |
| Capability model | `core/schemas/capability.py` | `Capability`, `CapabilityProfile`, `CAPABILITY_CLASSES`, `ATOMIC_CAPABILITIES` |
| Capability planning | `core/schemas/capability_plan.py` | `CapabilityPlan`, `PlannedCapability`, `CAPABILITY_AVAILABILITY` |
| Approval | `core/schemas/approval.py`, `execution_approval.py` | `ApprovalDecision`, `ApprovalHistory`, `ExecutionApprovalRequirement`, `ExecutionReadinessReport` |
| Evidence | `core/schemas/evidence.py` | `EvidenceRecord`, `EvidenceCollection`, `EvidenceQualityGate`, `EvidenceRedactionReport`, `EvidenceClaim` |
| Delivery | `core/schemas/client_delivery.py`, `work_delivery.py` | `ClientDeliveryManifest`, `DeliveryArtifact`, `SecretScanResult`, `WorkDeliveryManifest` |
| Audit aggregation | `core/schemas/client_audit.py` | `ClientAuditPlan`, `ModuleResult`, `ClientAuditResult` |
| Tool/exec policy | `core/schemas/toolchain_plan.py` | `ToolExecutionPolicy`, `ExecutionBudget`, `SelectedMCPTool` |
| Reference-only policy | `core/schemas/integration.py` | `IntegrationEndpoint`, `IntegrationPolicy` |
| Commercial/scoring | `agents/opportunity_filter.py`, `agents/commercial_strategy.py`, `agents/pricing_advisor.py`, `agents/prescreening.py`, `agents/job_analyzer.py` | fit-score / apply-skip / pricing logic |
| Orchestration | `core/orchestration/capability_registry.py`, `capability_planner.py` | already exist (Phase 8.1) |

No contact, campaign, market-policy, site-memory, disclosure, or scoring **schema** exists
yet — those are the genuinely new domain surface.

---

## Candidate-by-candidate analysis

### Campaign definition group

#### ProspectCampaign — NEW THIN DOMAIN MODEL
- **Precursor:** `WorkPacket` (`work_packet.py`) as the "unit of work" pattern;
  `WorkRunState` for lifecycle; `ProjectStatus` for status strings.
- **Rationale:** a campaign is a new top-level batch-of-prospecting concept with no 1:1
  precursor. Do **not** overload `WorkPacket` (single client work unit).
- **Proposed module/class:** `core/schemas/prospect_campaign.py` → `ProspectCampaign`.
- **Reuse fields:** reference `WorkRunState.run_idempotency_key` / `state_version` shape;
  reference `CampaignTargetCriteria` and `MarketPolicy` by nested object, not copy.
- **Additive fields:** `campaign_id`, `title`, `objective`, `schema_version`,
  `created_at`, `target_criteria`, `market_policy`, `discovery_source_policy`,
  `status` (see ProspectLifecycle), `notes`.
- **Invariants:** planning-only; no runtime handle; `client_ready`/execution flags absent
  or `False`; ids deterministic under fixed clock.
- **Serialization/versioning:** carry `schema_version="8.2.0"`; nested objects round-trip.
- **Likely tests:** round-trip, default-safe (no execution field), nested-policy round-trip.
- **Dependencies:** `SchemaMixin`, `CampaignTargetCriteria`, `MarketPolicy`,
  `DiscoverySourcePolicy`.
- **Blocked runtime:** discovery, crawling, provider calls.
- **Phase:** 8.2 (slice 1).
- **Duplicate risk:** medium — must not become a second `WorkPacket`; keep it a campaign
  header that *references* work units later.

#### CampaignTargetCriteria — NEW THIN DOMAIN MODEL
- **Precursor:** none direct; conceptually similar to intake signal filters in
  `agents/opportunity_filter.py` (vertical/value/risk gates).
- **Rationale:** small filter object (vertical, geography, size band, tech signals).
- **Proposed class:** in `prospect_campaign.py` → `CampaignTargetCriteria`.
- **Reuse fields:** none to copy; align vocabulary with existing project-type taxonomy.
- **Additive fields:** `verticals`, `geographies`, `size_bands`, `include_signals`,
  `exclude_signals`, `max_targets`.
- **Invariants:** pure data; lists default-empty.
- **Tests:** round-trip; empty defaults.
- **Dependencies:** `SchemaMixin`.
- **Blocked runtime:** none (data only).
- **Phase:** 8.2 (slice 1).
- **Duplicate risk:** low.

#### MarketPolicy — NEW THIN DOMAIN MODEL (pattern EXTEND of IntegrationPolicy)
- **Precursor:** `IntegrationPolicy` / `ToolExecutionPolicy` (reference-only policy shape).
- **Rationale:** governs jurisdiction, rate ceilings, allowed markets — a policy record,
  not executable config. Model on the existing reference-only policy pattern.
- **Proposed class:** in `prospect_campaign.py` → `MarketPolicy`.
- **Reuse fields:** mirror `ToolExecutionPolicy` fields for rate/budget semantics
  (`max_*`, `requires_approval`), reuse names where sensible.
- **Additive fields:** `allowed_jurisdictions`, `blocked_jurisdictions`,
  `max_requests_per_domain`, `respect_robots` (default `True`), `requires_human_approval`.
- **Invariants:** conservative defaults (respect robots, approval required for anything
  beyond read).
- **Tests:** round-trip; default-conservative.
- **Dependencies:** `SchemaMixin`.
- **Blocked runtime:** no enforcement engine (documentation of intent only).
- **Phase:** 8.2 (slice 1).
- **Duplicate risk:** low.

#### DiscoverySourcePolicy — EXTEND EXISTING (IntegrationEndpoint/config pattern)
- **Precursor:** `IntegrationEndpoint` + `config/mcp_servers.yaml` reference-only manifest.
- **Rationale:** describes *which* discovery sources are permitted (search providers) as
  reference-only, exactly like the MCP server manifest — do not build a provider client.
- **Proposed class:** in `prospect_campaign.py` → `DiscoverySourcePolicy`.
- **Reuse fields:** `IntegrationEndpoint`-style `name`/`kind`/`enabled` (default `False`).
- **Additive fields:** `allowed_sources`, `disallowed_sources`, `max_depth`,
  `read_only` (always `True` in 8.2).
- **Invariants:** `enabled=False` and `read_only=True` by default; no live source runtime.
- **Tests:** round-trip; disabled-by-default.
- **Dependencies:** `SchemaMixin`.
- **Blocked runtime:** live discovery/crawling.
- **Phase:** 8.2 (slice 1).
- **Duplicate risk:** low.

### Business understanding group

#### BusinessContext — NEW THIN DOMAIN MODEL
- **Precursor:** `ProjectBlueprint` (inferred project type/environment) — same "inferred
  understanding" idea, different domain.
- **Rationale:** captures inferred business model/vertical/flows for a discovered site.
- **Proposed module:** `core/schemas/prospect_business.py` → `BusinessContext`.
- **Additive fields:** `vertical`, `business_model`, `detected_flows`, `confidence`
  (reuse `Confidence` enum from `finding.py`), `inferred_from`.
- **Invariants:** inference only; `confidence` explicit.
- **Tests:** round-trip; confidence enum reuse.
- **Dependencies:** `SchemaMixin`, `Confidence`.
- **Phase:** 8.2 (slice 2).
- **Duplicate risk:** medium — keep distinct from `SiteProfile` (technical) vs
  `BusinessContext` (commercial).

#### SiteProfile — NEW THIN DOMAIN MODEL
- **Precursor:** `profile_selection.py`, `ProjectBlueprint` surfaces.
- **Rationale:** technical snapshot (stack, flows present, protection status).
- **Proposed module:** `core/schemas/prospect_business.py` → `SiteProfile`.
- **Additive fields:** `domain`, `tech_signals`, `flow_signals`, `protection_status`
  (`open`/`protected`/`partially_protected`), `robots_state`.
- **Invariants:** protected site is **not** auto-rejected (per SAFETY_RULES); status is
  descriptive only.
- **Tests:** round-trip; protected-status does not imply reject.
- **Dependencies:** `SchemaMixin`.
- **Phase:** 8.2 (slice 2).
- **Duplicate risk:** medium vs BusinessContext — split technical/commercial cleanly.

#### BusinessFlowProfile — NEW THIN DOMAIN MODEL
- **Precursor:** `CapabilityProfile` (bundle-by-name pattern), `qa_strategy` TEST_LAYERS.
- **Rationale:** classifies business flows (checkout/booking/signup) and maps to existing
  capability profiles by name — never redefines capabilities.
- **Proposed module:** `core/schemas/prospect_business.py` → `BusinessFlowProfile`.
- **Additive fields:** `flow_name`, `flow_class`, `capability_profile_ref` (name only),
  `interaction_boundary_ref`.
- **Invariants:** references capability profiles by name (like `CapabilityProfile`).
- **Tests:** round-trip; capability reference is a name, not a redefinition.
- **Dependencies:** `SchemaMixin`.
- **Phase:** 8.2 (slice 2).
- **Duplicate risk:** low.

### Interaction boundary group

#### InteractionActionClass — EXTEND EXISTING (capability class vocabulary)
- **Precursor:** `CAPABILITY_CLASSES` (`read/compute/write/financial/
  external_communication/destructive`) **plus** the planned classes already documented in
  `docs/APPROVAL_MODEL.md` (`READ_ONLY`, `REVERSIBLE_SESSION_WRITE`,
  `POTENTIAL_BUSINESS_SIDE_EFFECT`, `EXTERNAL_COMMUNICATION`, `FINANCIAL`, `DESTRUCTIVE`).
- **Rationale:** this is a **vocabulary**, already half-defined in docs. Define one small
  enum aligned to those documented classes; do not invent a competing taxonomy.
- **Proposed class:** `core/schemas/prospect_interaction.py` → `InteractionActionClass`
  (`str, Enum`).
- **Invariants:** map each value to an approval default consistent with APPROVAL_MODEL.
- **Tests:** enum values match APPROVAL_MODEL table; destructive default-blocked.
- **Dependencies:** `SchemaMixin` (for the wrapper), `str, Enum`.
- **Phase:** 8.2 (slice 2).
- **Duplicate risk:** high if it diverges from `CAPABILITY_CLASSES`/APPROVAL_MODEL — keep
  a single documented mapping.

#### InteractionBoundary — EXTEND EXISTING (approval-requirement pattern)
- **Precursor:** `ExecutionApprovalRequirement` (`execution_approval.py`).
- **Rationale:** declares which action classes are permitted/blocked for a given flow —
  a policy over `InteractionActionClass`. Reuse the approval-requirement shape.
- **Proposed class:** `core/schemas/prospect_interaction.py` → `InteractionBoundary`.
- **Additive fields:** `allowed_classes`, `blocked_classes`, `requires_approval_classes`,
  `notes`.
- **Invariants:** `POTENTIAL_BUSINESS_SIDE_EFFECT`+ never in `allowed_classes` without
  approval; destructive always blocked.
- **Tests:** round-trip; invariant that business-side-effect is not auto-allowed.
- **Dependencies:** `SchemaMixin`, `InteractionActionClass`.
- **Phase:** 8.2 (slice 2).
- **Duplicate risk:** low.

### Synthetic data group

#### SyntheticPersona — NEW THIN DOMAIN MODEL
- **Precursor:** scaffold `test-data/sample-users.example.json` PLACEHOLDER convention;
  `credential_safety` rules.
- **Rationale:** a synthetic (never real) identity for pre-submit form population.
- **Proposed module:** `core/schemas/prospect_synthetic.py` → `SyntheticPersona`.
- **Additive fields:** `persona_id`, `display_name`, `synthetic_email`, `locale`,
  `is_synthetic` (always `True`), `storage_class` (see StorageClass).
- **Invariants:** `is_synthetic=True` enforced in `__post_init__`; no real PII; values
  clearly placeholder-shaped.
- **Tests:** `is_synthetic` cannot be False; no real-looking secrets.
- **Dependencies:** `SchemaMixin`, `StorageClass`.
- **Phase:** 8.2 (slice 3) — defer past slice 1.
- **Duplicate risk:** low.

#### SyntheticDataPolicy — NEW THIN DOMAIN MODEL
- **Precursor:** `SyntheticDataPolicy` has no precursor; conceptually near
  `ToolExecutionPolicy`.
- **Rationale:** governs synthetic-data generation rules (no real data, no submit).
- **Proposed class:** in `prospect_synthetic.py` → `SyntheticDataPolicy`.
- **Additive fields:** `allow_form_population` (default `True`),
  `allow_form_submission` (default `False`), `allowed_field_types`, `forbidden_field_types`.
- **Invariants:** submission default-blocked.
- **Tests:** round-trip; submission blocked by default.
- **Dependencies:** `SchemaMixin`.
- **Phase:** 8.2 (slice 3).
- **Duplicate risk:** low.

### Coverage group

#### CoverageMap — EXTEND EXISTING → **implemented as NEW THIN (slice 2)**
- **Precursor:** `scenario_execution_matrix.py`, `ClientAuditPlan`/`ModuleResult`
  (`client_audit.py`), `qa_strategy` TEST_LAYERS.
- **Rationale:** a coverage projection over capabilities/flows already modeled elsewhere.
  Extend/compose from existing coverage structures rather than a new engine.
- **Proposed class:** `core/schemas/prospect_coverage.py` → `CoverageMap` (thin projection).
- **Additive fields:** `campaign_id`, `covered_capabilities`, `covered_flows`, `gaps`.
- **Invariants:** references capabilities by name.
- **Tests:** round-trip; gap detection.
- **Dependencies:** `SchemaMixin`.
- **Phase:** 8.2 (slice 3+).
- **Duplicate risk:** medium — must not duplicate `scenario_execution_matrix`.
- **IMPLEMENTED DECISION (slice 2, verified):** implemented as a **thin new schema**
  (`CoverageArea` + `CoverageMap`) rather than extending `scenario_execution_matrix`.
  Coupling to the execution matrix would have blurred the required separation between
  **public QA coverage** and **commercial opportunity**. `capability_refs` validated
  against `ATOMIC_CAPABILITIES`; `COVERED`/`PARTIAL` require an evidence/verification
  reference (fail-closed, since Phase 8.2 executes nothing).

### Identity group

#### CompanyIdentity — NEW THIN DOMAIN MODEL
- **Precursor:** none.
- **Rationale:** resolves a company (legal/display name, primary domain, identifiers).
- **Proposed module:** `core/schemas/prospect_identity.py` → `CompanyIdentity`.
- **Additive fields:** `company_id`, `display_name`, `primary_domain`, `identifiers`,
  `confidence` (reuse `Confidence`), `provenance` (see ContactProvenance/SourceReference).
- **Invariants:** confidence explicit; no scraped PII stored raw.
- **Tests:** round-trip; confidence reuse.
- **Dependencies:** `SchemaMixin`, `Confidence`, `DomainIdentity`.
- **Phase:** 8.2 (slice 4 — identity/contact is the most sensitive; defer).
- **Duplicate risk:** medium vs DomainIdentity.

#### DomainIdentity — NEW THIN DOMAIN MODEL (small) / candidate OMIT
- **Precursor:** none.
- **Rationale:** registrable domain + subdomains. Small enough that it *could* fold into
  `CompanyIdentity`. Recommend a small standalone value object only if reused by
  `SiteProfile` and `CompanyIdentity`; otherwise **OMIT AS DUPLICATE** and inline.
- **Proposed class:** `prospect_identity.py` → `DomainIdentity` (value object).
- **Additive fields:** `registrable_domain`, `subdomains`, `is_apex`.
- **Phase:** 8.2 (slice 4) or omit.
- **Duplicate risk:** high — decide fold-in during slice 4 review.

### Contact group (most sensitive — defer)

#### ContactRecord — NEW THIN DOMAIN MODEL
- **Precursor:** none (no contact module exists). PII handling reuses `redaction` /
  `credential_safety` / `EvidenceRedactionReport`.
- **Rationale:** a discovered public business contact channel, stored redacted.
- **Proposed module:** `core/schemas/prospect_contact.py` → `ContactRecord`.
- **Additive fields:** `contact_id`, `company_id`, `channel` (email/phone/form/social),
  `value_redacted`, `storage_class`, `status` (ContactStatus), `provenance`.
- **Invariants:** raw contact value never stored unredacted; `storage_class` set;
  suppression respected before any future use.
- **Tests:** redaction enforced; round-trip; suppressed status honored.
- **Dependencies:** `SchemaMixin`, `ContactStatus`, `ContactProvenance`, `StorageClass`.
- **Phase:** 8.2 (slice 4 — contract only; no lookup runtime).
- **Duplicate risk:** low.

#### ContactProvenance — EXTEND EXISTING (SourceReference)
- **Precursor:** `SourceReference` (url/platform/title/retrieved_at/notes).
- **Rationale:** provenance of a contact is the same shape as a work-request origin.
  Extend/wrap `SourceReference` rather than invent a parallel provenance model.
- **Proposed class:** `prospect_contact.py` → `ContactProvenance` (composes
  `SourceReference` + method/confidence).
- **Additive fields:** `method` (`public_page`/`whois`/`directory`), `confidence`,
  `source` (`SourceReference`).
- **Tests:** round-trip; wraps SourceReference.
- **Dependencies:** `SchemaMixin`, `SourceReference`, `Confidence`.
- **Phase:** 8.2 (slice 4).
- **Duplicate risk:** medium — reuse `SourceReference`, do not clone it.

#### ContactStatus — NEW THIN (small enum)
- **Precursor:** `FindingStatus` / `ContactStatus` conceptually mirror the small `str,Enum`
  status pattern.
- **Rationale:** lifecycle of a contact (`candidate`/`verified`/`suppressed`/
  `contacted`/`invalid`).
- **Proposed class:** `prospect_contact.py` → `ContactStatus` (`str, Enum`).
- **Tests:** enum membership; suppressed is terminal-for-use.
- **Phase:** 8.2 (slice 4).
- **Duplicate risk:** low.

### Disclosure group

#### FindingDisclosurePolicy — NEW THIN DOMAIN MODEL
- **Precursor:** `EvidenceRedactionReport`, `SecretScanResult`, `client_delivery` gating.
- **Rationale:** governs which findings/evidence may be disclosed to a prospect.
- **Proposed module:** `core/schemas/prospect_disclosure.py` → `FindingDisclosurePolicy`.
- **Additive fields:** `max_severity_disclosed`, `redact_before_disclosure` (default
  `True`), `require_verification` (default `True`), `blocked_categories`.
- **Invariants:** verification + redaction required before disclosure.
- **Tests:** round-trip; conservative defaults.
- **Dependencies:** `SchemaMixin`, `Severity`, `FindingCategory`.
- **Phase:** 8.2 (slice 5).
- **Duplicate risk:** low.

#### DisclosureManifest — EXTEND EXISTING (ClientDeliveryManifest)
- **Precursor:** `ClientDeliveryManifest` + `DeliveryArtifact` + `SecretScanResult`,
  `WorkDeliveryManifest`.
- **Rationale:** a disclosure manifest is a delivery projection; reuse the delivery
  manifest + secret-scan structures rather than a new delivery model.
- **Proposed class:** `prospect_disclosure.py` → `DisclosureManifest` (references
  `DeliveryArtifact`/`SecretScanResult`).
- **Additive fields:** `campaign_id`, `prospect_id`, `disclosed_findings`,
  `secret_scan` (`SecretScanResult`), `approved_for_disclosure` (default `False`).
- **Invariants:** `approved_for_disclosure=False` until human approval; secret scan clean
  required (mirrors delivery gating).
- **Tests:** round-trip; not-approved-by-default; reuse of SecretScanResult.
- **Dependencies:** `SchemaMixin`, `DeliveryArtifact`, `SecretScanResult`.
- **Phase:** 8.2 (slice 5).
- **Duplicate risk:** medium — must not clone `ClientDeliveryManifest`.

### Scoring & lifecycle group

#### LeadScorecard — NEW THIN DOMAIN MODEL
- **Precursor:** `agents/opportunity_filter.py` (`fit_score`), `agents/commercial_strategy.py`,
  `agents/pricing_advisor.py`.
- **Rationale:** structured prospect score; reuse existing scoring *logic* from the agents,
  do not rebuild it — the schema is a typed container for outputs those agents already
  compute.
- **Proposed module:** `core/schemas/prospect_scoring.py` → `LeadScorecard`.
- **Additive fields:** `prospect_id`, `fit_score`, `severity_weight`, `commercial_signals`,
  `priority` (ProspectPriority), `rationale`.
- **Invariants:** score bounded; rationale required.
- **Tests:** round-trip; bounds.
- **Dependencies:** `SchemaMixin`, `ProspectPriority`.
- **Phase:** 8.2 (slice 5).
- **Duplicate risk:** medium — reuse agent scoring, do not duplicate the algorithm.

#### ProspectPriority — NEW THIN (small enum)
- **Precursor:** `opportunity_filter` recommended-action tiers.
- **Rationale:** priority band (`high`/`medium`/`low`/`watch`).
- **Proposed class:** `prospect_scoring.py` → `ProspectPriority` (`str, Enum`).
- **Tests:** enum membership.
- **Phase:** 8.2 (slice 5).
- **Duplicate risk:** low.

#### ProspectLifecycle — EXTEND EXISTING (WorkRunState pattern)
- **Precursor:** `work_run_state.py` (`WORK_RUN_STATES`, `ALLOWED_TRANSITIONS`,
  `TERMINAL_STATES`, `state_version`, `run_idempotency_key`).
- **Rationale:** build a **parallel** prospect lifecycle vocabulary using the exact same
  module shape; do **not** reuse the client-work states verbatim and do not modify
  `WorkRunState`.
- **Proposed module:** `core/schemas/prospect_lifecycle.py` → `ProspectLifecycle` +
  `PROSPECT_STATES` + `ALLOWED_TRANSITIONS` + `TERMINAL_STATES`.
- **Additive fields:** states such as `DISCOVERED`, `ELIGIBLE`, `TRIAGED`, `ANALYZED`,
  `VERIFIED`, `SCORED`, `CONTACT_RESOLVED`, `DISCLOSURE_READY`, `OUTREACH_DRAFTED`,
  `WON`, `REJECTED`, `SUPPRESSED`.
- **Invariants:** terminal states immutable (mirror `TERMINAL_STATES`); forward-only
  documented transitions; no executor attached (planning only).
- **Tests:** transition-table well-formed; terminal states have no outgoing edges;
  round-trip.
- **Dependencies:** `SchemaMixin`.
- **Phase:** 8.2 — good **optional hardening commit** for slice 1.
- **Duplicate risk:** medium — keep it clearly separate from `WorkRunState`.

### Site memory & governance group

#### RecheckPolicy — NEW THIN DOMAIN MODEL
- **Precursor:** `ExecutionBudget`/`ToolExecutionPolicy` cadence fields.
- **Rationale:** recheck cadence + trigger rules.
- **Proposed module:** `core/schemas/prospect_memory.py` → `RecheckPolicy`.
- **Additive fields:** `min_interval_days`, `triggers`, `max_rechecks`.
- **Tests:** round-trip; default cadence.
- **Dependencies:** `SchemaMixin`.
- **Phase:** 8.2 (slice 6).
- **Duplicate risk:** low.

#### SiteFingerprint — NEW THIN DOMAIN MODEL
- **Precursor:** none; conceptually near `EvidenceRecord` hashing.
- **Rationale:** stable signature used for change detection.
- **Proposed class:** `prospect_memory.py` → `SiteFingerprint`.
- **Additive fields:** `domain`, `content_hash`, `structure_hash`, `captured_at`.
- **Invariants:** hashes only; no raw page bodies with secrets.
- **Tests:** round-trip; hash fields present.
- **Dependencies:** `SchemaMixin`.
- **Phase:** 8.2 (slice 6).
- **Duplicate risk:** low.

#### RetentionPolicy — NEW THIN DOMAIN MODEL
- **Precursor:** `EvidenceRedactionReport` + governance docs.
- **Rationale:** data retention windows per storage class.
- **Proposed class:** `prospect_memory.py` → `RetentionPolicy`.
- **Additive fields:** `retention_days_by_class`, `purge_on_suppression` (default `True`).
- **Tests:** round-trip; purge default.
- **Dependencies:** `SchemaMixin`, `StorageClass`.
- **Phase:** 8.2 (slice 6).
- **Duplicate risk:** low.

#### SuppressionPolicy — NEW THIN DOMAIN MODEL
- **Precursor:** none.
- **Rationale:** do-not-contact / suppression governance.
- **Proposed class:** `prospect_memory.py` → `SuppressionPolicy`.
- **Additive fields:** `suppressed_domains`, `suppressed_companies`, `honor_optout`
  (default `True`).
- **Invariants:** suppression always honored before any (future) outreach.
- **Tests:** round-trip; opt-out honored.
- **Dependencies:** `SchemaMixin`.
- **Phase:** 8.2 (slice 6).
- **Duplicate risk:** low.

#### StorageClass — NEW THIN (small enum)
- **Precursor:** `credential_safety` sensitivity concepts.
- **Rationale:** data classification (`public`/`business`/`sensitive_pii`/`secret`).
- **Proposed class:** shared value in `core/schemas/prospect_memory.py` (or a small
  `prospect_common.py`) → `StorageClass` (`str, Enum`).
- **Invariants:** `secret` values never persisted in artifacts.
- **Tests:** enum membership; secret-not-persisted rule referenced.
- **Phase:** 8.2 — needed early (slice 3/4 as a shared enum). Consider a tiny
  `prospect_common.py` so contact/synthetic/memory groups share it.
- **Duplicate risk:** low.

### Capability, dashboard, and artifact contracts

#### Prospect Radar capability/profile extensions — EXTEND EXISTING (data, not code)
- **Precursor:** `capabilities/atomic_capabilities.yaml`, `capabilities/profiles/*.yaml`,
  `capability.py`.
- **Rationale:** add new **YAML profiles** referencing existing atomic capabilities; the
  REUSE_MAP already states profiles reference capabilities by name and never redefine them.
- **Proposed change:** new `capabilities/profiles/prospect_*.yaml` (data), no new code.
- **Tests:** existing capability-profile validation tests cover new YAML.
- **Phase:** 8.2 (any slice touching capabilities) — very low risk.
- **Duplicate risk:** low (data-only).

#### Dashboard information architecture — DEFER
- **Precursor:** none needed now.
- **Rationale:** read models/projections are a Phase 8.4/8.6 concern; no schema in 8.2
  beyond, at most, documenting the intended IA in the spec (already covered).
- **Phase:** DEFER (8.4/8.6).
- **Duplicate risk:** n/a.

#### Planned artifact contracts — EXTEND EXISTING (docs)
- **Precursor:** `docs/ARTIFACT_CONTRACTS.md` already lists a planned Prospect namespace.
- **Rationale:** finalize directory/namespace ownership in `ARTIFACT_CONTRACTS.md` as each
  schema group lands; no new artifacts generated in 8.2.
- **Phase:** 8.2 (docs sync per slice).
- **Duplicate risk:** low — keep single source in ARTIFACT_CONTRACTS.md.

---

## Classification summary

| Candidate | Classification |
|---|---|
| ProspectCampaign | NEW THIN |
| CampaignTargetCriteria | NEW THIN |
| MarketPolicy | NEW THIN (pattern EXTEND of IntegrationPolicy) |
| DiscoverySourcePolicy | EXTEND EXISTING (IntegrationEndpoint/manifest) |
| BusinessContext | NEW THIN |
| SiteProfile | NEW THIN |
| BusinessFlowProfile | NEW THIN |
| InteractionActionClass | EXTEND EXISTING (capability-class vocabulary) |
| InteractionBoundary | EXTEND EXISTING (approval-requirement pattern) |
| SyntheticPersona | NEW THIN |
| SyntheticDataPolicy | NEW THIN |
| CoverageMap | EXTEND EXISTING (scenario matrix / audit plan) |
| CompanyIdentity | NEW THIN |
| DomainIdentity | NEW THIN (candidate OMIT / fold into CompanyIdentity) |
| ContactRecord | NEW THIN |
| ContactProvenance | EXTEND EXISTING (SourceReference) |
| ContactStatus | NEW THIN (enum) |
| FindingDisclosurePolicy | NEW THIN |
| DisclosureManifest | EXTEND EXISTING (ClientDeliveryManifest) |
| LeadScorecard | NEW THIN |
| ProspectPriority | NEW THIN (enum) |
| ProspectLifecycle | EXTEND EXISTING (WorkRunState pattern) |
| RecheckPolicy | NEW THIN |
| SiteFingerprint | NEW THIN |
| RetentionPolicy | NEW THIN |
| SuppressionPolicy | NEW THIN |
| StorageClass | NEW THIN (enum) |
| Capability/profile extensions | EXTEND EXISTING (YAML data) |
| Dashboard IA | DEFER |
| Planned artifact contracts | EXTEND EXISTING (docs) |

---

## Recommended smallest safe first implementation slice

**Slice 1 — Campaign definition contracts (schema/planning only).**

Coherent minimal group that maximizes reuse and touches **no** browser/network/MCP/contact/
PII surface. It defines *what a campaign is and which policies bound it*, nothing executable.

**In scope:**
- `ProspectCampaign`, `CampaignTargetCriteria`, `MarketPolicy`, `DiscoverySourcePolicy`.

**Explicitly out of slice 1:** contacts, identity, findings, disclosure, scoring, synthetic
data, site memory, dashboard — and all runtime.

**Exact files likely to change:**
- New: `core/schemas/prospect_campaign.py` (the 4 dataclasses, all `SchemaMixin`).
- New: `tests/test_prospect_campaign_schema.py`.
- Edit (docs sync): `docs/PHASE_CONTRACTS.md` (mark this slice implemented),
  `docs/REUSE_MAP_PHASE8.md` (record the reuse decisions taken),
  `docs/DOCS_MANIFEST.md` (if a new schema doc section is added),
  `docs/ARTIFACT_CONTRACTS.md` (only if a campaign artifact namespace is fixed),
  `docs/handoffs/CURRENT.md` (handoff update).
- Possibly: `core/schemas/__init__.py` export if the repo re-exports schemas.

**Exact tests:**
- `to_dict()`/`from_dict()` round-trip for each of the 4 classes.
- Nested round-trip (`ProspectCampaign` containing the 3 policy/criteria objects).
- Default-safe: no execution/`client_ready`/enabled-by-default fields; `DiscoverySourcePolicy`
  `enabled=False`, `read_only=True`; `MarketPolicy` `respect_robots=True`,
  `requires_human_approval=True`.
- Forward-compat: `from_dict` ignores unknown keys (relies on `SchemaMixin`).
- `schema_version` present on `ProspectCampaign`.

**Acceptance criteria:**
- ruff clean; full pytest green (baseline 3643 + new tests); docs audit `[PASS]`; agent
  readiness `[PASS]`; no runtime module, no new runnable command, no network/MCP/browser
  code; reuse decisions recorded in `REUSE_MAP_PHASE8.md` before merge.

**Docs needing synchronization:** `PHASE_CONTRACTS.md`, `REUSE_MAP_PHASE8.md`,
`DOCS_MANIFEST.md` (if schema doc added), `ARTIFACT_CONTRACTS.md` (only if namespace
fixed), `docs/handoffs/CURRENT.md`.

**Commit shape:** fits one independently reviewable commit
(`feat: Phase 8.2 slice 1 — Prospect campaign definition contracts`), with an **optional
hardening commit** adding `ProspectLifecycle` (`core/schemas/prospect_lifecycle.py` +
tests) built on the `WorkRunState` pattern.

**Do not implement this slice now** — it is the recommendation for the next authorized
Claude Code session, after the current docs branch is accepted.

# Schema Foundation — Guided QA Automation Workbench

**Version:** 5.1.0  
**Updated:** 2026-05-24  
**Phase:** 1B — Schema foundations (pure Python, no runtime behavior)

---

## Purpose

`core/schemas/` defines the domain model for every structured concept the workbench works with: inputs, blueprints, approvals, artifacts, test evidence, monitoring, and ops.

These are pure Python dataclasses. They have no side effects, no database, no external calls. They exist to:

1. Give every concept in the system a named, typed, serialisable shape
2. Make `to_dict()` / `from_dict()` round-trips explicit and tested
3. Provide a shared vocabulary for agents, state, reports, and future persistence layers
4. Prevent string-dict soup in agent code

---

## Base pattern

All schema classes inherit `SchemaMixin` from `core/schemas/base.py`:

```python
class SchemaMixin:
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)   # dataclasses.asdict — recursive

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> T:
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
```

Container schemas (those with `List[SomeRecord]` fields) override `from_dict` explicitly to reconstruct typed objects from raw dicts. This is intentional — no reflection magic, just clear per-class handling.

---

## Constants (`core/schemas/constants.py`)

Frozen sets for valid values used as field values across schemas:

| Constant | Purpose |
|---|---|
| `INPUT_TYPES` | Valid `input_type` values for `InputSource` |
| `RISK_LEVELS` | Risk level taxonomy (safe_analysis → client_delivery) |
| `PROJECT_TYPES` | Project type taxonomy (web_saas, ecommerce, …) |
| `ENVIRONMENT_TYPES` | local, staging, production, sandbox, unknown |
| `ACTION_STATUSES` | pending, approved, rejected, running, completed, failed, skipped |
| `ACCESS_LEVELS` | none, read_only, read_write, admin |
| `ARTIFACT_TYPES` | test_strategy, scaffold, report, evidence, … |
| `ASSISTANT_TYPES` | workflow entry points: prescreen, scaffold, full, … |
| `WORK_DOMAINS` | web_ui, api, mobile, performance, security, … |
| `TASK_TYPES` | prescreen, proposal, test_design, scaffold, … |
| `DELIVERABLE_TYPES` | proposal, test_plan, test_cases, report, … |

These constants are informational — schemas do not validate field values against them at construction time. Validation can be added in Phase 2 if needed.

---

## Schema modules

### Input / context

| Module | Classes | Description |
|---|---|---|
| `source_reference` | `SourceReference` | Origin of a work request (URL, platform, raw text) |
| `work_request` | `WorkRequest` | Normalised intake record with UUID, brief, platform, target URLs |
| `task_classification` | `TaskClassification` | Classification result: task type, project type, confidence, signals |
| `input_map` | `InputSource`, `InputMap` | Classified inputs for a project; explicit nested from_dict |

### Project / blueprint

| Module | Classes | Description |
|---|---|---|
| `project_blueprint` | `ProjectBlueprint` | Structured source-of-truth: type, stack, scope, risks |
| `delivery_plan` | `DeliveryItem`, `DeliveryPlan` | Planned deliverables with status; explicit nested from_dict |
| `quality_rubric` | `QualityCriterion`, `QualityRubric` | Scoring criteria with weights; explicit nested from_dict |

### Execution

| Module | Classes | Description |
|---|---|---|
| `automation_plan` | `AutomationAction`, `AutomationPlan` | Planned test actions with risk level and framework; explicit nested from_dict |
| `approval` | `ApprovalDecision`, `ApprovalHistory` | Per-action approval/rejection record; explicit nested from_dict |
| `tool_selection` | `ToolRecommendation`, `ToolSelection` | Tool recommendations with rationale; explicit nested from_dict |
| `artifact_manifest` | `ArtifactRecord`, `ArtifactManifest` | Registry of all generated artifacts; explicit nested from_dict |
| `run_context` | `RunContext` | Execution context: workflow, mode, flags, agents run |
| `safety` | `SafetyCheck`, `SafetyReport` | Per-rule safety evaluation with violation details; explicit nested from_dict |
| `execution_summary` | `EvidenceItem`, `ExecutionSummary` | Test run results with evidence items; explicit nested from_dict |
| `assistance` | `AssistanceRecord`, `AssistanceHistory` | AI assistance session log; explicit nested from_dict |

### Monitoring

| Module | Classes | Description |
|---|---|---|
| `activity_log` | `ActivityEvent`, `ActivityLog` | Ordered event timeline; explicit nested from_dict |
| `blocker` | `Blocker`, `BlockerRegister` | Open blockers with severity/status; explicit nested from_dict |
| `progress` | `ProgressItem`, `ProgressTracker` | Progress items with completion %; explicit nested from_dict |
| `self_assessment` | `SelfAssessmentFinding`, `SelfAssessment` | Automated quality findings; explicit nested from_dict |
| `project_status` | `ProjectStatus` | Phase, overall status, pending approvals, next action |

### Ops

| Module | Classes | Description |
|---|---|---|
| `cleanup` | `CleanupCandidate`, `CleanupReport` | Dry-run cleanup candidates (approved_for_deletion=False by default); explicit nested from_dict |
| `ai_resilience` | `AIProviderStatus`, `AIFallbackEvent`, `AIResilienceReport` | Provider health + fallback history; explicit nested from_dict |
| `admin_feedback` | `AdminNotification`, `AdminFeedbackCenter` | Admin notifications requiring attention; explicit nested from_dict |
| `media_evidence` | `MediaEvidenceItem`, `MediaEvidenceCollection` | Screenshots, traces, videos from test runs; explicit nested from_dict |
| `analytics` | `AnalyticsMetric`, `AnalyticsReport` | Aggregated project metrics; explicit nested from_dict |

---

## Safety defaults

| Default | Why |
|---|---|
| `CleanupReport.dry_run = True` | Cleanup never executes automatically |
| `CleanupCandidate.approved_for_deletion = False` | Explicit approval required per candidate |
| `SafetyReport.all_passed = True` | Fail-safe: only set to False on violation |
| `RunContext.approved = False` | Approval is opt-in, not assumed |
| `RunContext.mode = "mock"` | Real LLM mode must be explicitly requested |

---

## State integration — deferred to Phase 2

`QAFactoryState` (`core/state.py`) currently holds free-form dict fields for agent outputs. Schema objects can be stored as `to_dict()` snapshots and rehydrated via `from_dict()`. The wiring is not done yet.

See the `TODO (Phase 2)` comment in `core/state.py` for the list of fields planned for integration. The deferral keeps all 69 existing mock-mode tests passing without change.

---

## Testing

All schemas have round-trip tests in `tests/test_schema_foundations.py`. Coverage:
- Constants: 6 checks
- Every schema class: at minimum `from_dict` reconstruction + round-trip
- Container schemas: explicit test that nested dicts are reconstructed as typed objects
- Defaults: `dry_run`, `approved`, `mode`, `all_passed`, counter fields

Run: `python -m pytest tests/test_schema_foundations.py -v`

---

## Related documents

- [`APPROVAL_MODEL.md`](APPROVAL_MODEL.md) — risk levels used in `AutomationAction.risk_level` and `ApprovalDecision.risk_level`
- [`SAFETY_RULES.md`](SAFETY_RULES.md) — rules enforced by `SafetyCheck` / `SafetyReport`
- [`TOOLING_DECISIONS.md`](TOOLING_DECISIONS.md) — why pure dataclasses over Pydantic
- [`COMMANDS.md`](COMMANDS.md) — planned commands that will produce schema objects

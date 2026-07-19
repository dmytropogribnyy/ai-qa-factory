# v3.2.0 Combined Reuse Map (precedes new modules)

v3.2 **extends** the v3.1 foundation. One dashboard app, one orchestration lifecycle, one Scout, one
safety-gated core, one evidence/state store. This map classifies each area REUSE / EXTEND / ADAPT /
NEW so no second system is introduced.

## Reuse / extend (no new system)

| Area | Verdict | Where |
|---|---|---|
| Dashboard server + handler + guards + CSP | REUSE/EXTEND | `core/scout/dashboard.py` (single app) |
| Read model + AllowedAction + ProjectDetail | REUSE/EXTEND | `core/dashboard/` |
| Lifecycle + persistence + integrity + delivery | REUSE/EXTEND | `core/orchestration/work_execution.py`, `work_state_manager.py`, `work_run_state.py` |
| Project id contract | EXTEND | `core/orchestration/providers.validate_project_id` (add Windows reserved names, trailing dot/space, OS-independent) |
| Tool readiness + internal bindings | EXTEND | `core/orchestration/tool_broker.py`, `internal_bindings.py` |
| Design tokens / layout | EXTEND | `_TOKENS_CSS` / `_page` in `core/scout/dashboard.py` → Pro Dark semantic vars + theme toggle |
| Scout service + campaign guard + controls | REUSE | `core/scout/service.py`, `campaign_start.py` |
| Validation evidence + redaction | EXTEND | `core/orchestration/operator_executor.py` (broaden redaction, per-field honesty) |
| Genuine A–D acceptance | REUSE/EXTEND | `tests/test_v3_genuine_execution_*`, add flaky + read-only DB |
| CI (4 jobs) + zero-skip asserter + screenshots | EXTEND | `.github/workflows/ci.yml`, `tools/assert_no_skips.py`, `tests/test_v31_screenshots.py` |
| Windows ownership-safe stop | REUSE | `scripts/stop-local.ps1`, `tests/test_v3_windows_stop_ownership.py` |

## Genuinely NEW (thin, over the existing core)

| Module | Purpose | Notes |
|---|---|---|
| `core/orchestration/service_capability.py` + `SERVICE_CAPABILITY_MATRIX.json` | Versioned advertised-service contract with honest readiness | data + read model; surfaced via Settings/Tools, no cluttered page |
| `core/orchestration/access_bootstrap.py` | Local Access & Identity readiness inspector (no secrets) | reuses ToolBroker; extended readiness states |
| `core/orchestration/claude_worker.py` | Pluggable bounded Claude Code execution adapter | fixture-tested; live run operator-gated + honestly reported; never `dangerously-skip-permissions` |

## Hard prohibitions honored

No second dashboard/backend/database/project-store/state-store/evidence-store/orchestration/Scout; no
arbitrary HTTP command/argv; no CAPTCHA/auth/paywall bypass, stealth, proxy rotation; no email/form/
deploy/purchase/production change; no secret committed; Upwork stays manual (no API); main + tags
immutable; nothing merged or tagged.

## Honesty ladder (labels used everywhere)

deterministic-core · fixture-verified · runtime-verified · live-verified · client-authorized-external
· unavailable-connector · needs-operator. A catalog entry / installed package / mock / fixture /
generated-but-unrun config is never presented as a live capability.

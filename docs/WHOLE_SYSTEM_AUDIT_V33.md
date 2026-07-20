# Whole-System Audit Matrix — AI QA Factory v3.3

Honest end-to-end classification. **"Complete" means traced end-to-end + tested**, not "code
exists". Branch `feature/v3.3-scout-autonomy`. Legend: **CP** complete & proven (deterministic +
CI) · **FX** fixture-verified only · **LIVE** requires operator live acceptance · **DEF** honestly
deferred.

| Capability | Status | Module | Dashboard / surface | Test | Remaining |
|---|---|---|---|---|---|
| Session/production presets + finite budgets | CP | `presets.py` | `/scout/new` | `test_v33_presets_budget` | — |
| 7 counters + actionable/consec-failure stop + stop_reason | CP | `run_counters.py`, `discovery/engine.py` | `/scout/progress` | `test_v33_run_counters` | — |
| A/B/C + commercial/QA/evidence/safety/combined scores | CP | `priority.py`, `scout_brain.py` | `/scout/target` | `test_v33_priority_country`, `_scout_brain` | — |
| Country confidence (Verified/Probable/Unverified) | CP | `country_confidence.py` | target detail | `test_v33_priority_country` | — |
| Adaptive Scout Brain (understanding + replan) | CP | `scout_brain.py` | target decision trail | `test_v33_scout_brain` | — |
| Adaptive allocation (ceilings≠outcomes≠depth) + planner | CP | `adaptive.py`, `target_planner.py` | progress decisions | `test_v33_adaptive` | — |
| Per-vertical QA + fail-closed public-action policy | CP | `verticals.py`, `public_action_policy.py` | — | `test_v33_verticals` | live browser flows = LIVE |
| Persisted 11-state run-control + pause/resume/recovery/no-overlap | CP | `run_control.py` | progress controls | `test_v33_run_control` | — |
| Challenge resilience (one CAPTCHA ≠ campaign stop) | CP | `challenge_resilience.py` (+ `orchestration/challenge_policy.py`) | counters/target | `test_v33_challenge_resilience` | wire into live engine loop = LIVE |
| Retry / self-recovery (bounded, classified) | CP | `retry_policy.py` | — | `test_v33_retry_policy` | wire into live engine loop = LIVE |
| Attention + notification policy (Level 0-3, dedup, off-by-default) | CP | `attention.py` | Needs-attention (data) | `test_v33_attention` | Dashboard attention panel = FX |
| Evidence escalation + video qualification | CP | `evidence_policy.py` | finding detail (labels) | `test_v33_evidence_policy` | live video capture = DEF |
| Load/stress refusal (single-user only) | CP | `load_test_policy.py` | — | `test_v33_evidence_policy` | authorized load mode = DEF |
| Mode-3 test-account approval gate | CP | `test_account.py` | — | `test_v33_test_account_repro` | live account creation = DEF |
| Bug-reproduction structured context | CP | `repro_context.py` | finding detail | `test_v33_test_account_repro` | live Reproduce/Recheck runtime = DEF |
| Readiness preflight (real probes) | CP | `preflight.py` | `/scout/new` preflight | `test_v33_preflight` | — |
| Campaign orchestration service | CP | `campaign_service.py` | all `/scout/*` | `test_v33_campaign_service` | — |
| Dashboard form/preflight/progress/history/target/controls | CP | `dashboard.py` | `/scout/new|progress|history|target` | `test_v33_dashboard_scout` | screenshots = LIVE |
| Scheduling modes (Manual/Daily/Weekdays/Weekly/Once) | CP | `tools/scout_schedule.py` | schedule status = FX | `test_v33_schedule_modes` | live Task Scheduler run = LIVE |
| Cross-campaign memory (skip/rescan/resume) | CP | `discovery/analyzed_registry.py` | `/scout/history` | `test_v33_analyzed_registry` | — |
| Observer API (read-only) + AI Review Bundle | CP | `observer_api.py` | export action | `test_v33_observer_api` | — |
| Observer MCP adapter (read-only, 19 tools) | CP | `integrations/mcp/observer_handlers.py` | `--list-tools` | `test_v33_mcp_observer` | live stdio needs `pip install mcp`; ChatGPT connect = operator step |
| Seedless discovery (Tavily) + engine | CP | `discovery/*` | — | `test_v33_live_wiring` (mock transport) | one live Tavily run = LIVE |
| **One Dashboard-driven live acceptance (real US/DE sites)** | **LIVE** | end-to-end | `/scout/new` → Run | — | operator-run; runbook `LIVE_SCOUT_ACCEPTANCE_V33.md` |

## Honestly deferred (DEF) — not blockers for a first useful release

- Live short-video **recording** runtime (policy + qualification + repro-context done).
- Live **Mode-3 account creation** execution (approval gate + constraints done).
- **MCP control tools** (pause/resume/stop/recheck/reproduce/record-video) — read-only shipped;
  control tools remain disabled/unimplemented by design this increment.
- **Authorized load/stress** testing mode (public refusal done).
- Additional discovery providers.

For each DEF item: no misleading "working" control is exposed; status is truthful; future
acceptance is defined above.

## Rationality/efficiency notes

- No duplicate engine/store/registry/scheduler/Dashboard introduced — all new modules are thin
  layers over existing ones.
- Observer/`get_updates_since` corrected from a whole-snapshot hash to a true event cursor; AI
  Review Bundle corrected to campaign-scoped + relative paths (no cross-campaign leak, no absolute
  path exposure).
- Fixed a real intermittent failure (`run_control._is_orphaned` boundary) that had reached `main`.

## Merge readiness

**Merge-ready to `main`** once this branch's CI is 4/4 green. This branch also carries the
`_is_orphaned` fix that makes `main` (currently red on an intermittent `windows-smoke`) green again.
The single remaining **operator** step before declaring the product live-ready is the one
Dashboard-driven live acceptance (LIVE row above) — it is not fabricated here.

# Checkpoint — /target confidence label + repro hint (ordered by qa_value_score)

Branch `feat/scout-target-confidence` @ `ba8f3d2778c5b8d18b3c9bfacb25fbd96cd28614` (base main `eff733c`).
Thread `pkt-20260722T120017Z-e2d07d26`. Proposal reviewed (RECOMMENDATION) + ACKed.

## What changed (2 source files + 1 test file)
- `core/scout/campaign_service.py`: new module-level `_project_target_finding(f)` whitelist
  projection now carries `confidence` + `reproduction_steps` to the `/target` read-model; wired
  into `target_detail`'s return (was dropping both).
- `core/scout/dashboard.py`: pure, testable helpers `_collapse_ws` / `_norm_steps` /
  `_confidence_label` / `_repro_hint` / `_finding_qa_value` / `_problems_table_html`, wired into
  `_scout_target_page` (replaces the old inline, unsorted table). New columns: **Confidence** and
  **Repro hint**. Rows ordered by `qa_value_score` desc (stable → equal scores keep input order),
  reusing the canonical `core.scout.priority.qa_value_score` (no second source of truth; lazy import,
  no cycle). Every dynamic cell is newline-collapsed then HTML-escaped; absent
  confidence/repro/type → neutral placeholder `—` (never invented). Multi-step findings keep the
  full path as an **escaped hover `title`** on the repro cell (bounded one-line cell + full access).

## Reviewer refinements addressed (all 7)
1. **Page-path wiring test** — `test_target_page_renders_confidence_and_repro_end_to_end` seeds a
   registry entry + brain decision + run store, then `GET /scout/target?domain=acme.com` over
   loopback HTTP proves the real `target_detail` projection AND `_scout_target_page` render the new
   table (catches missed wiring, not just isolated helpers).
2. **Defensive `reproduction_steps`** — `_norm_steps` handles missing/None/empty/scalar-legacy;
   a scalar string is ONE step (never char-by-char joined). Test:
   `test_scalar_legacy_reproduction_steps_not_char_joined`.
3. **Bounded repro presentation** — cell shows the first concrete step; full path preserved as an
   escaped hover `title` (muted class does not itself cap content).
4. **Escaping of newly-exposed fields** — `test_malicious_title_and_repro_step_are_escaped` (a
   `<script>` in title AND in a step) and `test_legacy_confidence_value_is_escaped` (a legacy dict
   `confidence` = `<b>"high"</b>` → escaped).
5. **Cell-specific newline assertion** — `test_newline_in_step_is_collapsed_to_one_line` asserts the
   collapsed value present and the un-collapsed form absent (not a blanket table-wide newline check).
6. **Evidence markup preserved** — evidence refs are collapsed + escaped per-ref then joined (no
   wholesale-escaping of a built link; current surface has no link markup).
7. **Ruff on test + both sources + regression tests run** — see evidence below.

## Evidence (controller venv, cwd = worktree)
- `ruff check core/scout/campaign_service.py core/scout/dashboard.py tests/test_target_findings_render.py`
  → **All checks passed!**
- `pytest tests/test_target_findings_render.py -q` → **12 passed in 0.84s**
- `pytest tests/test_dashboard_bundle1_integrity.py tests/test_v33_campaign_service.py -q`
  (existing target/dashboard regression) → **25 passed in 14.97s**

Tests exercise the real `ScoutFinding` field shapes via `ScoutFinding(...).to_dict()` throughout.

## Trusted gate manifest (recorded for this exact SHA)
A trusted LOCAL-workflow gate manifest is recorded for `ba8f3d2` under
`_review_relay/collab_gate/` (written by the local writer, never the remote model):
`present=True, success=True — CI success (local-trusted-gate-2026-07-22); tests 25/25 ok=True;
audits ok=True`. Re-confirmed this session: `ruff check .` clean, `tools/docs_audit.py` [PASS],
`tools/agent_readiness_audit.py` [PASS], the 12 focused tests + scout/dashboard regression green.
No cloud CI run — this is an unpushed isolated worktree and external contact is out of scope for
this packet; the deterministic local gate is the trusted evidence. Branch head is unchanged at
`ba8f3d2` (re-checkpoint only supplies the now-present trusted manifest; no code moved).

## Not changed / out of scope
No `ScoutFinding` schema change; no new persisted field; no change to verification/sanitization or
other `/target` cards; import graph stays acyclic (lazy scorer import).

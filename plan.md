# Plan — /target finding confidence + repro hint, ordered by qa_value_score

Branch: `feat/scout-target-confidence` (worktree, based on main `eff733c`).
Thread: `pkt-20260722T120017Z-e2d07d26`.

## Goal (acceptance)
On the Scout `/target` page, each finding in the **Problems found** table renders (a) its
**confidence label** and (b) a **one-line repro hint**, ordered by **qa_value_score desc**.
Dynamic finding text is HTML-escaped **and** newline-collapsed. Absent confidence/repro show a
neutral placeholder (`—`, the placeholder already used across this page) — never invented.

## Findings from code reading
- `core/scout/dashboard.py::_scout_target_page` builds the "Problems found" table (lines ~1984-1998).
  It iterates `findings` in arrival order (comment claims "highest-severity first" but there is **no
  sort**). Columns today: Severity, Type, Issue, Business impact, Evidence. `title`/`business_impact`
  are `_esc`-escaped but **not** newline-collapsed.
- `core/scout/campaign_service.py::target_detail` (lines ~327-333) projects each finding to a 6-field
  whitelist and **drops `confidence` and `reproduction_steps`**. Those must be added to the
  projection or the page can never show them.
- `ScoutFinding` (core/scout/findings.py) has real fields `confidence` (low|medium|high) and
  `reproduction_steps: List[str]`. `to_dict()` includes both. Validation forbids an empty
  `confidence` on the dataclass, so "absent" is only reachable via a projected/legacy dict where the
  key is missing/None — which is exactly the realistic case.
- `core/scout/priority.py::qa_value_score(findings)` = Σ severity-weight (`high40/med20/low8/info2`) +10
  evidence bonus for evidence-backed med/high, capped 100. It is a **list aggregator**, not a
  per-finding field.

## Change (minimal, 2 source files + 1 test file)

### 1. `core/scout/campaign_service.py`
Extract the finding projection into a small pure module-level helper
`_project_target_finding(f) -> dict` and use it in `target_detail`'s return. Add two keys to it:
`"confidence": f.get("confidence")` and `"reproduction_steps": f.get("reproduction_steps", [])`.
(Pure helper → unit-testable without a RunStore.)

### 2. `core/scout/dashboard.py`
Add module-level, pure, testable helpers near `_esc`:
- `_collapse_ws(s)` → `" ".join(str(s or "").split())` (collapses newlines/tabs/space runs, trims).
- `_finding_qa_value(f)` → `qa_value_score([f])` (per-finding contribution; reuses the scorer).
- `_confidence_label(f)` → collapsed `confidence` or `—` (never invented).
- `_repro_hint(f)` → reproduction_steps, each newline-collapsed, non-empty joined with ` → `; `—`
  when there are no steps (never invented).
- `_problems_table_html(findings)` → sorts findings by `_finding_qa_value` **desc** (stable, so ties
  keep input order), renders the table with columns **Severity | Confidence | Type | Issue |
  Business impact | Repro hint | Evidence**; every dynamic cell is `_esc(_collapse_ws(...))` with the
  `—` placeholder for empties; returns the existing "No verified problem items…" empty state when the
  list is empty.

Rewire `_scout_target_page` to call `_problems_table_html(findings)` (keeps the `scrollx` wrapper and
the card). Net: sorting + two new columns + uniform escape/collapse, no behavior removed.

### 3. Tests — `tests/test_target_findings_render.py`
Exercise the **real ScoutFinding field shapes** (build `ScoutFinding(...).to_dict()`):
- **ordering**: high/medium/low + evidence produce qa_value desc order in the HTML; two equal-score
  findings keep input order (stable-tie assertion).
- **rendering**: confidence label and a repro hint (first step text) appear in the output; a `<script>`
  in a title is escaped (`&lt;script&gt;`); a multi-line reproduction step renders on one line
  (no raw `\n`, steps joined by ` → `).
- **absent-field cases** (projected/legacy dicts missing confidence/reproduction_steps, and empty
  strings/lists): both render the `—` placeholder, never invented text.
- **projection**: `campaign_service._project_target_finding(ScoutFinding(...).to_dict())` carries
  `confidence` and `reproduction_steps` through.

Run: `.venv/Scripts/python.exe -m pytest tests/test_target_findings_render.py -q` (+ `ruff check` on
the two changed files) and report real output before the checkpoint.

## Design choices for reviewer
- **Repro hint = steps joined with ` → ` (collapsed), not just the first step.** A path is a more
  useful one-line hint than a single step; capped only by the muted table cell. Open to "first step
  only" if preferred.
- **Confidence rendered as a plain muted label cell** (not a colored badge) — it is a confidence
  *label*, and avoids inventing a badge-kind mapping. Open to a badge if preferred.
- **Placeholder = `—`** to match every other absent field on this page (`category`, `stop_boundary`,
  etc.), for visual consistency.
- Ordering reuses `priority.qa_value_score` rather than a new scoring rule — no second source of truth.

## Out of scope
No schema change to `ScoutFinding`; no new persisted field; no change to verification/sanitization;
no change to other cards on the page.

# Scout Detail Seam Inspection — design

Date: 2026-07-26
Baseline: `main` @ `9d5c6af`
Surfaces: `/scout/run`, `/scout/target`, `/api/scout/target`, `/scout` (Manual URL Scan)

## 1. Why a seam inspection, not a surface audit

The Scout detail surfaces have already been hardened by several independently merged slices:

| PR | commit | scope |
| --- | --- | --- |
| #31 | `759150d` | target detail domain scoping (no cross-target evidence) |
| #34 | `637490b` | Run Results golden path + manual-action truthfulness |
| #35 | `6cd61b6` | evidence usability + operator UI truthfulness |
| #37 | `d054c30` | coverage profile UI wiring + honest readout |
| #41/#42 | `8cc5ebb`/`c0100d1` | bounded evidence bundles, latest-campaign evidence |
| #45 | `d827faf` | operator UX, manual challenges, client evidence |

Each slice is internally consistent. The remaining risk is the **seam between them**: one operator
question ("how many problems does this target have, and did the analysis finish?") answered by two
different code paths that no single slice owned. This is the same defect shape as PR #49, where an
Overview tile disagreed with the view it linked to.

## 2. Source-of-truth map

The same per-target facts are projected by four UI consumers plus one read API from two sources:

| Render site | Source | Reference |
| --- | --- | --- |
| `/scout/run` — Actionable / Informational | compact prospect state | `core/scout/dashboard.py:3398` |
| `/scout` Manual URL Scan — Actionable | compact prospect state | `core/scout/dashboard.py:2069` |
| legacy run table | compact prospect state | `core/scout/dashboard.py:1484` |
| `/scout/target` — Actionable findings / Informational notes / Problem items | `findings.json` artifact | `core/scout/dashboard.py:3081-3084`, `core/scout/campaign_service.py:537` |
| `/api/scout/target` — `findings[]` | `findings.json` artifact (ungated) | `core/scout/dashboard.py:287` |

The compact counters are a denormalized cache of the artifact. The invariant that binds them is
implicit — it holds only because two writes sit next to each other in the engine.

## 3. The reachable divergence

`core/scout/engine.py`:

- line 253 — `findings.json` is written;
- lines 260/264 — reproduction video and coverage are written;
- lines 267-275 — the compact state gets `status: DONE` together with `verified_findings` /
  `verified_defects`.

Between 253 and 267 the prospect holds confirmed findings on disk while its compact state still
says `PENDING`.

**How that window is actually reachable.** Not through ordinary Stop/Cancel: control is cooperative
(`engine.py:579`), and any ordinary failure inside the window is caught at `engine.py:151-152` and
persisted as `FAILED`. That handler is `except Exception`, so it does **not** catch
`KeyboardInterrupt` or `SystemExit`, which derive from `BaseException`. The genuine sources of
`PENDING` + `findings.json` are therefore: hard process termination, `KeyboardInterrupt` /
`SystemExit`, an external hard timeout, or power loss.

**What each surface does with that state** (behaviour on `9d5c6af`, to be confirmed on the stand):

| Surface | Expected behaviour |
| --- | --- |
| `/scout/run` | `0 / 0`, "Not analyzed" — reads the compact counters |
| `/scout/target?run=<run>&domain=delta` | incomplete screen, 0 confirmed findings — gated at `dashboard.py:2655` |
| `/api/scout/target?run=<run>&domain=delta` | **returns N findings — candidate defect**, the route is ungated |
| `/scout/target?domain=delta` (unpinned) | may render N findings: the gate at 2655 requires a non-empty `run` |

The UI gate at `dashboard.py:2655` catches any non-empty status other than DONE. The read model does
not: `campaign_service.py:500` treats only `MANUAL_ACTION_REQUIRED` and `FAILED` as incomplete, so
`PENDING` loads the artifact. The leak is in the read model and reaches the operator through the API
route and the unpinned page.

## 4. Stand and seed

Local stand on `127.0.0.1:8899` with a dedicated temporary output directory. Never port 8765, never
the real `outputs/`.

One primary run containing deliberately heterogeneous targets:

| Target | State | What it proves |
| --- | --- | --- |
| `alpha` | DONE, 5 verified (3 defects + 2 info), coverage written | counts agree across all four render sites |
| `beta` | MANUAL_ACTION_REQUIRED with `manual_action.json` | fail-closed incomplete view is correct |
| `gamma` | FAILED | same, without a manual-action record |
| `delta` | PENDING with `findings.json` already written | the four-way divergence above |
| `epsilon` | DONE from a legacy run, no `coverage` key | absent data renders as unavailable, not `0 pages` |
| `theta` | DONE with 0 findings, coverage written | an honestly clean result must not read as "not analyzed" |
| `eta` | SKIPPED, no findings and no challenge record | the SKIPPED half of the §7 UX check; without it that candidate stays half-tested |

Plus:

- `?run=<run>&domain=zeta` for a domain absent from the run — this is what produces
  `prospect_not_found`; without `run=` the same request is merely "No record", a different state;
- a second run over `alpha` with **different counts and distinguishable evidence**, so that
  run pinning (`?run=`) versus registry resolution is actually falsifiable;
- for the unpinned `delta` check, a real brain/replay/registry resolution must be seeded — a plain
  `PENDING` manual run is not registered in the registry, so without this the unpinned case is
  vacuous;
- one archived run for the banner and the Archive/Restore controls.

## 5. Invariants

Stated by status, so the check does not depend on which screen happens to render it:

1. **DONE** — the compact counters equal the artifact rows exactly: `verified_defects` equals the
   number of `Defect` rows, `verified_findings - verified_defects` equals the number of
   `Informational` rows.
2. **Any non-empty status other than DONE** — no UI surface and no read API presents artifact rows as
   confirmed findings or a finding reproduction. An unrecognized future status is included: unknown
   must fail closed, not fall through to artifact loading.
3. **Missing/empty legacy status only** — the existing backward-compatible artifact-loading behaviour
   is preserved deliberately; this is not a defect. It is the sole exemption from invariant 2, and no
   fix may collapse it into the statuses covered there.

   These invariants are acceptance criteria, not an implementation. Where a confirmed divergence gets
   fixed — in the read model, so every surface inherits it, or per-surface — is decided in the
   implementation plan against the evidence, not assumed here.
4. **For every DONE target**, one mapping holds across every surface that projects it:
   `Actionable = count(severity != "info")`, `Informational = count(severity == "info")`,
   `Total = Actionable + Informational = len(API findings[])`. Every linked destination must preserve
   this mapping — the run row's Actionable/Informational (compact counters) against the card's
   Actionable findings / Informational notes (artifact) is a direct number-to-number comparison, not
   an approximate one.
5. Every action on both pages actually executes in a live Chromium: Details, Archive/Restore run,
   checkboxes and bulk actions, raw JSON links, rescan/replay.
6. Missing data stays honest: no `coverage` key renders as unavailable; `prospect_not_found` renders
   the warning banner and never another target's evidence.

## 6. Explicitly not defects

- Zero findings on the card for `MANUAL_ACTION_REQUIRED` / `FAILED` — deliberate fail-closed
  behaviour (`campaign_service.py:535`).
- "Problem items (5)" alongside "Actionable 3" — different quantities under different labels. The
  card already carries an explicit Actionable findings / Informational notes summary
  (`dashboard.py:3081-3084`) and a per-row `Kind` column, so the two readings are reconcilable on
  screen. Not a defect; only their *arithmetic* is checked, under invariant 4.

## 7. UX candidates to confirm in Chromium

- A pinned `PENDING` (or `SKIPPED`) target currently lands on the manual-action screen
  (`dashboard.py:3228`), whose text is written for a challenge: "Needs your help", "The browser could
  not complete this target automatically", and an **Open manual check** button. For a target that was
  interrupted rather than blocked, that story is wrong and the challenge action has no session to
  bind to. Confirm whether the button is appropriate and whether it does anything.

## 8. Deterministic engine test

Independently of the stand: a two-prospect run where the first prospect completes and persists full
state, and the second is interrupted inside the 253-267 window.

The fault injector must call the real `save_prospect_artifact(..., "findings.json", ...)` first and
only then raise `KeyboardInterrupt` — otherwise the test may abort *before* the write and prove
nothing about the state it claims to reproduce.

After reopening the store, assert explicitly: the first prospect is `DONE` with counters matching its
artifact; the second is `PENDING`; the second's `findings.json` exists on disk; the run itself is
left unfinished. Then assert every operator surface stays fail-closed for the second prospect —
including `/api/scout/target`, which is the one that currently would not.

## 9. Deliverables and gates

- An evidence-backed report of confirmed divergences (a screen alone is not evidence; the paired
  numbers are).
- Fixes only for confirmed divergences.
- One test per fix, each verified red against the unfixed code, plus the generalized
  number-equals-destination test for Scout rows.
- `ruff` + affected tests + the Scout subset while iterating; the full suite once before merge.
- PR with an exact-head checkpoint through the relay.

## 10. Out of scope

Results/Company and Collaboration surfaces (a later slice), the Paid Full Website Audit, and the
Tavily live `/usage` UI.

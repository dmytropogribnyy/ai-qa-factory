# Scout Brain — Canonical Product Concept (v3.3)

> **CONTROLLING CONTRACT.** Scout is an **autonomous, adaptive, evidence-driven QA and
> commercial-opportunity agent operating within strict deterministic safety boundaries.** Do NOT
> simplify Scout back into a static crawler, a fixed QA checklist, a preset of Playwright scripts,
> a fixed discovered-to-tested ratio, a noise-maximizing scanner, or an opaque LLM agent. Any
> future change must preserve the behaviors below and the tests that enforce them.

## What Scout is

The operator sets **goals + boundaries** (targeting, commercial priorities, QA interests,
interaction permissions, hard ceilings, safety). Scout autonomously decides the **detailed
investigation path** per target: what it is, how it makes money, its critical public journeys, an
individual test plan, adapting as evidence appears, safely verifying the most promising problems,
collecting evidence, and ranking the strongest evidence-backed commercial opportunities.

The operator instruction is *"find commercially promising sites in these markets, understand their
critical flows, safely investigate the most meaningful risks, return the strongest evidence-backed
opportunities"* — **not** *"run exactly these 25 checks on every domain."*

## Enforcing modules (the brain is code, not a prompt)

| Concept section | Enforced by | Tests |
|---|---|---|
| Understand the target (Phase A): archetype / business model / critical journeys + confidence + evidence | `core/scout/scout_brain.py` `understand_target()` | `tests/test_v33_scout_brain.py` |
| Individual Target Test Plan (Phase C): select/skip/why/depth/interaction/stop/evidence | `core/scout/target_planner.py` | `tests/test_v33_adaptive.py` |
| Adaptive resource allocation (§6): ceilings ≠ outcomes ≠ per-target depth; no fixed ratio | `core/scout/adaptive.py` | `tests/test_v33_adaptive.py` |
| Adapt on evidence (Phase E/F): deepen/stop/escalate/block when evidence appears | `core/scout/scout_brain.py` `replan_on_evidence()` | `tests/test_v33_scout_brain.py` |
| Value over raw issue count (§4) | `scout_brain.combined_opportunity_score()` + `priority.qa_value_score()` | `tests/test_v33_scout_brain.py` |
| Commercial vs QA intelligence separate (§5): Commercial / QA / Evidence-confidence / Safety-confidence / Combined | `core/scout/priority.py` + `scout_brain.py` | `tests/test_v33_priority_country.py`, `tests/test_v33_scout_brain.py` |
| Safety is in the brain (§7): reasoning never overrides policy | `core/scout/public_action_policy.py`, `core/scout/verticals.py` (fail-closed) | `tests/test_v33_verticals.py` |
| Performance only, no load/stress on third parties (§8) | `core/scout/load_test_policy.py` (separate authorized mode) | `tests/test_v33_scout_brain.py` |
| Evidence escalation levels 1–4 (§9); video only when justified | `core/scout/evidence_policy.py` | `tests/test_v33_evidence_policy.py` |
| Operational memory (§10): skip processed, rescan policy, resume without repeat | `core/scout/discovery/analyzed_registry.py`, `core/scout/run_control.py` | `tests/test_v33_analyzed_registry.py`, `tests/test_v33_run_control.py` |
| Dashboard exposes the decisions (§11/12) | `core/scout/dashboard.py` target-detail + progress + history | `tests/test_v33_dashboard_*` |

## Non-negotiable behaviors (acceptance criteria — §15)

The concept is implemented ONLY when controlled tests show Scout:

1. builds **different plans** for materially different archetypes;
2. chooses **different depths** for different commercial/QA signals;
3. **changes its plan** after new evidence appears;
4. **stops** spending on weak targets;
5. **deepens** for strong, safe opportunities;
6. respects **all budgets and safety boundaries**;
7. **records why** every important decision was made;
8. preserves enough context for **recheck/reproduction**;
9. **exposes the decision trail** in the Dashboard;
10. honestly marks **uncertainty / blocked / unavailable reasoning**;
11. can **resume without repeating** completed work;
12. does not depend on **fixed discovered-to-tested ratios**;
13. does not use a **universal static checklist**;
14. does not perform **unsupported browser actions**;
15. **prioritizes useful commercial findings over raw issue count.**

## Architectural expectation (§13)

Scout's brain is a **bounded, explainable decision system**, not one giant prompt: deterministic
policy gates + persisted schemas + explicit scoring + bounded archetype classification + plan
generation + adaptive decision rules + controlled browser primitives + evidence-based escalation,
with optional model reasoning **only where it adds value**. The reasoning layer produces structured
decisions/plans that are validated → policy-checked → budget-checked → translated into supported
browser primitives → logged → persisted → explainable. **Unknown/unsupported actions are rejected,
not improvised.** When model/provider reasoning is unavailable, Scout degrades safely: deterministic
fallback classification, reduced depth, honest confidence — it never silently pretends full adaptive
reasoning occurred (`understand_target()` reports `reasoning_source`).

## Safety (§7, §8) — never autonomous

Never complete a purchase / submit an order / pay / reserve / confirm a booking / submit a
contact-lead form / send a message / call / submit an application / create a production account /
accept legal terms / bypass auth, CAPTCHA, anti-bot, access restrictions or rate limits / run real
load/stress against arbitrary third-party sites. Reversible actions: capture pre-state → one bounded
action → capture changed state → clean up → verify cleanup; if cleanup is unproven, mark the target
unclean and non-client-safe. **When uncertain, stop — an honest blocked result is not a failure.**

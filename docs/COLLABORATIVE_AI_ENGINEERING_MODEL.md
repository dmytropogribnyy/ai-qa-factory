# Collaborative AI Engineering Model

Status: canonical operating model for the Claude Code + GPT collaboration layer.

## 1. Purpose

This model exists to accelerate delivery of a powerful, truthful, commercially useful AI QA Factory,
Prospect Scout, and Operator Dashboard. The collaboration infrastructure is a means to that end, not a
new product competing with the product.

Primary outcome:

- Claude Code and GPT combine complementary strengths;
- important decisions are challenged before implementation;
- implementation is verified against objective evidence;
- the owner is interrupted only for genuine business, money, access, outreach, delivery, or merge decisions;
- the remaining Scout/Dashboard work is finished faster, with fewer regressions and less rework.

## 2. Operating roles

### Owner

Owns product intent, business priorities, external permissions, budget exceptions, outreach, client actions,
release acceptance, and merge authorization.

### GPT — Product Architect, Red Team, Independent Reviewer

GPT is responsible for:

- turning business goals into product contracts and acceptance criteria;
- proposing architecture and simpler alternatives;
- checking product truthfulness across Dashboard, APIs, Observer, CI, evidence, and documentation;
- identifying scope creep, hidden contradictions, false confidence, and unsafe assumptions;
- independently reviewing exact Git diffs and exact head SHAs;
- issuing COMMENT / GO / NO-GO decisions for the reviewed SHA;
- never authorizing merge automatically.

### Claude Code — Local Principal Engineer

Claude Code is responsible for:

- reading the real local repository and runtime context;
- validating whether architectural proposals fit the existing implementation;
- proposing simpler or safer alternatives when repository evidence contradicts an initial idea;
- implementing changes in the active feature branch;
- running targeted tests, local applications, diagnostics, and live acceptance;
- producing an evidence-backed checkpoint;
- fixing blockers or challenging a review finding with concrete evidence.

### Deterministic Judge

Neither model is the source of truth about whether the system works. Truth comes from:

- exact head SHA and Git diff;
- CI status and test output;
- Observer and canonical persisted state;
- Dashboard/API responses;
- browser and platform acceptance;
- evidence manifests and integrity hashes;
- cost/budget ledgers;
- actual Scout funnel and commercial outcome metrics.

## 3. Core principles

1. **One writer, two thinkers.** Claude Code is the primary writer on the active implementation branch.
   GPT is read-only architect/reviewer for that branch unless a separate owner-approved branch is used.
2. **Evidence over rhetoric.** Every important claim must point to a SHA, command result, persisted record,
   API response, screenshot, trace, or explicitly marked assumption.
3. **Independent thought before convergence.** For high-risk decisions, Claude and GPT should form initial
   views independently before reading the other's final recommendation.
4. **Exact-SHA decisions.** A decision applies only to the checkpoint head SHA. A changed SHA requires a
   new checkpoint. Old GO must never be reused.
5. **GO is not merge authorization.** Every GO records `merge_authorized=false`. Only the owner authorizes merge.
6. **No duplicate product engines.** Reuse existing state, Observer, orchestration, evidence, Scout, and Dashboard
   components. Collaboration tooling must not create a second business data model.
7. **Timeboxed disagreement.** Maximum two substantive critique rounds. Then run an experiment, choose a
   reversible option, or escalate a concise decision to the owner.
8. **No infrastructure theatre.** Do not expand collaboration infrastructure unless it removes a real bottleneck
   in finishing Scout, Dashboard, QA execution, evidence, delivery, or commercial learning.

## 4. Collaboration message types

The base relay supports checkpoint, decision, and acknowledgement. The target collaboration layer adds:

- `PROPOSAL` — a concrete design or execution option;
- `CRITIQUE` — weaknesses, risks, counterexamples, and alternatives;
- `QUESTION` — one bounded uncertainty that blocks progress;
- `RESPONSE` — a direct evidence-backed answer;
- `RECOMMENDATION` — preferred option and why;
- `EVIDENCE` — commands, outputs, hashes, screenshots, metrics, or Observer data;
- `CHECKPOINT` — implementation review request bound to exact head SHA;
- `DECISION` — COMMENT / GO / NO-GO for exact head SHA;
- `ACKNOWLEDGEMENT` — worker confirms receipt and intended next action;
- `ESCALATION_TO_OWNER` — short decision packet containing only the unresolved business choice.

Each message should include only what is needed:

- thread id and message type;
- goal or bounded question;
- exact head SHA when code is involved;
- evidence references;
- assumptions and unknowns;
- risks;
- confidence: high / medium / low;
- requested next action.

## 5. Standard workflows

### Fast implementation workflow

Use for small, low-risk changes:

1. Claude inspects the existing code and posts a short proposal.
2. GPT comments only on material architecture/product risks.
3. Claude implements and runs targeted gates.
4. Claude posts checkpoint with exact SHA and evidence.
5. GPT independently verifies and posts GO/NO-GO.

Target: one proposal round, one review round.

### Design-decision workflow

Use for canonical state, scoring, budget, evidence, autonomy, security, or major Dashboard changes:

1. Owner goal becomes a product contract.
2. Claude and GPT form independent options.
3. Each critiques the other option.
4. The agents select a reversible option or define a small experiment.
5. Claude implements only the agreed scope.
6. Deterministic evidence decides the review.

Target: maximum two critique rounds.

### Incident/debug workflow

1. Claude reproduces locally and posts the smallest reliable failure evidence.
2. GPT checks for product-level contradictions, hidden blast radius, and prior invariants.
3. Claude applies the narrowest repair and regression test.
4. GPT reviews the exact repair SHA.

### Scout-learning workflow

1. Scout predicts target value, defect value, and fixability.
2. Execution produces real findings and evidence.
3. The funnel records qualification, proposal readiness, response, and paid outcome where available.
4. GPT and Claude compare prediction vs outcome.
5. A confirmed miss becomes a classifier/scoring change, fixture, or regression test.

## 6. Time-efficiency rules

- Default to targeted tests while iterating; rely on the repository's tiered CI contract.
- Do not run the full suite after every small edit.
- Use one bounded relay thread per decision.
- Avoid restating repository history already available through Git/Observer/docs.
- Prefer a reversible experiment over a long abstract debate.
- Reject unrelated refactors from active delivery slices.
- Limit collaboration-platform work to small PRs with a direct productivity payoff.
- Summaries to the owner must contain: decision, reason, risk, and required owner action — not the full agent transcript.

Suggested decision budgets:

- trivial/local: 5 minutes;
- cross-module: 15 minutes;
- canonical/security/budget: 30 minutes before experiment or escalation.

## 7. Scout and Dashboard outcome priorities

The collaboration system must accelerate these product outcomes:

1. Truthful canonical production-vs-diagnostic state across Dashboard and Observer.
2. Reliable prospect discovery from real configured sources, with dedupe and safe rescan semantics.
3. Multi-axis opportunity scoring: defect confidence, business impact, fixability, buyer likelihood,
   access feasibility, evidence quality, noise/competition, and expected value.
4. High-value QA investigation of critical flows with reproducible evidence and low false-positive rate.
5. Clear Operator Dashboard triage: what is active, what needs attention, why a target matters, what action is next.
6. Explicit budget/cost visibility for LLM, browser, and provider work.
7. Human-approved proposal/outreach/delivery boundaries.
8. A learning loop from target -> finding -> qualified opportunity -> proposal -> response -> paid work.

Existing owner-approved slice priorities remain authoritative. This document does not silently reorder them;
it defines how Claude and GPT should collaborate to complete them faster and more reliably.

## 8. Scout success metrics

Optimise for useful opportunities, not raw site counts or feature counts:

- qualified prospects / scanned targets;
- false-positive rate;
- confirmed commercially significant findings;
- evidence completeness and reproducibility;
- time from discovery to validated evidence;
- cost per qualified prospect;
- percentage of findings with a realistic fix path;
- target -> qualified -> proposal-ready -> response -> paid conversion;
- duplicate/rescan avoidance;
- diagnostic noise excluded from production views;
- LLM/browser/provider spend per useful outcome.

## 9. Autonomy levels

### Level 0 — unrestricted read/analysis

Repository reading, Git diff, Observer reads, planning, local deterministic analysis, recommendations.

### Level 1 — autonomous with audit

Feature-branch code changes, targeted tests, fixture runs, draft PRs, proposal/critique exchange,
NO-GO correction cycles.

### Level 2 — GPT gate required

Slice completion, canonical state semantics, scoring, budget semantics, security boundaries, evidence integrity,
release-candidate claims.

### Level 3 — owner required

Paid-budget exceptions, client credentials/access, outreach/email, purchases, real external mutations,
client delivery, destructive history rewrite, repository visibility/access changes, and final release acceptance.

**Merge to main** is owner-owned but **standingly delegated**: the owner granted a one-time standing
authorization (see section 13) so the trusted local Git/Claude automation may *execute* a merge after
an exact-head `[GPT REVIEW: GO]` + green required CI, with no per-PR re-confirmation. This does not move
merge authority to GPT — GPT's decision is a review verdict and always carries `merge_authorized=false`;
the authority stays with the owner, whose standing grant delegates only the routine execution.

## 10. Delivery phases

### Phase A — Base Review Relay (current PR)

- worker/reviewer role separation;
- checkpoint -> decision -> acknowledgement;
- immutable exact-SHA decisions;
- no shell and no merge;
- live stdio + authenticated HTTP handshake.

### Phase B — Collaboration Envelopes

Add PROPOSAL / CRITIQUE / QUESTION / RESPONSE / RECOMMENDATION / EVIDENCE threads without adding an autonomous model driver.

### Phase C — Session Delivery Driver

Safely deliver a decision to the intended Claude Code session. Session IDs and machine-specific paths remain local
and uncommitted. The driver must not expose arbitrary shell execution through MCP.

### Phase D — Autonomous Reviewer Driver

A separate bounded service notices checkpoints, invokes the configured GPT reviewer, posts decisions, and wakes the
Claude session. It must enforce budgets, retry/idempotency, exact-SHA binding, audit logging, and owner boundaries.

**Status:** Phase A shipped (`core/review_relay.py` + relay MCP). Phases B + C + D are implemented
together as **Direct Collaboration Driver v1** (GitHub Issue #14, `core/collaboration/`) — SHA-bound
envelopes, a bounded OpenAI-backed reviewer driver, safe delivery into one bound Claude session, an
owner-visible Dashboard monitor, and budget/retry/idempotency guardrails. See
`docs/DIRECT_COLLABORATION_DRIVER.md`. Phase E (Scout commercial learning loop) remains future work.

### Phase E — Scout Commercial Learning Loop

Use the collaboration channel to improve ranking, QA allocation, evidence quality, cost efficiency, and conversion
based on real outcomes.

Do not combine all phases into one PR.

## 11. Definition of done for the collaboration system

The system is successful when:

- Claude can submit a checkpoint without owner copy/paste;
- GPT can independently read it and post a SHA-bound decision;
- Claude receives and acknowledges that decision in the intended session;
- a moved head invalidates the old decision;
- neither agent can merge through the relay;
- the owner receives only concise escalations;
- the collaboration measurably shortens delivery cycles for Scout/Dashboard instead of becoming a parallel project.

## 12. Immediate execution plan

1. Finish and live-verify the current base Review Relay PR.
2. Keep the current PR narrowly scoped; use this document as the target architecture, not a request to implement all phases now.
3. After the handshake is proven, add collaboration message envelopes in one small PR.
4. Add local session delivery in a separate bounded step.
5. Use the working channel immediately on the remaining Scout/Dashboard slices.
6. Add full autonomous reviewer driving only after the manual relay path is stable and auditable.

## 13. Standing owner authorization (merge boundary)

The owner granted a durable standing authorization (recorded on GitHub, PR #13 comment 5037397576).
It replaces the earlier rule that each merge required a fresh owner message.

**Autonomous without another owner prompt** — after an exact-head `[GPT REVIEW: GO]` + green required
CI: create/update branches; commit and push scoped changes; open/update/convert PRs; add/remove CI
labels and rerun relevant jobs; rebase or resolve ordinary conflicts (no `main` history rewrite);
**merge a PR**; delete merged feature branches; create follow-up issues/checkpoints/comments; and
revert a newly merged change when CI or deterministic evidence proves a regression (then report).

**Still owner-gated (never automatic)** — force-push/history rewrite of `main` or protected branches;
deleting `main`, repositories, releases, or durable evidence; publishing a release/tag externally;
changing repository visibility/ownership/access; paid-budget exceptions, credentials, outreach,
purchases, client delivery, or any other external mutation.

The relay and reviewer tools themselves have **no merge capability** (`merge_authorized` is always
false); the merge is executed by the trusted local Git/Claude workflow after the validated exact-SHA GO.
A GO whose `reviewed_sha` no longer matches the branch head is stale and must not be acted on.

## 14. Canonical product invariants (review acceptance criteria)

Every architecture/PR review checks these owner-level invariants (GitHub PR #13 comment 5037647350).
A technically green change that materially violates one is a product NO-GO.

1. **Integrated product, not islands** — Scout, Dashboard, Work execution, Observer, evidence, CI, and
   the Claude↔GPT collaboration share one canonical state/read model; no duplicate dashboards or stores.
2. **Flexible, smart architecture** — modular, replaceable adapters and policy-driven orchestration; a
   living design that records decisions and migration paths.
3. **Maximum safe autonomy** — autonomous discovery, triage, analysis, testing, evidence, retries,
   dedupe/rescan, review/fix/merge-after-GO, and continuation; owner interruption only for
   credentials/access, paid budget, outreach/external mutation, destructive history, or genuine ambiguity.
4. **Operator-first UI** — clear state, actor, task, progress, PR/SHA/CI, next action, heartbeat,
   blockers, NEEDS_OWNER; smart defaults, filters, production vs diagnostics separation; mobile-friendly.
5. **Evidence is a first-class object** — reproducible bundles (screenshots/trace/logs/steps/env/
   timestamps/hashes/impact/confidence), retention/dedupe/redaction, and links from Dashboard findings;
   never fabricated; observed vs inferred vs unverified distinguished.
6. **Autonomous Scout optimizes commercial value** — real-source discovery, safe access checks,
   critical-flow investigation, low false positives, buyer likelihood, fixability, expected value; the
   target→finding→opportunity→proposal→response→paid-work learning loop is preserved.
7. **Budget-safe LLM usage** — deterministic/read-only first; LLM only where it materially helps;
   per-task/model/token/cost ledger, hard/soft limits, caching, idempotency, retry caps, visible spend.
8. **Restartable, low-maintenance** — survive app/driver/Claude restarts without losing the active task
   or duplicating actions; persist safe config/session bindings locally (never secrets in Git); health checks.
9. **Truthful across every surface** — Dashboard, Observer, API, CI, evidence, and docs agree on
   production state, diagnostics, readiness, costs, completion. "Installed" ≠ "ready"; "token present" ≠
   "authenticated"; "folder exists" ≠ a production campaign.
10. **Success is product completion** — the Direct Driver and relay are enabling infrastructure that must
    accelerate Scout/Dashboard/AI QA Factory completion, not become a competing endless platform.

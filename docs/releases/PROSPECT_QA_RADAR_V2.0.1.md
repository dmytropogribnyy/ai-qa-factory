# Prospect QA Radar v2.0.1 — Final Independent Acceptance + Gmail Primary Provider

**Status:** independently accepted complete local, human-approved prospect qualification and
communication product with a genuine Gmail API provider path. **Not** a new functional phase — this
release independently verifies `scout-v2.0.0`, fixes the real CI failure, adds the Gmail provider,
hardens the send core, and issues `scout-v2.0.1`. No additional product phase follows.

## Headline

- **CI root cause fixed.** The v2.0.0 `core-deterministic` job failed on Linux because a test
  launched a subprocess with a hardcoded Windows `cwd` (`d:\1QA AI\ai-qa-factory`). The cwd is now
  derived from the test's own location, plus a regression guard that fails if any committed Python
  file hardcodes a machine-specific absolute cwd.
- **Gmail is the primary genuine live provider**, sender pinned to `dipptrue@gmail.com`. Resend is an
  optional secondary adapter for `darrowcode.com` only, excluded from the critical path.

## What changed

- **Complete contact provenance (schema v3, additive).** An immutable, single-ACTIVE-row provenance
  entity per contact (source URL/evidence, publication, terms-review, freshness, named-person, data
  subject). Pre-send blocks on missing / synthetic / unpublished / terms-blocked / expired /
  named-person-incomplete provenance. The approval binds to the full provenance snapshot. Fixture
  provenance is allowed only when explicitly marked `deterministic_fixture` and is never a real
  prospect contact.
- **Real persisted gate references.** `suppression_checks`, `pre_send_revalidations`, and
  `policy_decisions` records with immutable ids, content hashes, and expiry replace synthetic strings
  such as `reval-live`. Placeholder detection now rejects `reval-live`, `supp-live`, `live`,
  `current`, `latest`, `placeholder`, `pending`, and legacy shortcuts.
- **Mandatory reviewed-content proof.** A canonical REVIEW_PREVIEW hash over one immutable revision's
  exact content is required to approve; an empty, arbitrary, wrong-revision, or stale hash is
  rejected, and the repository refuses to create any approval without it.
- **Enforced state machines + complete attempts.** Explicit allowed transitions for revisions,
  approvals, and messages (invalid / terminal-rewrite / skipping / unknown rejected) with an
  immutable lifecycle event per transition; every provider invocation finalizes a complete attempt
  record (no body/recipient stored).
- **Pre-provider control race closed.** Immediately before the single provider call, all
  authoritative gates are re-read; any late blocker cancels the reserved message as
  `CANCELLED_BEFORE_PROVIDER` with zero provider calls.
- **Provider-event trust model.** Every event carries a trust class; the contact/company relationship
  is derived only from the referenced outbound message, so a forged relationship can never suppress
  another company; unverifiable events are quarantined.
- **Exact approved payload boundary.** The provider receives the exact recipient/subject/body/from in
  a typed envelope; the local sink stores only sanitized hashes; a capture transport asserts the
  Gmail adapter receives the exact payload without publishing it.
- **Gmail API adapter + OAuth desktop flow.** Genuine MIME + base64url + injected transport, sender
  pinned to the authorized account, send-only scope, sanitized bounded errors, honest idempotency,
  and no token leakage. See [../GMAIL_PROVIDER_SETUP.md](../GMAIL_PROVIDER_SETUP.md).
- **Daily outreach limits.** Default 5/day, hard ceiling 10, optional per-campaign ceiling, computed
  from authoritative records; fixture/local-sink sends never consume the real ceiling.
- **Complete human review CLI** (`draft-create/preview/edit/approve/reject/revoke/status`) and Gmail
  commands (`gmail-auth/status/revoke-local-token`, `provider-status`); one revision at a time, no
  bulk / approve-all, bodies read from a file so they never enter shell history.
- **CI hardened.** `PROSPECT_RADAR_EXTERNAL_SEND_DISABLED=1` on every job; every real transport
  refuses external calls under the guard; no Gmail/Resend secrets; pip cache; JUnit + bounded
  secret-free artifacts.

## Provider readiness (honest)

`adapter-ready` → `OAuth-client-configured` → `user-authorized` → `expected-account-verified` →
`controlled-address-accepted` → `live-accepted`. As shipped: Gmail is **adapter-ready** (no
credential configured in this environment); **no provider is live-accepted and no real external
message was sent.**

## Tests

Full deterministic suite: **4336 passed, 4 pre-existing `PytestCollectionWarning`s** (+84 over the
4252 v2.0.0 baseline). Real browser/axe/perf acceptance remains green (browser-acceptance job).

## Honest non-claims

Does **not** claim: live Gmail acceptance (no test email was sent), autonomous or bulk outreach,
unrestricted crawling, exactly-once external delivery, automatic reply tracking without additional
authorization, cloud/SaaS deployment, guaranteed delivery, or guaranteed revenue.

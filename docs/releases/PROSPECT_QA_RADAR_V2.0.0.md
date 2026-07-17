# AI QA Factory / ARK Prospect QA Radar v2.0.0 — complete local, human-approved product

**Release:** `scout-v2.0.0` · **Date:** 2026-07-17 · **Phase:** Final Phase II (roadmap functionally complete)

The second and final functional phase. It completes the local product from "pre-send draft +
review queue" to **immutable draft revision → explicit human approval → immediate pre-send
revalidation → controlled provider send → immutable send history → delivery/bounce/reply/opt-out
events → human-approved follow-ups → commercial metrics**. Only a verification-only Final
Independent Acceptance pass remains.

## What it adds (Final Phase II)

- **Schema v2 (transactional migration).** New normalized entities (draft_revisions,
  approval_records, outbound_messages, send_attempts, provider_events, contact_events,
  followup_plans, commercial_events, outreach_controls, recipient_allowlist). A real v1.9.0
  database migrates to v2 preserving all data, suppression, and the no-send drafts history;
  migration is transactional (interrupted-rollback) and idempotent; backup/restore works across
  versions.
- **Immutable revisions + single-use approvals.** Editing supersedes and invalidates the old
  approval (never mutates in place). An approval is explicit, individual, single-use, expiring, and
  bound to exact recipient/body/finding/evidence/disclosure/suppression snapshot hashes; any
  material change invalidates it. Reviewer identity is required. There is no bulk approval.
- **Immediate pre-send revalidation.** Recomputes every gate from authoritative persisted truth and
  compares to the approved binding; placeholder references (supp-1, reval-1, …) are rejected.
- **Providers + gated sending.** A narrow provider interface with a mandatory
  DeterministicLocalSinkProvider (no network; the E2E driver), a sandbox, and an adapter-ready real
  email adapter (env-ref credentials only; no arbitrary-SMTP fallback). Sending is **disabled by
  default** and dry-run by default; a live send atomically consumes the single-use approval AND
  reserves the message (one idempotency key per provider+revision+recipient+channel) and calls the
  provider **exactly once**. An ambiguous outcome becomes OUTCOME_UNKNOWN and is **never
  auto-retried**. Global/campaign/provider/channel controls + global kill are checked at every gate.
- **Events + follow-up.** Normalized delivery/reply/bounce/opt-out/complaint events (idempotent);
  hard bounce invalidates the contact, opt-out/complaint create durable suppression, any reply
  stops automatic follow-up. Follow-ups are individually human-approved (no inherited approval).
- **Responsible disclosure.** A security finding can never enter normal outreach (routed to a
  secure review queue).
- **Commercial metrics** (factual; revenue only from explicit real/manual events; fixture vs real
  distinguished); a read-only **dashboard** communication view with **no send button**; a `send` /
  `radar-demo` / `outreach-control` / `comms-status` / `mcp-audit` CLI; `scripts/radar.cmd`; and CI.
- **MCP + VS Code integration audit.** 14 servers declared in `config/mcp_servers.v2.yaml`, all
  **disabled by default**, honestly classified, at most `declared_in_manifest` (never
  live-accepted); agent-only servers are never available to the Factory process. `.vscode`
  recommendation files (no auto-install). No live MCP call in the product or CI.

## Honest guarantees

At-most-once **automatic provider invocation** per approval; local duplicate-reservation prevention;
provider idempotency when supported; manual reconciliation for ambiguous outcomes. **Exactly-once
external delivery is NOT claimed.** The deterministic tests and the full E2E use only the confined
local sink — **no real external message was sent**.

## It may claim / it must not claim

May claim: controlled discovery, commercial triage, adaptive QA, verified evidence, company/site
memory, rechecks, public contact intelligence, controlled disclosure, immutable human approval,
controlled provider sending, reply/bounce/opt-out history, human-approved follow-ups, local
commercial metrics, deterministic full E2E, and CI when actually green. Must **not** claim:
autonomous/bulk outreach, unrestricted crawling, inferred-contact sending, cloud/SaaS, production
deployment, guaranteed revenue, guaranteed delivery, accessibility certification, or exactly-once
external delivery.

## Safety confirmation

No inferred-contact send, suppressed/opted-out send, unapproved send, bulk send, contact-form/
LinkedIn automation, CAPTCHA/access-control bypass, financial operation, or any external message
occurred. `scout-v1.0.0`, `scout-v1.0.1`, `scout-v1.1.0`, and `scout-v1.9.0` are unchanged.

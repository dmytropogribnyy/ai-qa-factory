# Prospect QA Radar v2.0.2 — Operator-Path Hotfix (Gmail wired into the real CLI + fail-closed OAuth)

**Status:** operator-path hotfix over `scout-v2.0.1`. **Not** a new functional phase — it reproduces
and fixes two independently discovered operator-path defects and issues `scout-v2.0.2`. No real Gmail
authorization was performed and **no real external message was sent.**

## Blocker 1 — Gmail was not wired into the public send command (fixed)

`cli._registry` used the deterministic **demo** registry (local_sink + a legacy `RealEmailAdapter`
for resend only), so `gmail_personal` was never registered and `GmailProvider` existed only in tests.
The documented operator command `scout send --provider gmail_personal` therefore failed with
"unknown provider". Worse, `SendService` resolved the provider only **after** consuming the approval
and reserving the message, so an unknown/unavailable provider stranded a consumed approval + a
reservation.

Fix:

- New `core/scout/comms/runtime.py::build_runtime_provider_registry` registers `local_sink` + the
  genuine `gmail_personal` (real transport, OAuth token provider, env-driven readiness status) +
  optional secondary `resend`. Transport/token/status are injectable so deterministic tests drive the
  full CLI path with a fake transport and fake credentials.
- The public `scout send` command uses the **runtime** registry, not the demo registry.
- `SendService` runs a **provider preflight (resolve + readiness) BEFORE** consuming the approval,
  reserving a message, or creating an attempt. Unknown / disabled / unconfigured / unauthorized /
  wrong-account / insufficient-scope providers produce a clean `BLOCKED` with the approval
  **unconsumed**, nothing reserved, no attempt, and **zero provider calls**.

## Blocker 2 — OAuth account verification was fail-open (fixed)

`authorize()` stored `account or expected_account`, **inventing** the expected identity when the
user-info lookup failed, and `gmail_status` trusted the bare token-store `account` field as proof.

Fix:

- Scopes are validated **before** any identity lookup or token write (required `gmail.send` +
  `openid`/`email`; no forbidden `gmail.modify`/`readonly`/`compose`/`metadata`/full-mailbox scope).
- The authorized account is proven **fail-closed** via a verified Google **id-token email claim**
  (offline decode of a signed Google claim; userinfo fallback). If the account cannot be proven, or
  differs from `dipptrue@gmail.com`, a sanitized `GmailConfigError` is raised and **no token is
  written** (any partial temp file is removed). `expected_account` is never substituted.
- The token is written **atomically** (temp file + `os.replace`); token values are never exposed.
- `gmail_status` reports `expected-account-verified` **only** when the verified id-token claim matches
  the expected account, a refresh token is present, and scopes are valid — a manually altered
  `account` field is **never** treated as identity proof.

## Provider readiness (honest)

`adapter-ready` → `OAuth-client-configured` → `user-authorized` → `expected-account-verified` →
`controlled-address-accepted` → `live-accepted`. **As shipped:** the adapter is implemented and the
operator CLI path is wired, but **OAuth remains unconfigured until the user performs local setup** —
so Gmail is **adapter-ready**, no provider is **live-accepted**, and **no real message was sent**.

## Tests

Deterministic operator-path acceptance (no Google client, no OAuth flow, no network, no real email):
runtime registry contains `gmail_personal`; the CLI send path uses `GmailProvider` with the exact
reviewed recipient/subject/body/From via a fake transport; preflight blocks every not-ready case
before any state mutation; the external-send guard refuses the real transport; and fail-closed OAuth
proves identity via a verified id-token claim and refuses unprovable/wrong accounts and invalid
scopes without writing a token.

## Honest non-claims

No live Gmail acceptance, no autonomous/bulk outreach, no exactly-once external delivery, no
cloud/SaaS deployment, no guaranteed delivery. OAuth credentials are supplied locally by the user and
were **not** supplied during this hotfix.

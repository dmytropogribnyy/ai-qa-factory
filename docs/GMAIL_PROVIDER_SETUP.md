# Gmail Provider Setup (Prospect QA Radar v2.0.1)

Gmail is the **primary genuine live email provider** for v2.0.1. The authorized sender is
**Dmytro Pogribnyy `<dipptrue@gmail.com>`**. Resend is an optional secondary adapter for verified
`darrowcode.com` addresses only (see the bottom of this page).

Sending is **disabled by default**. Every external message must be individually, explicitly, and
currently approved by a human. Nothing in this document enables autonomous or bulk outreach.

> **Canonical email policy:** `docs/EMAIL_IDENTITY_AND_MAILBOX_POLICY.md` is the single source of
> truth for every email identity, its purpose, and its OAuth scope — including the SECOND, read-only
> **Gmail QA Test Inbox** (`drdiplextexh@gmail.com`, `gmail.readonly`), which is a **distinct token**
> from this send provider. The send token can never read; the read token can never send.

> A ChatGPT/Claude Gmail connector is **not** a Factory credential. It does not expose its OAuth
> tokens to this standalone local process, and connector sessions are never reused.

> **v2.0.2 operator-path hotfix:** the Gmail adapter is now wired into the public
> `scout send --provider gmail_personal` command through the production runtime provider registry,
> and a provider **preflight** runs before any approval is consumed — an unconfigured/unauthorized/
> wrong-account/insufficient-scope Gmail provider produces a clean `BLOCKED` with nothing reserved and
> zero provider calls. OAuth account verification is **fail-closed** (a verified id-token claim, never
> an invented identity). OAuth still **remains unconfigured until you perform the local setup below**;
> nothing here is live-accepted and no real message has been sent.

## What the adapter is

- A real Gmail API adapter — not browser automation, SMTP, or an app password. It builds an
  RFC-compliant MIME message with the Python standard library, URL-safe-base64 encodes it, and
  submits `{"raw": ...}` to `users.messages.send`.
- The HTTP transport and the access-token provider are **injected**, so the deterministic test
  suite exercises the exact payload with a fake transport — no network, no Google client library,
  and no credential are required by the core or by CI.
- The optional Google client libraries are needed **only** for real OAuth authorization and a real
  send. They are listed in `requirements-gmail.txt` and are **not** part of `requirements.txt`.

## Credentials (supplied locally by you; never committed)

Create a **Desktop app** OAuth client in Google Cloud and download its client JSON. Store it and the
token outside the repo (e.g. under `.secrets/gmail/`, which is git-ignored). Never paste OAuth JSON
or refresh tokens into a chat prompt.

Configurable paths and identity (environment references only — never secret values):

| Variable | Meaning | Default |
| --- | --- | --- |
| `GMAIL_OAUTH_CLIENT_JSON` | Path to the downloaded client config | — |
| `GMAIL_OAUTH_TOKEN_JSON` | Path where the local token is stored | — |
| `GMAIL_EXPECTED_ACCOUNT` | The account authorization must belong to | `dipptrue@gmail.com` |
| `GMAIL_FROM_EMAIL` | The pinned sender address | `dipptrue@gmail.com` |
| `GMAIL_FROM_NAME` | The sender display name | `Dmytro Pogribnyy` |

## Scopes

Only the send scope plus minimal identity scopes are requested:

- `https://www.googleapis.com/auth/gmail.send`
- `openid`, `email` (only to prove the authenticated account)

The flow **refuses** `https://mail.google.com/`, `gmail.modify`, `gmail.readonly`, `gmail.compose`,
and `gmail.metadata`. Optional live reply synchronization would require a separately authorized
`gmail.metadata` scope; it is disabled by default and is **not** required for v2.0.1 sending. Extra
Gmail scopes are never added silently.

## One-time authorization

```
pip install -r requirements-gmail.txt
python main.py scout gmail-auth \
  --client-config .secrets/gmail/client_secret.json \
  --token-store   .secrets/gmail/token.json \
  --expected-account dipptrue@gmail.com
```

This opens your browser through the supported loopback (`localhost`) installed-app flow (no
deprecated copy/paste), verifies the authorized identity is `dipptrue@gmail.com` (a different
account is rejected), requests offline access, and stores a refreshable local token. Tokens are
never printed, never written to SQLite, never placed under `outputs/`, and never appear in
exceptions. On Windows, file-mode hardening is best-effort only — protect the token via NTFS ACLs / a
user-only directory (a future OS-keyring backend is planned).

Check status at any time (no token value is ever shown):

```
python main.py scout gmail-status --client-config ... --token-store ...
python main.py scout provider-status
```

## Provider readiness (honest ladder)

`adapter-ready` → `OAuth-client-configured` → `user-authorized` → `expected-account-verified` →
`controlled-address-accepted` → `live-accepted`. A client-secret file, a token file, or a passing
fake-transport test is **never** described as live acceptance. `live-accepted` is recorded only
after a controlled acceptance was actually performed.

## Delivery and idempotency honesty

`messages.send` does not provide a product-level exactly-once guarantee, and none is claimed. The
adapter keeps the existing honest guarantee: one local reservation per idempotency key, one
automatic provider invocation per consumed approval, **no** automatic retry after an ambiguous
result, and manual reconciliation for `OUTCOME_UNKNOWN`. Deterministic correlation headers
(`Message-ID`, `X-Prospect-Radar-Message-ID`, `X-Prospect-Radar-Revision-ID`) are set for Sent-folder
reconciliation; they are not claimed to be a Gmail idempotency mechanism. A read timeout after
transmission is `OUTCOME_UNKNOWN` (never auto-retried); a connection failure proven to occur before
transmission is a definite failure.

## Daily safety limits

Conservative defaults for the personal sender: outreach disabled by default, one recipient per
command, no CC/BCC, no batch API, a default of **5** new outreach messages per day, a hard ceiling of
**10**, an optional per-campaign ceiling, no auto-send scheduler, and no auto-retry. Fixture /
local-sink sends never consume the real daily ceiling.

## Dry-run, live send, and reconciliation

`scout send` is a dry run by default. A live Gmail send requires **all** of: `--approve-send`, the
exact revision id, the exact approval id, `--provider gmail_personal`, a non-empty `--reviewer`, an
exact `--confirm-recipient`, the recipient on the current allowlist, outreach enabled, and every gate
green. See [COMMANDS.md](COMMANDS.md), [RUNBOOK.md](RUNBOOK.md), and
[APPROVAL_MODEL.md](APPROVAL_MODEL.md).

## CI external-send guard

CI sets `PROSPECT_RADAR_EXTERNAL_SEND_DISABLED=1`, and each real transport refuses to make an
external call when that variable is set. No Gmail or Resend secrets are configured in CI, and no real
email is ever sent by any automated test.

## Controlled real acceptance (optional; never automated)

After all automated acceptance is green, a single harmless real message may be sent for a self-test —
to an address you own (sending to `dipptrue@gmail.com` itself is acceptable), never to a prospect,
with a subject that clearly identifies a test, no prospect data in the body, no attachment, no
CC/BCC, no follow-up, and an exact confirmation immediately before send. If OAuth files or explicit
confirmation are unavailable, the state remains `adapter-ready: yes / OAuth-client-configured: no /
user-authorized: no / live-accepted: no / real messages sent: zero`; missing credentials are not a
code defect.

## Resend (optional secondary)

Resend is optional, adapter-ready by default, disabled unless configured, and **excluded from the
critical path** (Gmail is the only required live provider). It may send only from a verified
`darrowcode.com` address, configured through `RESEND_API_KEY`, `RESEND_FROM_EMAIL`, and
`RESEND_REPLY_TO` (suggested: `From: QA Radar <qa@darrowcode.com>`, `Reply-To: dipptrue@gmail.com`).
A `dipptrue@gmail.com` sender is never used with Resend.

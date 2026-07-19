# Email Identity & Mailbox Policy (canonical)

**Status: IMPLEMENTED (v3.2).** This is the single source of truth for every email identity the AI QA
Factory uses, what each is for, which OAuth scope it holds, and how the two Gmail tokens are kept
strictly separate. `.env.example`, `docs/GMAIL_PROVIDER_SETUP.md`, `docs/CLIENT_WORK_OPERATOR_GUIDE.md`,
`docs/DASHBOARD_OPERATOR_GUIDE.md`, the Access Bootstrap, and the Dashboard all defer to this file.
Identities, scopes, and roles are asserted by `tests/test_v32_docs_consistency.py` so they cannot drift.

Dmytro Pogribnyy has explicitly authorized publishing these identities in the repository.

## 1. Canonical identity / use matrix

| Identity | Purpose | External visibility | OAuth / access |
|---|---|---|---|
| `Dmytro Pogribnyy <dipptrue@gmail.com>` | Scout sender after per-message approval; reply-to; operator notifications; manual client communication; controlled self-test recipient | Visible to approved recipients | **Separate SEND token:** `gmail.send + openid + email` only |
| `drdiplextexh@gmail.com` | Technical QA test inbox for explicitly authorized client/staging signup, verification, magic-link and password-reset flows | Test identity only; never the public Scout sender | **Separate TEST-INBOX token:** `gmail.readonly + openid + email` only |
| `drdiplextexh+<safe-project-slug>@gmail.com` | Per-project test alias routed to the technical inbox | Visible only to the authorized target being tested | Same test-inbox token; fall back to the base address if a target rejects plus addressing |
| prospect/client contact email | Recipient of one specific reviewed outreach draft | One exact recipient only | Never a global config value; allowlist + current revision + human approval |
| client-provided staging mailbox | Preferred when the client provides one | Client-scoped | **Needs Client** until supplied and authorized |
| Upwork messaging | Client/prospect conversation inside Upwork | Upwork only | Manual only; never Gmail automation or unofficial Upwork automation |

`qa@darrowcode.com` / Resend are **not** the AI QA primary identity and remain optional/outside the
critical path.

## 2. Which address is used where

- **Scout outreach send:** `dipptrue@gmail.com` (from-name `Dmytro Pogribnyy`), one recipient per
  approved message.
- **Operator notifications / reply-to:** `dipptrue@gmail.com`.
- **Manual client communication:** `dipptrue@gmail.com` (or Upwork messaging, manual).
- **QA test flows** (signup, email verification, magic links, password reset): the test inbox
  `drdiplextexh@gmail.com`, normally via a per-project alias `drdiplextexh+<slug>@gmail.com`.
- **Controlled self-test:** send from `dipptrue@gmail.com` → `drdiplextexh+aiqa-selftest@gmail.com`.
- **Upwork:** manual, inside Upwork only.

## 3. Separate tokens & scopes (hard rule)

Two Gmail identities, **two distinct token stores**, mutually-exclusive scopes:

- The **send token** holds `gmail.send + openid + email`. `gmail.readonly` (and modify/compose/full)
  are **forbidden** on it — it can never read mail.
- The **test-inbox token** holds `gmail.readonly + openid + email`. `gmail.send` (and modify/compose/
  insert/settings) are **forbidden** on it — it can never send mail.

Because each policy lists the other's core scope as forbidden, a single "mixed" token carrying both
`gmail.send` and `gmail.readonly` fails **both** validators. In addition, the test-inbox token file
must be a **physically distinct file** from the send token; if `GMAIL_TEST_OAUTH_TOKEN_JSON` resolves
to the same file as `GMAIL_OAUTH_TOKEN_JSON`, readiness is `Blocked`. The send-only Scout token is
**never** broadened to read Dmytro's personal mailbox to make a readiness badge green.

Enforced in `core/scout/comms/gmail.py` (`gmail_scope_blockers`) and
`core/scout/comms/test_inbox.py` (`test_inbox_scope_blockers`, `test_inbox_status`).

## 4. Plus-alias behavior & base-address fallback

- Template: `AIQA_TEST_ALIAS_TEMPLATE=drdiplextexh+{project_id}@gmail.com`.
- The `{project_id}` slug is validated **before** interpolation (`safe_project_slug`): 1–40 chars of
  `a-z`, `0-9`, single interior dashes; no dots, `+`, `@`, spaces, leading/trailing/double dashes,
  or non-ASCII. A malformed project id **fails closed** with an exact operator action — it is never
  interpolated into an address.
- If a target rejects plus addressing, fall back to the **base** `drdiplextexh@gmail.com`
  (`build_test_alias(..., plus_addressing=False)`).

## 5. Local secret-file locations, redaction & no-commit rules

- Credentials live **locally only**, referenced by environment-variable **name**, never by value:
  - Send: `GMAIL_OAUTH_CLIENT_JSON`, `GMAIL_OAUTH_TOKEN_JSON`.
  - Test inbox: `GMAIL_TEST_OAUTH_CLIENT_JSON` (may reuse the same Desktop client), a **distinct**
    `GMAIL_TEST_OAUTH_TOKEN_JSON`.
- Suggested locations (git-ignored, user-only): a directory outside the repo, e.g.
  `%USERPROFILE%\.aiqa\gmail\client_secret.json`, `...\send_token.json`, `...\test_inbox_token.json`.
- Token values, `client_secret`, `refresh_token`, `id_token`, and access tokens are **never** printed,
  returned, logged, placed in exceptions/HTTP responses/artifacts, committed, or included in PR
  comments. Retrieval returns only bounded, **redacted** correlation facts. Never commit a real `.env`.

## 6. Exact OAuth setup / status / self-test commands

Full walkthrough: `docs/GMAIL_PROVIDER_SETUP.md`. Summary:

```bash
# One-time Google Cloud Desktop OAuth client (client_secret.json) — see the setup guide.

# Authorize the SEND identity (loopback consent; select dipptrue@gmail.com):
python main.py scout gmail-auth \
  --client-config "$GMAIL_OAUTH_CLIENT_JSON" --token-store "$GMAIL_OAUTH_TOKEN_JSON" \
  --expected-account dipptrue@gmail.com

# Authorize the READ-ONLY test inbox (DISTINCT token; select drdiplextexh@gmail.com). Passing the
# send token lets the tool refuse a shared/mixed token store:
python main.py scout test-inbox-auth \
  --client-config "$GMAIL_TEST_OAUTH_CLIENT_JSON" --token-store "$GMAIL_TEST_OAUTH_TOKEN_JSON" \
  --send-token-store "$GMAIL_OAUTH_TOKEN_JSON" --expected-account drdiplextexh@gmail.com

# Per-identity readiness (no secret is shown):
python main.py scout gmail-status
python main.py scout test-inbox-status

# Both identities also appear as distinct rows in the Dashboard "Access & Integrations" card
# (Gmail Scout Send + Gmail QA Test Inbox):
python main.py dashboard
```

## 7. Human-approval model & default external-send kill switch

- External send is **disabled by default**: `PROSPECT_RADAR_EXTERNAL_SEND_DISABLED=1`. It is cleared
  only for an explicitly approved action and re-set immediately afterwards.
- Every send is **one recipient, current revision, human-approved, allowlisted, exact-recipient-
  confirmed**. No batch, no scheduler, no automatic retry. An ambiguous transport outcome is
  `OUTCOME_UNKNOWN`, never auto-retried.
- The account is proven by a **live cryptographic id-token check** at send/retrieval time
  (`verify_gmail_identity`), never by a decoded-claim shortcut.

## 8. Client authorization requirements for form / email-flow testing

- Automated signup/verification/reset testing against a client or staging system requires **explicit
  client authorization** for that flow. Until then the capability is **Needs Client / Needs Operator**.
- Prefer a **client-provided staging mailbox** when offered; otherwise use the operator-owned test
  inbox alias against the authorized target only.
- No CAPTCHA solving/bypass; no unofficial Upwork automation; intake is always manual.

## 9. Bounded inbox-search policy

The test inbox is **not** a general mailbox reader and no generic browser is exposed through the
Dashboard/HTTP. Every retrieval (`TestInboxReader.correlated_search`) is constrained to:

- an **exact** authorized test alias (`to:` must be the test mailbox or one of its plus-aliases —
  a foreign recipient is refused);
- a **narrow time window** (`newer_than`, hard-capped at 14 days);
- an **expected sender and/or subject** correlation, re-verified client-side after fetch;
- **metadata format only** (From/To/Subject/Date + Gmail's short snippet) — the full body is never
  fetched, and uncorrelated messages are dropped;
- **no persistence** of unrelated personal mail; only bounded, redacted correlation facts are returned.

## 10. Live acceptance, revocation & re-authorization

- **Controlled live acceptance:** authorize the send token (`dipptrue@gmail.com`) and the separate
  read-only token (`drdiplextexh@gmail.com`); after Dmytro's exact confirmation, send **one** harmless
  self-test `dipptrue@gmail.com → drdiplextexh+aiqa-selftest@gmail.com`; retrieve only that correlated
  message through the test-inbox adapter; record bounded redacted evidence of genuine send + receive;
  contact no prospect; then keep outreach disabled (`PROSPECT_RADAR_EXTERNAL_SEND_DISABLED=1`).
- **If Google browser consent is required**, setup pauses at exactly that step with one precise
  click-by-click instruction; it resumes automatically after confirmation.
- **Revocation / re-authorization:** delete the local token file (`revoke_local_token`) to force a
  fresh loopback authorization; revoke Google-side access in the Google Account permissions page. A
  revoked or stale token **fails closed** at preflight with an exact operator action. Re-authorize with
  the correct scopes and expected account; a wrong account or wrong scope is refused, never stored.

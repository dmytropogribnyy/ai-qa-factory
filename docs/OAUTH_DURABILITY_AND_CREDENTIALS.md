# OAuth Durability & Credential Status — v3.2

Companion to `docs/EMAIL_IDENTITY_AND_MAILBOX_POLICY.md`. Records the durability risk of the current
Gmail OAuth app and the GitHub PAT status. **No secret, token, refresh token, client secret, or
authorization code is printed here or anywhere in the repo.**

## 1. Gmail OAuth app — publishing status (RESOLVED — durable)

**Current state (updated):** the Google Cloud OAuth app (`Prospect QA Radar Local`, project
`prospect-qa-radar-local`, client "AI QA Factory Local Desktop") is **External / In production**
(user cap 2/100; full public verification intentionally not requested — personal use, two
owner-controlled accounts). The 7-day Testing refresh-token limit **no longer applies**.

**Durable re-authorization completed (atomic, no email sent, self-test not repeated):** both identities
were re-authorized under the In-production app with `prompt=consent`, each written to a temporary token
file, validated (exact account + mutually-exclusive scopes via live tokeninfo + refresh present), then
**atomically replaced** (`os.replace`) — the working tokens were never destroyed before the durable
replacements validated. Redacted evidence: `outputs/_email_selftest/durability_reauth.json` (git-ignored;
no token/secret value). Result — send: `dipptrue@gmail.com` `gmail.send + openid + email` (no read);
read: `drdiplextech@gmail.com` `gmail.readonly + openid + email` (no send); both refreshable, distinct
files, outside the repo. **Blocker CLOSED — durable Gmail readiness is now claimed.**

### Historical risk (why publication was required)

Before publication the app was **External / Testing**.

**Verified risk (official Google documentation, `developers.google.com/identity/protocols/oauth2`):**
> "A Google Cloud Platform project with an OAuth consent screen configured for an external user type
> and a publishing status of 'Testing' is issued a refresh token expiring in **7 days**, unless the
> only OAuth scopes requested are a subset of name, email address, and user profile."

Our tokens request `gmail.send` (send identity) and `gmail.readonly` (test-inbox identity). These are
**not** in the exempt `{email, profile, openid}` subset, so **both refresh tokens expire in ~7 days**
while the app remains in Testing. **Durable Gmail readiness cannot be claimed in this state.**

### Exact owner action (interactive Google — only the owner can do this)

1. Open <https://console.cloud.google.com/apis/credentials/consent> and select the project
   **`Prospect QA Radar Local`** (top project picker).
2. On the **OAuth consent screen** (or **Audience**) page, find **Publishing status: Testing**.
3. Click **PUBLISH APP** → in the "Push to production?" dialog click **CONFIRM**.
   - The app uses sensitive Gmail scopes, so Google may note that verification is required for
     wide public use. For **single-owner personal use this is fine**: publishing to production
     removes the 7-day refresh-token expiry; the only effect is the "unverified app" notice still
     appears on the consent screen for that account. **Do not** create another project or OAuth client.
4. Tell me "**published**".

### After publication (automatic, no email sent)

Existing refresh tokens were minted under Testing (7-day). To obtain durable refresh tokens I will
**re-authorize both identities** (`scout gmail-auth` for `dipptrue@gmail.com`, `scout test-inbox-auth`
for `drdiplextech@gmail.com`), each with `prompt=consent`, writing to **temporary** token files first
and **atomically replacing** the current tokens only after tokeninfo confirms the exact account and
mutually-exclusive scopes. Working tokens are never destroyed before the replacements validate. **No
email is sent during reauthorization.**

**Status: CLOSED (A). App In production + both identities re-authorized with durable refresh tokens.**

## 2. GitHub PAT status

- **GitHub secret-scanning alerts:** 0 (open + resolved) for `dmytropogribnyy/ai-qa-factory`.
- **git history:** no `client_secret`, token, `.aiqa`, or evidence path ever committed (`git log --all`
  name scan clean).
- **Active auth:** `gh` CLI is authenticated via the OS **keyring** (not an env var or committed file),
  scopes `gist, read:org, repo, workflow`.

There is **no evidence of a PAT ever being committed or exposed in this repository.** The earlier
"PAT-in-env workaround" put a token in a local environment variable (a GitHub MCP DCR workaround), not
in the repo.

**Owner decision (recorded):** the owner reviewed the GitHub token inventory and explicitly authorizes
**retaining** the existing fine-grained token **"Claude_vscode"** — do **not** rotate or delete it.
Owner-supplied evidence: fine-grained token; actively used; expires **2026-10-16**; **no classic PAT
exists**; repository secret scanning and Git history found no exposure. The fine-grained token's exact
repository selection and permissions are visible only in the owner's Developer Settings UI
(`github.com/settings/tokens`) — the API does not expose another token's scope selection without the
token itself, so this is confirmed by owner review, not reprinted here (the credential is never shown).

**Classification: Owner reviewed — retained by explicit owner decision; no in-repository exposure found;
residual risk accepted.** The token was **not** rotated (by owner choice). This owner decision
**resolves** the owner-only release blocker.

## 3. Local secret hygiene (evidenced)

- Both Gmail token stores + the client secret live under `%USERPROFILE%\.aiqa\gmail\` — **outside the
  repository**; `.gitignore` also defensively ignores `.aiqa/`, `client_secret*.json`, `send_token.json`,
  `test_inbox_token.json`.
- Self-test evidence lives under `outputs/_email_selftest/` (git-ignored `outputs/*`); it is redacted
  and contains no token/body.
- Token/refresh/client-secret **values** are never returned, printed, logged, committed, or sent to any
  endpoint except Google's own token/tokeninfo endpoints.

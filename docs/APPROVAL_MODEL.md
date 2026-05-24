# Approval Model — Guided QA Automation Workbench

**Version:** 5.1.0  
**Updated:** 2026-05-24

> **AI drafts. Senior QA decides.**

---

## Core rule

The workbench generates artifacts and proposes actions. Dmytro approves before anything risky executes.

Approval is **execution-mode-based and action-based** — not URL-pattern-based, not robots.txt-based, not domain-based. A staging URL is not automatically safe just because it says "staging".

---

## Risk levels

Every action in the workbench belongs to one of these risk levels:

| Level | Label | Description |
|---|---|---|
| 0 | `safe_analysis` | Reading, classifying, summarizing text locally |
| 1 | `safe_local` | Generating files, running local compile/lint/dry-run |
| 2 | `external_read_only` | Fetching a URL or API response (no state changes) |
| 3 | `external_write` | Writing to an external system (issue tracker, repo, form) |
| 4 | `production_read_only` | Any read against a production environment |
| 5 | `payment_or_auth` | Payment flows, auth flows, session tokens, MFA |
| 6 | `security_sensitive` | Injection tests, auth bypass, privilege escalation |
| 7 | `client_delivery` | Sending any artifact to a client or posting publicly |

---

## What runs automatically

Risk levels 0 and 1 run without any gate:

| Action | Risk level |
|---|---|
| Read and parse input files | `safe_analysis` |
| Classify input type and project type | `safe_analysis` |
| LLM inference (mock or real) | `safe_analysis` |
| Generate strategy, test plans, test cases | `safe_analysis` |
| Write output files to `outputs/` | `safe_local` |
| Generate Playwright TypeScript scaffold | `safe_local` |
| Generate Project Blueprint | `safe_local` |
| Run TypeScript compile check | `safe_local` |
| Run `playwright --dry-run` | `safe_local` |
| Run ESLint | `safe_local` |
| Run pytest (always mock mode) | `safe_local` |
| Write state snapshots and JSONL logs | `safe_local` |
| `--dry-run` workflow mode | `safe_local` |

---

## What requires approval

Risk levels 2–6 require explicit approval before proceeding:

| Action | Risk level | Approval mechanism |
|---|---|---|
| Fetch a URL for content | `external_read_only` | `--approve` flag |
| Run Playwright tests against any external URL | `external_read_only` | `--approve` + checklist |
| Call a live API endpoint | `external_read_only` | `--approve` + scope confirmation |
| Run Playwright against staging | `external_read_only` | `--approve` + section 4 of RUNBOOK |
| Write to an issue tracker (Jira, Linear) | `external_write` | `--approve` + explicit scope |
| Push to a repository | `external_write` | Manual only — workbench never auto-pushes |
| Any read against production | `production_read_only` | `--approve` + written client scope |
| Test payment flows | `payment_or_auth` | `--approve` + sandbox confirmation in writing |
| Test auth flows (login, session, token) | `payment_or_auth` | `--approve` + test account confirmation |
| Use a credential reference in a test run | `payment_or_auth` | `--approve` + `CredentialUseApproval` record |
| Auth flow execution against staging | `payment_or_auth` | `--approve` + `AuthFlowPlan.approved = True` |
| Password reset, 2FA, email verification, account settings | `payment_or_auth` | `--approve` + explicit scope per flow type |
| Billing or payment flow testing | `payment_or_auth` | `--approve` + sandbox confirmation in writing |
| Auth check against production | `production_read_only` | `--approve` + written client scope + read-only confirmed |
| Security testing (injection, bypass) | `security_sensitive` | `--approve` + written authorization |
| Destructive account actions (delete, change password, modify billing) | `security_sensitive` | Blocked by default — requires separate destructive-scope approval |

**Currently implemented approval mechanism:** `--approve` flag on the CLI.  
**Planned:** `approve-action` command with per-action approval records.

### Credential-specific approval gates (schema-only in Phase 1B-auth)

These gates are encoded in `core/schemas/credentials.py` and `core/schemas/auth_flow.py`. Runtime enforcement is planned for a later phase.

| Gate | Default | Override requirement |
|---|---|---|
| `CredentialReference.requires_approval_before_use` | `True` | Explicit `CredentialUseApproval` with `approved = True` |
| `CredentialReference.approved_for_use` | `False` | Must be set via approval decision |
| `CredentialPolicy.allow_credential_use` | `False` | Must be explicitly enabled per project |
| `CredentialPolicy.allow_production_credentials` | `False` | Written client scope + production read-only approval |
| `AuthFlowPlan.blocked` | `True` | Must be unblocked via explicit approval |
| `AuthFlowPlan.safe_to_execute` | `False` | Set to True only after all approval gates pass |
| `AuthFlowStep.allowed_in_production` | `False` | Production read-only approval required |

---

## What is blocked

Risk level 7 is always blocked — it requires a manual human action, not just a flag:

| Action | Why blocked |
|---|---|
| Sending a proposal to a client | Must be manually copied and sent |
| Delivering a client report | Must be manually reviewed, edited, and sent |
| Posting to Upwork, Fiverr, or any platform | Manual — workbench never auto-posts |
| Committing to a client's repository | Manual — workbench never auto-commits |

No flag, no argument, no configuration makes these automatic. They require a person to act.

---

## What should never run automatically

Beyond level 7, some actions are permanently out of scope:

- Running destructive database operations
- Running security tests (injection, auth bypass) without client-signed authorization
- Testing payment flows with real money
- Accessing systems not listed in the agreed scope
- Generating or using real user credentials (PII)
- Auto-scaling or triggering infrastructure changes

---

## How approval is currently enforced

### `--approve` flag

Signals that Dmytro has reviewed the input and context. With `--approve`:
- `HUMAN_REVIEW_REQUIRED.md` is still generated (for audit trail) but marked pre-approved
- The quality gate still runs — errors are shown but do not block
- Use only when you have genuinely reviewed and accepted the input

Without `--approve`:
- `HUMAN_REVIEW_REQUIRED.md` is generated with a full checklist
- Approval status is `needs_human_review`

### `--require-real-llm`

Fails the run if `LLM_MODE=mock`. Ensures output is real LLM content before any client-facing use.

### Pre-run safety prompts

Certain keywords trigger interactive prompts before the workflow starts:

| Keyword in input | Prompt |
|---|---|
| `payment`, `sandbox`, `stripe` | Confirm payment testing is sandbox-only |
| `production`, `live site` | Confirm staging/prod boundary and stop conditions |
| `urgency`, `ASAP` | Confirm scope is realistic for the timeline |

### `HUMAN_REVIEW_REQUIRED.md`

Generated after every non-pre-approved run. Contains per-artifact checklist. Never send output without clearing this file.

### `QUALITY_GATE_REPORT.md`

16 automated checks. Errors block the "approved" status. Warnings require manual review.

---

## Approval model for the planned client project workflow

When `approve-action` and `reject-action` commands are implemented (Phase 5):

```
Action proposed → approval-board shows it pending
    → approve-action records the decision
    → run-approved executes with that decision recorded
    → evidence is linked to the approval decision
    → reject-action blocks and records reason
```

Every external execution will have a recorded approval decision in the project state.

---

## Related documents

- [`SAFETY_RULES.md`](SAFETY_RULES.md) — hard rules, no exceptions
- [`RUNBOOK.md`](RUNBOOK.md) — approval checkpoints checklist (section 4)
- [`REAL_TESTING_PREPARATION.md`](REAL_TESTING_PREPARATION.md) — full staging checklist

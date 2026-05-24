# Safety Rules — Guided QA Automation Workbench

**Version:** 5.1.0-workbench-alpha  
**Updated:** 2026-05-24

These rules are non-negotiable. They exist because QA automation work touches authentication flows, payment systems, staging environments, and client data. Getting any of these wrong has real consequences.

---

## Execution rules

### Rule 1 — No external execution without explicit approval

The workbench does not run Playwright tests, API calls, or any network operations against external URLs unless:

1. `--approve` flag is passed, AND
2. `APPROVAL_CHECKPOINTS.md` has been reviewed, AND
3. `TESTING_READINESS_CHECKLIST.md` has been completed

**There is no URL pattern, domain allowlist, or robots.txt check that substitutes for this.** Even "safe" public demo sites require the above before running generated tests.

### Rule 2 — Production is never a test target

Production environments are never an acceptable test target for automated runs.

Testing on production:
- Is not supported by the workbench
- Requires explicit written authorisation from the client
- Requires a stop-conditions agreement before any test execution
- Must still be approved per Rule 1

### Rule 3 — Staging is not production, but is still external

Staging environments are still real external systems. Apply Rule 1 fully.

Additional staging requirements:
- Staging URL must be a different domain or subdomain from production
- Test accounts must be synthetic (no PII, no real user data)
- Payment flows must use sandbox mode (Stripe test mode, etc.)
- No destructive actions without explicit scope

### Rule 4 — No credentials in artifacts

API keys, passwords, tokens, and credentials:
- Must never appear in input briefs
- Must never appear in generated test files
- Must never appear in reports or delivery notes
- Live in `.env` only, inside the framework folder that generates them
- `.env` files are never committed to git and never included in deliveries

The quality gate includes a `HardcodedCredentialsCheck` that flags patterns matching common credential formats. If it fires, fix before any client use.

### Rule 5 — No invented evidence

The workbench must never claim capabilities, results, or experience that don't exist:

- No invented bug reports (e.g., "I found 12 bugs in your system last week")
- No invented Loom recordings
- No invented Linear or Jira tickets
- No invented device availability (e.g., claiming iOS device access without having it)
- No invented Tosca/Maestro/React Native experience beyond what is declared

The quality gate includes a `NoInventedEvidenceCheck`. If it fires, the output cannot be sent to a client.

### Rule 6 — Mock output is not client output

If `LLM_MODE=mock`, the generated content is structural placeholder text — not real analysis.

Mock output must never be sent to a client. The workbench marks mock runs with:
- `MockModeWarningCheck` in the quality gate
- WARNING in terminal output
- Exit code 2 under `--require-real-llm`

Use `--require-real-llm` before any client-facing run.

---

## Content rules

### Rule 7 — No overclaims

The workbench must not generate text that claims:
- Guaranteed bug-free outcomes
- 100% test coverage
- Absolute stability or reliability
- Outcomes that cannot be verified before delivery

The quality gate includes an `OverclaimsCheck`. Soften language to: "aims to cover", "targets the critical path", "provides a foundation for".

### Rule 8 — No generic proposal phrases

Client-facing proposals must not use:
- "I'm excited to apply"
- "Dear Hiring Manager"
- "I am passionate about"
- Template filler that could apply to any job

The quality gate includes a `GenericProposalPhrasesCheck`. Personalise to the specific brief.

### Rule 9 — Screening questions must be answered specifically

If a job post contains screening questions, the generated proposal must answer them specifically — not generically. The `ScreeningQuestionsAnsweredCheck` flags proposals where screening questions were detected but no specific answers were generated.

---

## System rules

### Rule 10 — Safety gates are not bypassed

Hooks, guards, and quality checks are not bypassed with `--no-verify`, `--force`, or by editing check logic.

If a quality check fires incorrectly (false positive), fix the check — don't disable it.

### Rule 11 — Real testing only after system-health pass

Before any real-mode run:

```bash
python main.py system-health
.venv\Scripts\python.exe -m pytest -q   # must show 69 passed
```

A failing health check or failing tests mean the local environment is not ready for real work.

### Rule 12 — Archive hygiene

When creating archives or sharing the project:

**Exclude:** `.env`, `.env.local`, `.venv/`, `__pycache__/`, `outputs/`, `test-results/`, `playwright-report/`, `node_modules/`

**Include:** source code, `sample_inputs/`, `validation_inputs/`, `docs/`, `tests/`, `requirements.txt`, `README.md`, `.env.example`

If `.env` is accidentally included in a shared archive: **rotate all API keys immediately.**

---

## Approval model reference

The full approval model (gates, flags, checklists) is in [`docs/APPROVAL_MODEL.md`](APPROVAL_MODEL.md).  
The pre-execution checklist for real staging runs is in [`docs/REAL_TESTING_PREPARATION.md`](REAL_TESTING_PREPARATION.md).

---

## Summary table

| Scenario | Allowed without approval | Requires approval |
|---|---|---|
| Generate scaffold from brief | Yes | — |
| Write output files locally | Yes | — |
| Run pytest (mock mode) | Yes | — |
| TypeScript compile check | Yes | — |
| Run Playwright dry-run (no network) | Yes | — |
| Run Playwright against demo/public site | No | Rule 1 checklist |
| Run Playwright against client staging | No | Rule 1 checklist + written scope |
| Run Playwright against production | No | Rule 2 — not supported |
| Send proposal to client | No | Human edit + HUMAN_REVIEW_REQUIRED.md |
| Submit deliverable to client | No | Human edit + HUMAN_REVIEW_REQUIRED.md |
| Push to client's repository | No | Manual — workbench never auto-pushes |

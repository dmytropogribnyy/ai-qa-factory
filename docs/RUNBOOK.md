# Guided QA Automation Workbench — Daily Practical Runbook

**System version:** v5.1.0-workbench-alpha (built on v5.0.9 + P1 calibration)  
**Tests:** 69/69 pass  
**Updated:** 2026-05-24

This is the daily operating guide. What to run, what to open, and what to check.

Product vision: [`docs/VISION.md`](VISION.md)  
Full command reference: [`docs/COMMANDS.md`](COMMANDS.md)  
Approval and safety model: [`docs/APPROVAL_MODEL.md`](APPROVAL_MODEL.md)  
Architecture: [`docs/AI_QA_Factory_Concept_and_Implementation_Plan_v7_validation_hardened.md`](AI_QA_Factory_Concept_and_Implementation_Plan_v7_validation_hardened.md)

> **AI drafts. Senior QA decides.**

---

## 1. Quick Start from Clean Repo

```powershell
# Windows PowerShell
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# Windows Git Bash
python -m venv .venv
source .venv/Scripts/activate

# macOS / Linux
python3 -m venv .venv
source .venv/bin/activate
```

```bash
pip install -r requirements.txt
copy .env.example .env      # Windows
# cp .env.example .env      # macOS/Linux
```

Keep mock mode first — no API keys required for structure testing.

---

## 2. Mock Mode vs Real Mode

### Mock mode (default, safe, no cost)

```env
LLM_MODE=mock
MODEL_PROFILE=mock
```

Use for: installation check, workflow testing, CI, structure validation.  
Not suitable for real client proposals or actual test strategy quality.

### Real mode (requires API keys)

```env
LLM_MODE=real
MODEL_PROFILE=premium_hybrid

OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

**Model routing in `premium_hybrid`:**

| Role | Model | Used for |
|------|-------|----------|
| `architect` | `gpt-5.5` | Prescreening, capability routing, strategy |
| `coding` | `anthropic/claude-sonnet-4-6` | Scaffold notes, code implementation |
| `review` | `anthropic/claude-opus-4-7` | Deep review, quality gate, self-health |
| `fast` | `anthropic/claude-sonnet-4-6` | Proposals, summaries, delivery notes |
| `vision` | `gpt-5.5` | Future visual review |
| `fallback` | `gpt-5.4-mini` | Backup |

**If only OpenAI key:** `MODEL_PROFILE=openai_only`  
**If only Anthropic key:** `MODEL_PROFILE=anthropic_only`

**Safety rules:**
- API keys stay only in `.env` — never in input briefs, prompts, or reports.
- Do not commit `.env` to any repo.

---

## 3. Health Check and Tests

Run these before any real work:

```bash
python main.py system-health
```

Expected: all 26 checks pass (Python, packages, LLM config, API keys, directories, Node/npm/npx).

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Expected: **69 passed**

Tests always run in mock mode regardless of `.env`. No API keys consumed.

> **Windows — real LLM runs only:** Set `PYTHONIOENCODING=utf-8` before calling the factory with `--require-real-llm`. LLM responses may contain Unicode characters (arrows, em-dashes, etc.) that the Windows cp1252 console codec cannot encode. Without this, litellm's internal logging raises `UnicodeEncodeError`, which the router catches as a real failure and triggers mock fallback — silently producing mock output even when keys are valid.
>
> ```powershell
> $env:PYTHONIOENCODING="utf-8"
> .venv\Scripts\python.exe main.py <command> --require-real-llm
> ```
>
> Alternatively, add `PYTHONUTF8=1` to your `.env` file (see `.env.example`) so this is always on for new setups. Always use `.venv\Scripts\python.exe`, not `python` — the system Python may resolve to a different installation with stale bytecode.

---

## 4. Daily Workflow

Follow this order every time:

```
1. prescreen (fast suitability check)
        ↓
2. open READ_ME_FIRST.md → DECISION.md → PRESCREENING_REPORT.md
        ↓
3. choose next workflow:
   - upwork        for proposals
   - test-design   for strategy/plan/cases
   - scaffold      for Playwright framework
   - batch-filter  for shortlisting many jobs
   - full          for end-to-end pack
   - review        for code/test file review
        ↓
4. human review before using anything
```

---

## 5. Confirmed Current Commands

### System readiness

```bash
python main.py system-health
```

### Pre-screening

> `--auto` controls workflow execution style, not LLM mode. Mock vs real is controlled by `LLM_MODE` and `MODEL_PROFILE`.

```powershell
# PowerShell — set mock mode before running
$env:LLM_MODE="mock"; $env:MODEL_PROFILE="mock"
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --auto
```

```bash
# Git Bash — set mock mode before running
export LLM_MODE=mock MODEL_PROFILE=mock
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --auto
```

```bash
# Real LLM (requires LLM_MODE=real and valid API keys in .env)
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
```

### Batch filter (shortlist many jobs at once)

```bash
python main.py batch-filter --input real_jobs/
```

Output: `outputs/batch_opportunity_report.md`

### Upwork proposal pack

```bash
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
```

### Test design (strategy + plan + cases)

```bash
python main.py test-design --input real_jobs/client_brief.txt --require-real-llm
```

### Playwright scaffold

```bash
python main.py scaffold --input real_sites/site_001_brief.txt --require-real-llm
```

### Full workflow

```bash
python main.py full --input real_jobs/client_brief.txt --require-real-llm
```

### Code / test file review

```bash
python main.py review --input real_jobs/test_to_review.ts
```

### Ask about a saved project

```bash
python main.py ask --project-id <project_id> --question "Why did you recommend apply_selectively?"
python main.py ask --project-id <project_id>   # interactive REPL
```

### Capability and agent info

```bash
python main.py capabilities
python main.py agents
python main.py agents --workflow prescreen
```

### Execution mode flags (work with any workflow)

```bash
python main.py full --input <file> --step            # pause between agents for inline feedback
python main.py full --input <file> --dry-run         # no final file write
python main.py full --input <file> --only proposal_writer
python main.py full --input <file> --from-step proposal_writer
python main.py full --input <file> --project-id <id> --only proposal_writer
```

### Run tests from a generated Playwright framework

```bash
python main.py run-tests --project-path outputs/<project_id>/framework --kind playwright
```

---

## 6. `--source-platform` Values

Use `--source-platform` when the pasted text doesn't make the source obvious:

```bash
python main.py prescreen --input <file> --source-platform upwork
```

Valid values:

| Value | Use for |
|-------|---------|
| `upwork` | Upwork job post |
| `fiverr` | Fiverr buyer request |
| `peopleperhour` | PeoplePerHour brief |
| `contra` | Contra project post |
| `linkedin_direct` | LinkedIn DM or direct lead |
| `writing_platform` | nDash, Draft.dev, TestMu, DO Ripple etc. |
| `direct_b2b` | Client email / direct B2B brief |
| `ai_evaluator` | Evaluator platform opportunity |
| `unknown` | Default when source is unclear |

---

## 7. Commands That Do NOT Exist

| Wrong | Correct |
|-------|---------|
| `python -m ai_qa_factory` | `python main.py <mode>` |
| `--brief` | `--input` |
| `python main.py opportunity` | `python main.py prescreen` — **future, not current** |
| `python main.py gig` | `python main.py prescreen` — **future, not current** |
| URL-only autonomous analysis | Write a brief `.txt` first — **future, not current** |
| Screenshot-only intake | **Future, not current** |

---

## 8. What to Open First After Any Run

```
outputs/<project_id>/
  READ_ME_FIRST.md          ← start here
  DECISION.md
  NEXT_ACTIONS.md
  PRESCREENING_REPORT.md
  APPROVAL_CHECKPOINTS.md
  QUALITY_GATE_REPORT.md    ← check for errors/warnings
  HUMAN_REVIEW_REQUIRED.md  ← manual checklist before sending
  SELF_HEALTH_REPORT.md     ← if present
  SYSTEM_REPAIR_PLAN.md     ← if present
```

For proposals: also open `proposal.md`, `screening_answers.md`, `evidence_needed.md`, `commercial_strategy.md`.  
For delivery: also open `TEST_STRATEGY.md`, `TEST_PLAN.md`, `TEST_CASES.md`.

---

## 9. Upwork Workflow

```bash
# Step 1 — save job text
# Create: real_jobs/job_001.txt
# Paste the full Upwork job post (title, description, budget, screening questions)

# Step 2 — prescreen first
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --auto

# Step 3 — read the verdict
# Open: READ_ME_FIRST.md → DECISION.md → PRESCREENING_REPORT.md

# Step 4 — if promising, run full proposal
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm

# Step 5 — review before sending
# Open and edit manually: proposal.md, screening_answers.md, evidence_needed.md,
#   commercial_strategy.md, QUALITY_GATE_REPORT.md, HUMAN_REVIEW_REQUIRED.md
```

**Never invent:** bug reports, Loom examples, Linear tickets, client names, device availability, Tosca/Maestro/React Native experience, security testing authorization.

---

## 10. Test Design Workflow

When a client asks for a test strategy, test plan, or test cases:

```bash
python main.py test-design --input real_jobs/client_brief.txt --require-real-llm
```

Outputs:

```
TEST_STRATEGY.md
TEST_PLAN.md
TEST_CASES.md
QUALITY_GATE_REPORT.md
HUMAN_REVIEW_REQUIRED.md
```

---

## 11. Playwright Scaffold Workflow

### Generate the scaffold

```bash
python main.py scaffold --input real_sites/site_001_brief.txt --require-real-llm
```

### Before running any generated tests — P1.2 behavior (current)

The scaffold intentionally requires setup before tests pass:

- `playwright.config.ts` has `baseURL: process.env.BASE_URL` — **no fallback default**. Tests will fail without BASE_URL set.
- `smoke.spec.ts` has `test.skip(!process.env.BASE_URL, 'Set BASE_URL in .env before running UI smoke tests')` — the home-page test skips until BASE_URL is provided.
- `health.spec.ts` accepts **`[200, 204]` only** — a 404 from `/health` fails the test.
- The generated `framework/README.md` has a **First-run setup** section. Read it before `npm test`.

```bash
# Step 1 — go to generated framework
cd outputs/<project_id>/framework

# Step 2 — install dependencies
npm install
npx playwright install

# Step 3 — create .env and set BASE_URL to your staging URL
# cp .env.example .env
# edit .env: set BASE_URL=https://your-staging-url.com

# Step 4 — review placeholder assertions (TODO comments in smoke.spec.ts)
# Replace /.+/ with your actual expected title pattern

# Step 5 — run tests
npx playwright test
```

Do **not** run `npm test` blindly against a public site without reviewing the generated files first.

### Safe runner from Factory root

```bash
python main.py run-tests --project-path outputs/<project_id>/framework --kind playwright
```

---

## 12. Controlled Demo-Site Testing

**Current stage:** controlled testing on safe public apps only.

Approved sources:

| Source | Notes |
|--------|-------|
| `validation_inputs/01–06` | Local briefs, no credentials needed |
| `https://demoqa.com/` — written brief | Public learning site |
| `https://www.saucedemo.com/` — written brief | QA training site, public demo accounts |
| `https://opensource-demo.orangehrmlive.com/` — written brief | Public HRM demo |

**Workflow for each demo site:**

```bash
# Write a brief describing the site (do NOT paste credentials in the brief)
# Save as: real_sites/demo_site_001_brief.txt

python main.py prescreen --input real_sites/demo_site_001_brief.txt --auto

# Read routing result, then optionally:
python main.py scaffold --input real_sites/demo_site_001_brief.txt --require-real-llm
```

**Rules:**

- No real payments. Sandbox/payment-flow testing only when explicitly in scope, confirmed safe, and real-mode output has not fallen back to mock.
- No production sites.
- No credentials in the input brief.
- Do not `npm test` against demo sites until BASE_URL and assertions are reviewed.
- Record any misrouting as a gap — do not fix during the run.

---

## 13. Real Staging-Site Checklist

Before any run against a real client staging environment, all of the following must be in place:

```
Written scope
  [ ] Client provided written scope: target URL, in-scope flows, out-of-scope, timebox
  [ ] Staging URL is different domain from production
  [ ] Stop conditions agreed

Environment
  [ ] Test accounts provisioned per role (no PII, synthetic data)
  [ ] API base URL is staging only
  [ ] OpenAPI spec / Postman collection (if API testing)
  [ ] Bearer/JWT tokens for staging only
  [ ] Rate limits known

Safety
  [ ] Sandbox payment confirmed in writing (test cards only)
  [ ] No destructive actions allowed
  [ ] Stripe / payment provider is in test mode
  [ ] No production database access
  [ ] Credentials in .env only — not in briefs or reports

System readiness
  [ ] python main.py system-health — all pass
  [ ] .venv\Scripts\python.exe -m pytest -q — 69/69 green
  [ ] LLM_MODE=real, MODEL_PROFILE=premium_hybrid
  [ ] python main.py prescreen --input <brief> --require-real-llm — real LLM response (not mock fallback)

Human approval per run
  [ ] APPROVAL_CHECKPOINTS.md signed off
  [ ] PRESCREENING_REPORT.md reviewed
  [ ] No client-facing artifact sent without manual edit pass
```

Full checklist: [`docs/REAL_TESTING_PREPARATION.md`](REAL_TESTING_PREPARATION.md)

---

## 14. Mock Fallback Warning (P1.5)

If real LLM calls fail and the system falls back to mock output, you will see:

```
WARNING: N LLM call(s) fell back to mock output. Check outputs/<id>/logs/factory.jsonl.
```

Under `--require-real-llm`, the process returns **exit code 2** unless `--allow-mock` is also passed.

If you see this warning in a real-mode run:
1. Check API key validity (`python main.py system-health`).
2. Check model availability and rate limits.
3. Do not use the output as client-facing — it is mock content.

---

## 15. Troubleshooting

### venv not active / wrong Python

```
(.venv) PS> python --version   # should show the venv Python
```

If not active:
```powershell
.\.venv\Scripts\Activate.ps1
```

### Tests accidentally hitting real LLM

Tests always run in mock mode — `tests/conftest.py` sets `LLM_MODE=mock` before any import. No API keys are consumed by `pytest`.

### `--require-real-llm` fails immediately

Cause: `LLM_MODE=mock` in `.env` or environment.  
Fix: set `LLM_MODE=real` and provide valid API keys. Run `python main.py system-health` to confirm.

### Mock fallback warning on real run

See §14 above. Check keys and model availability.

### `botocore` warning in CLI output

```
WARNING: No module named 'botocore'
```

**Cosmetic only.** LiteLLM warns about AWS Bedrock/SageMaker not being available. No functional impact. Suppressed in `pytest`.

### Playwright `BASE_URL` missing

Generated scaffold requires `BASE_URL` set in the framework `.env`. Without it, UI smoke tests skip and API tests fail. See §11.

### Playwright `npm test` shows green against wrong URL

After P1.2 there is no `https://example.com` fallback. If you still see unexpected greens, verify which `.env` is loaded in the framework folder.

### Output is generic / too short

Likely mock mode. Set `LLM_MODE=real`, run with `--require-real-llm`. Add more context to the input brief. Use `--step` mode to give inline feedback after each agent.

---

## 16. Common Workflow Quick-Reference

| Situation | What to do |
|-----------|------------|
| Found an Upwork job, not sure if worth applying | `prescreen` → read DECISION.md → if promising, `upwork` |
| Have 20 jobs in a folder, want to shortlist fast | `batch-filter --input real_jobs/` → read `outputs/batch_opportunity_report.md` |
| Client asks for test strategy / plan / cases | `test-design --input brief.txt --require-real-llm` |
| Need a proposal for a writing/SaaS doc opportunity | `prescreen --source-platform writing_platform` → if green, `full` |
| Asked to scaffold Playwright framework for a site | `scaffold --input brief.txt --require-real-llm` → run `run-tests` after setup |
| Want to ask why the system made a decision | `ask --project-id <id> --question "Why did you recommend skip_low_value?"` |
| Output looks like a mock / too generic | Check `.env`: `LLM_MODE=real`. Re-run with `--require-real-llm` |
| Want to re-run only one agent from a saved project | `full --input brief.txt --project-id <id> --only proposal_writer` |

---

## 17. Optional Tools by Project Type

These are not installed by the Factory — they are external tools you may need depending on what the client brief describes.

| Project type | Optional tools |
|--------------|---------------|
| Bug tracking / issue management | Linear, Jira, GitHub Issues |
| Exploratory session recording | Loom, Jam.dev |
| API testing | Postman, OpenAPI spec / Swagger UI |
| Billing / payment flow testing | Stripe test-mode dashboard, test card set |
| Mobile testing | Maestro (Android/iOS), Xcode Simulator, Android Emulator |
| CI/CD integration | GitHub Actions (needs access token), GitLab CI |
| Accessibility audits | axe DevTools, Lighthouse |

The Factory generates instructions and notes for these tools where relevant — it does not launch them autonomously.

---

## 18. First Real Testing Sequence (Onboarding Path)

Follow this order the first time you move from mock to real LLM and real-site work:

```
Step 1 — mock smoke check
  python main.py system-health
  .venv\Scripts\python.exe -m pytest -q     ← must show 69 passed

Step 2 — batch-filter a small folder
  python main.py batch-filter --input real_jobs/
  Read: outputs/batch_opportunity_report.md

Step 3 — pick one promising job, run real prescreen
  python main.py prescreen --input real_jobs/job_001.txt \
    --source-platform upwork --require-real-llm
  Read: READ_ME_FIRST.md → DECISION.md → PRESCREENING_REPORT.md
  Check: WARNING lines in terminal (mock fallback?)

Step 4 — if verdict is strong_apply, run full proposal
  python main.py upwork --input real_jobs/job_001.txt \
    --source-platform upwork --require-real-llm
  Open and manually edit: proposal.md, screening_answers.md,
    evidence_needed.md, QUALITY_GATE_REPORT.md, HUMAN_REVIEW_REQUIRED.md

Step 5 — only after steps 1–4 are clean, start website testing
  Write a brief for a safe demo site (see §12)
  python main.py scaffold --input real_sites/demo_brief.txt --require-real-llm
  Follow §11 setup before running npx playwright test
```

Never jump to Step 5 without passing Step 1. A mock-fallback warning in Step 3 means your output is not client-ready — fix keys first.

---

## 19. Archive and Sharing Hygiene

When creating a zip to share or archive:

**Exclude:**

```
.env
.env.local
.venv/
__pycache__/
.pytest_cache/
outputs/
test-results/
playwright-report/
node_modules/
```

**Safe archive includes:** source code, `sample_inputs/`, `validation_inputs/`, `docs/`, `tests/`, `requirements.txt`, `README.md`, `.env.example`.

If `.env` was accidentally included in a shared archive: **rotate all API keys immediately** (OpenAI, Anthropic, any others present).

---

## 20. Source Documents

| Document | Purpose |
|----------|---------|
| [`docs/AI_QA_Factory_Concept_and_Implementation_Plan_v7_validation_hardened.md`](AI_QA_Factory_Concept_and_Implementation_Plan_v7_validation_hardened.md) | Canonical concept, architecture, capability zones, roadmap |
| [`docs/REPO_STRATEGIC_READINESS_AUDIT_v1.md`](REPO_STRATEGIC_READINESS_AUDIT_v1.md) | P0/P1/P2/P3 patch plan, agent readiness matrix |
| [`docs/VALIDATION_WEBSITE_TESTING_REPORT.md`](VALIDATION_WEBSITE_TESTING_REPORT.md) | 2026-05-24 validation run results |
| [`docs/REAL_TESTING_PREPARATION.md`](REAL_TESTING_PREPARATION.md) | Full real-site staging checklist |
| [`docs/VSCODE_USAGE.md`](VSCODE_USAGE.md) | VS Code setup and archive hygiene |
| [`docs/MODEL_ROUTING_PROFILES.md`](MODEL_ROUTING_PROFILES.md) | Full model profile reference |
| [`README.md`](../README.md) | Quick start and main commands |

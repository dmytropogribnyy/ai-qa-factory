# AI QA Factory — Practical Runbook

**Version:** v1.0  
**For project:** AI QA Factory v5.0.7 Code & Documentation Sync  
**Purpose:** clear step-by-step guide for installing, running, testing, and working with the system.

---

## 0. What this system is for

AI QA Factory is a local **opportunity + QA delivery cockpit**.

It helps you:

- pre-screen Upwork / direct / writing / platform opportunities;
- decide whether to apply, skip, treat as advisory, or ask for clarification;
- generate proposals, screening answers, evidence requirements, pricing strategy;
- generate QA strategy, test plans, test cases, Playwright scaffold, review notes, delivery summaries;
- keep a human-readable workflow with approvals and reports.

Main rule:

> **AI drafts. Senior QA decides.**

The system should not auto-submit proposals, auto-push code, run unsafe actions, or perform unauthorized testing.

---

## 1. Recommended working setup

Use:

- **VS Code** as the main workspace;
- **VS Code integrated terminal** for commands;
- **Python 3.11+** if possible;
- **Node.js + npm** for Playwright scaffold / test execution;
- **real LLM API key** only when you are ready to test actual output quality;
- **mock mode** first, to verify structure and workflow.

---

## 2. First installation

### 2.1. Unzip the project

Unzip:

```text
AI-QA-Factory-v5.0.7-Code-Doc-Sync.zip
```

Open the unzipped folder in VS Code.

Example folder:

```text
AI-QA-Factory-v5.0.7-Code-Doc-Sync/
```

---

### 2.2. Create virtual environment

#### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks activation, run PowerShell as user and execute:

```powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned
```

Then activate again:

```powershell
.\.venv\Scripts\Activate.ps1
```

#### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
```

---

### 2.3. Install Python dependencies

```bash
pip install -r requirements.txt
```

---

### 2.4. Create `.env`

Copy the example file:

#### Windows

```powershell
copy .env.example .env
```

#### macOS / Linux

```bash
cp .env.example .env
```

At the beginning, keep mock mode:

```env
LLM_MODE=mock
ARCHITECT_MODEL=mock
CODING_MODEL=mock
REVIEW_MODEL=mock
FAST_MODEL=mock
VISION_MODEL=mock
FALLBACK_MODEL=mock

OUTPUT_DIR=outputs
MEMORY_DIR=memory
PERSISTENCE_BACKEND=json
LLM_TIMEOUT_SECONDS=90
LLM_MAX_RETRIES=2
```

---

## 3. First health check

Run:

```bash
python main.py system-health
```

This checks:

- Python environment;
- installed packages;
- `.env` / LLM mode;
- output and memory folders;
- Node / npm / npx availability;
- readiness for Playwright-related work.

Then run tests:

```bash
python -m pytest -q
```

Expected:

```text
35 passed
```

If tests pass, the local system is structurally OK.

---

## 4. Mock mode vs real LLM mode

## 4.1. Mock mode

Use mock mode for:

- checking installation;
- checking workflows;
- testing file outputs;
- learning commands;
- verifying that the system does not crash.

Example:

```bash
python main.py prescreen --input sample_inputs/upwork_job_saas_multitenant_billing.txt --allow-mock
```

Mock mode is **not suitable** for real client proposals.

---

## 4.2. Real LLM mode

Use real mode for:

- actual proposal quality testing;
- real Upwork job analysis;
- final screening answers;
- serious test strategy / test plans;
- client-facing drafts.

Recommended `.env` structure:

```env
LLM_MODE=litellm

ARCHITECT_MODEL=<your-architect-model>
CODING_MODEL=<your-coding-model>
REVIEW_MODEL=<your-review-model>
FAST_MODEL=<your-fast-model>
VISION_MODEL=<your-vision-model>
FALLBACK_MODEL=<your-fallback-model>

OPENAI_API_KEY=sk-...
```

Example with OpenAI models, if available in your account:

```env
LLM_MODE=litellm

ARCHITECT_MODEL=gpt-5.5
CODING_MODEL=gpt-5.5
REVIEW_MODEL=gpt-5.5
FAST_MODEL=gpt-5.4-mini
VISION_MODEL=gpt-5.5
FALLBACK_MODEL=gpt-5.4-mini

OPENAI_API_KEY=sk-...
```

Alternative Anthropic / Claude via LiteLLM example:

```env
LLM_MODE=litellm

ARCHITECT_MODEL=anthropic/claude-sonnet-4-5-20250929
CODING_MODEL=anthropic/claude-sonnet-4-5-20250929
REVIEW_MODEL=anthropic/claude-sonnet-4-5-20250929
FAST_MODEL=anthropic/claude-sonnet-4-5-20250929
VISION_MODEL=anthropic/claude-sonnet-4-5-20250929
FALLBACK_MODEL=anthropic/claude-sonnet-4-5-20250929

ANTHROPIC_API_KEY=...
```

Important:

- model names can change;
- verify available model IDs in your provider account;
- never paste API keys into prompts or job descriptions;
- keep API keys only in `.env`;
- do not commit `.env` to GitHub.

After configuring real mode, run:

```bash
python main.py system-health
```

Then test one real LLM call:

```bash
python main.py upwork --input sample_inputs/upwork_job_greenhouse_ai_native_qa.txt --require-real-llm
```

If `LLM_MODE=mock`, this command must fail. That is correct.

---

## 5. Main command map

### 5.1. Check system readiness

```bash
python main.py system-health
```

Use before real testing.

---

### 5.2. Pre-screen one opportunity

```bash
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --allow-mock
```

Use this first for any new opportunity.

Output answers:

- is this suitable?
- can Factory help fully / partially / advisory-only?
- rough timebox;
- blockers;
- required inputs;
- approval checkpoints;
- recommended workflow.

Key file:

```text
PRESCREENING_REPORT.md
```

---

### 5.3. Filter one opportunity

```bash
python main.py filter --input real_jobs/job_001.txt --source-platform upwork --allow-mock
```

Use when you only need a fast apply/skip decision.

---

### 5.4. Batch-filter many opportunities

Put job texts into:

```text
real_jobs/
  job_001.txt
  job_002.txt
  job_003.txt
```

Run:

```bash
python main.py batch-filter --input real_jobs/ --allow-mock
```

Output:

```text
outputs/batch_opportunity_report.md
```

Use this to shortlist opportunities before spending Connects.

---

### 5.5. Generate Upwork proposal package

Mock structure test:

```bash
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --allow-mock
```

Real proposal draft:

```bash
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
```

Expected important outputs:

```text
READ_ME_FIRST.md
DECISION.md
NEXT_ACTIONS.md
proposal.md
screening_answers.md
commercial_strategy.md
evidence_needed.md
red_flags.md
HUMAN_REVIEW_REQUIRED.md
QUALITY_GATE_REPORT.md
SELF_HEALTH_REPORT.md
SYSTEM_REPAIR_PLAN.md
```

Open first:

```text
READ_ME_FIRST.md
```

Then check:

```text
screening_answers.md
proposal.md
evidence_needed.md
QUALITY_GATE_REPORT.md
HUMAN_REVIEW_REQUIRED.md
```

---

### 5.6. Generate test strategy / test plan / test cases

```bash
python main.py test-design --input real_jobs/client_brief_or_requirements.txt --allow-mock
```

With real LLM:

```bash
python main.py test-design --input real_jobs/client_brief_or_requirements.txt --require-real-llm
```

Outputs:

```text
TEST_STRATEGY.md
TEST_PLAN.md
TEST_CASES.md
SELF_HEALTH_REPORT.md
SYSTEM_REPAIR_PLAN.md
PROJECT_EXTENSION_PLAN.md
```

Use this for:

- manual QA projects;
- client briefs;
- QA strategy requests;
- test case creation;
- documentation of testing approach.

---

### 5.7. Generate Playwright scaffold

```bash
python main.py scaffold --input real_jobs/client_brief.txt --allow-mock
```

With real LLM:

```bash
python main.py scaffold --input real_jobs/client_brief.txt --require-real-llm
```

Expected framework output is usually under:

```text
outputs/<project_id>/framework/
```

Then go there:

```bash
cd outputs/<project_id>/framework
npm install
npx playwright install
npx playwright test
```

Or use Factory safe runner from project root:

```bash
python main.py run-tests --project-path outputs/<project_id>/framework --kind playwright
```

---

### 5.8. Full workflow

```bash
python main.py full --input real_jobs/client_brief.txt --allow-mock
```

Real LLM:

```bash
python main.py full --input real_jobs/client_brief.txt --require-real-llm
```

Use full workflow only after pre-screening says the opportunity is suitable.

---

### 5.9. Review code or test file

```bash
python main.py review --input real_jobs/test_to_review.ts --allow-mock
```

Use for:

- flaky Playwright test review;
- locator quality review;
- hard waits;
- weak assertions;
- test data problems.

---

### 5.10. Ask questions about a saved project

After a run, find `project_id` in the output folder name or `state.json`.

One question:

```bash
python main.py ask --project-id <project_id> --question "Why did the system recommend apply_selectively?"
```

Interactive mode:

```bash
python main.py ask --project-id <project_id>
```

Useful questions:

```text
Why did you recommend skip?
What should I edit before sending proposal?
Which evidence is missing?
How can we make the proposal shorter?
What risks should I mention to the client?
What should be the first milestone?
```

---

## 6. Execution modes

Most workflows support these flags:

```text
--auto       default, run without pauses
--step       pause between agents and allow feedback
--dry-run    run without final output writing
--only       run one selected agent
--from-step  resume from selected agent
--project-id reuse saved project state
```

### 6.1. Step mode

```bash
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --step --require-real-llm
```

Use when the opportunity is important and you want to control each stage.

Example feedback:

```text
redo: make proposal shorter, less automation-first, more SaaS billing risk focused
```

---

### 6.2. Dry run

```bash
python main.py full --input real_jobs/job_001.txt --dry-run --allow-mock
```

Use for quick workflow testing.

---

### 6.3. Run only one agent

```bash
python main.py upwork --input real_jobs/job_001.txt --project-id <project_id> --only proposal_writer --require-real-llm
```

Use when you only want to regenerate one artifact.

---

### 6.4. Resume from step

```bash
python main.py full --input real_jobs/job_001.txt --project-id <project_id> --from-step qa_planner --require-real-llm
```

Use when earlier steps are already OK.

---

## 7. Human-readable outputs: what to open first

After each run, open files in this order:

### 1. `READ_ME_FIRST.md`

Top-level summary:

- decision;
- suitability;
- recommended workflow;
- effort estimate;
- what to open next.

### 2. `DECISION.md`

Apply / skip / advisory decision.

### 3. `NEXT_ACTIONS.md`

Concrete next steps.

### 4. `PRESCREENING_REPORT.md`

Suitability, effort, blockers, required inputs.

### 5. `APPROVAL_CHECKPOINTS.md`

Where your confirmation is required.

### 6. `QUALITY_GATE_REPORT.md`

Warnings / errors in generated outputs.

### 7. `HUMAN_REVIEW_REQUIRED.md`

Manual checklist before using any client-facing output.

### 8. `SELF_HEALTH_REPORT.md` and `SYSTEM_REPAIR_PLAN.md`

System consistency check and safe repair suggestions.

---

## 8. Working with Upwork jobs

### 8.1. Save job text

Create:

```text
real_jobs/job_001.txt
```

Paste full Upwork job post including:

- title;
- summary;
- required skills;
- budget/rate;
- screening questions;
- client metadata if available;
- bid range if visible.

### 8.2. Pre-screen first

```bash
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --allow-mock
```

### 8.3. If promising, run real LLM

```bash
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
```

### 8.4. Before sending proposal

Always check:

```text
screening_answers.md
proposal.md
evidence_needed.md
commercial_strategy.md
QUALITY_GATE_REPORT.md
HUMAN_REVIEW_REQUIRED.md
```

Never invent:

- bug reports;
- Loom examples;
- Linear tickets;
- client names;
- device availability;
- Tosca / Maestro / React Native experience;
- security testing authorization.

---

## 9. Working with other platforms

Use `--source-platform` when known:

```bash
python main.py prescreen --input opportunities/fiverr_gig_request.txt --source-platform fiverr --allow-mock
python main.py prescreen --input opportunities/writing_pitch.txt --source-platform writing_platform --allow-mock
python main.py prescreen --input opportunities/direct_b2b_lead.txt --source-platform direct_b2b --allow-mock
```

Current useful source values:

```text
upwork
fiverr
peopleperhour
contra
linkedin_direct
writing_platform
direct_b2b
ai_evaluator
unknown
```

The system should adapt output style:

- Upwork → proposal + screening answers;
- writing platform → pitch + article outline + AI policy warning;
- Fiverr/PPH → gig/package structure;
- direct B2B → cold DM / one-page offer / credibility pack;
- evaluator platform → profile prep, not task execution.

---

## 10. Testing websites and apps

## 10.1. Important current limitation

Current reliable intake is:

```text
text / brief / job post / manually described URL or screenshots
```

Do **not** expect full production-ready URL-only or screenshot-only autonomous analysis yet.

Allowed now:

- paste target URL as context;
- describe what the site/app does;
- list critical flows;
- provide test credentials in `.env`, not in prompt;
- generate test strategy / plan / Playwright scaffold;
- manually run generated tests after review.

Future stage:

```text
URLIntakeAdapter
ScreenshotIntakeAdapter
PlaywrightReconAgent
VisionReviewAgent
```

---

## 10.2. Prepare a site testing brief

Create:

```text
real_sites/site_001_brief.txt
```

Template:

```text
Project: <name>
URL: <target URL>
Testing permission: yes / no / own account / demo site
Environment: staging / production-safe / public demo
Goal: <what to test>
Critical flows:
1. login
2. signup
3. checkout
4. dashboard
5. role-based access
Accounts:
- stored in .env
Roles:
- admin
- user
- technician
Restrictions:
- no real payment
- no destructive actions
- no security exploitation
Expected output:
- QA audit
- test plan
- bug report template
- Playwright scaffold
```

Then run:

```bash
python main.py prescreen --input real_sites/site_001_brief.txt --source-platform direct_b2b --allow-mock
```

If suitable:

```bash
python main.py test-design --input real_sites/site_001_brief.txt --require-real-llm
```

Or:

```bash
python main.py scaffold --input real_sites/site_001_brief.txt --require-real-llm
```

---

## 10.3. Demo/public sites

Good for safe practice:

- public demo login sites;
- public e-commerce demo stores;
- form/table demo apps;
- local test apps;
- your own websites;
- staging apps where you have permission.

Avoid:

- real checkout payments;
- scraping;
- aggressive crawling;
- unauthorized API replay;
- crypto/deposit/ID tasks;
- testing other people's production apps without permission.

---

## 10.4. Real client / real site readiness checklist

Before running practical testing, prepare:

```text
approved target URL
staging/test environment if possible
test accounts
test roles
test data
browser/device matrix
critical flows
allowed actions
forbidden actions
reporting format
Loom/Jam if video required
Linear/Jira/Google Doc if bug reports required
Stripe sandbox if billing
Postman/OpenAPI if API testing
```

---

## 11. Credentials and secrets

Never store credentials in job text or Markdown outputs.

Use `.env`:

```env
TEST_BASE_URL=https://staging.example.com
TEST_ADMIN_EMAIL=...
TEST_ADMIN_PASSWORD=...
TEST_USER_EMAIL=...
TEST_USER_PASSWORD=...
STRIPE_TEST_MODE=true
```

Do not commit `.env`.

Recommended:

- use test accounts only;
- rotate passwords after testing;
- never use real customer data;
- use email aliases where possible;
- avoid real payment methods.

---

## 12. Playwright practical workflow

### 12.1. Generate scaffold

```bash
python main.py scaffold --input real_sites/site_001_brief.txt --require-real-llm
```

### 12.2. Open generated framework

```bash
cd outputs/<project_id>/framework
```

### 12.3. Install Node dependencies

```bash
npm install
npx playwright install
```

### 12.4. Configure test env

Create local `.env` in framework if generated README asks for it.

Example:

```env
BASE_URL=https://staging.example.com
ADMIN_EMAIL=...
ADMIN_PASSWORD=...
```

### 12.5. Run tests

```bash
npx playwright test
```

Or from Factory root:

```bash
python main.py run-tests --project-path outputs/<project_id>/framework --kind playwright
```

### 12.6. View Playwright report

```bash
npx playwright show-report
```

Expected Playwright artifacts may include:

- trace;
- screenshot on failure;
- video on failure;
- HTML report.

---

## 13. Common workflows

## 13.1. “I found an Upwork job — should I apply?”

```bash
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --allow-mock
```

Open:

```text
READ_ME_FIRST.md
PRESCREENING_REPORT.md
DECISION.md
```

If good:

```bash
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
```

---

## 13.2. “I have 20 Upwork jobs — sort them”

```bash
python main.py batch-filter --input real_jobs/ --allow-mock
```

Open:

```text
outputs/batch_opportunity_report.md
```

---

## 13.3. “Client asks for test strategy / test cases”

```bash
python main.py test-design --input real_jobs/client_requirements.txt --require-real-llm
```

Open:

```text
TEST_STRATEGY.md
TEST_PLAN.md
TEST_CASES.md
```

---

## 13.4. “Client asks for Playwright setup”

```bash
python main.py prescreen --input real_jobs/client_brief.txt --allow-mock
python main.py scaffold --input real_jobs/client_brief.txt --require-real-llm
```

Then:

```bash
python main.py run-tests --project-path outputs/<project_id>/framework --kind playwright
```

---

## 13.5. “I need technical writing / documentation pitch”

```bash
python main.py prescreen --input writing_jobs/job_001.txt --source-platform writing_platform --allow-mock
python main.py full --input writing_jobs/job_001.txt --source-platform writing_platform --require-real-llm
```

Open:

```text
documentation_plan.md
sample_doc_rewrite.md
proposal.md
screening_answers.md
evidence_needed.md
```

---

## 13.6. “I want to ask the system why it decided this”

```bash
python main.py ask --project-id <project_id>
```

Then ask:

```text
Why did you recommend apply_selectively?
What evidence is missing?
How should I reduce the scope?
What should I ask the client before accepting?
```

---

## 14. What APIs / tools are needed?

## 14.1. Required now

For basic real output quality:

```text
OpenAI API key or another LiteLLM-supported provider key
```

For OpenAI:

```env
OPENAI_API_KEY=sk-...
```

For Anthropic:

```env
ANTHROPIC_API_KEY=...
```

Run:

```bash
python main.py system-health
```

---

## 14.2. Required for Playwright website testing

```text
Node.js
npm
npx
Playwright browsers
```

Commands:

```bash
node -v
npm -v
npx --version
npx playwright install
```

---

## 14.3. Optional by project

| Need | Tool / access |
|---|---|
| Bug reports in Linear | Linear access |
| Bug reports in Jira | Jira access |
| Videos | Loom or Jam.dev |
| API testing | Postman / OpenAPI / API tokens |
| Stripe billing | Stripe sandbox / test cards |
| Mobile iOS | Mac + Xcode + TestFlight |
| Mobile Android | Android Studio + emulator |
| Maestro tests | Maestro CLI |
| GitHub repo | GitHub access token or repo invite |
| Screenshots / visual review | later Vision model / screenshot adapter |
| Browser recon | later PlaywrightReconAgent |

---

## 15. When not to use the system yet

Do not use Factory as an autonomous executor for:

- unsupported URL-only analysis;
- screenshot-only decisions;
- unauthorized security testing;
- real payment testing without sandbox/approval;
- crypto/deposit/ID tasks;
- evaluator platform tasks where AI usage is prohibited;
- any task where evidence would need to be invented.

Use Factory to analyze, plan, draft, and guide — not to bypass responsibility.

---

## 16. Recommended first real testing sequence

### Step 1 — mock smoke check

```bash
python main.py system-health
python -m pytest -q
python main.py prescreen --input sample_inputs/upwork_job_saas_multitenant_billing.txt --allow-mock
```

### Step 2 — batch-filter real Upwork jobs in mock mode

```bash
python main.py batch-filter --input real_jobs/ --allow-mock
```

### Step 3 — pick 1 best job

Run:

```bash
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --allow-mock
```

### Step 4 — run same job with real LLM

```bash
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
```

### Step 5 — review human-readable pack

Open:

```text
READ_ME_FIRST.md
proposal.md
screening_answers.md
commercial_strategy.md
evidence_needed.md
QUALITY_GATE_REPORT.md
HUMAN_REVIEW_REQUIRED.md
```

### Step 6 — only after this, test real websites

Prepare a site brief and run:

```bash
python main.py prescreen --input real_sites/site_001_brief.txt --source-platform direct_b2b --allow-mock
python main.py test-design --input real_sites/site_001_brief.txt --require-real-llm
```

Then, if scaffold is needed:

```bash
python main.py scaffold --input real_sites/site_001_brief.txt --require-real-llm
```

---

## 17. Troubleshooting

### Problem: `--require-real-llm` fails

Likely reasons:

- `LLM_MODE=mock`;
- no API key;
- wrong model name;
- LiteLLM not installed;
- model unavailable in account.

Check:

```bash
python main.py system-health
```

---

### Problem: Playwright tests do not run

Check:

```bash
node -v
npm -v
npx --version
npx playwright install
```

Then run inside framework folder:

```bash
npm install
npx playwright test
```

---

### Problem: output is too generic

Likely reason:

- mock mode;
- weak input brief;
- no real LLM;
- missing evidence/context.

Fix:

- use `--require-real-llm`;
- add more details to input;
- use `--step` and give feedback;
- ask system via `ask` command.

---

### Problem: system recommends skip but you disagree

Use:

```bash
python main.py ask --project-id <project_id>
```

Ask:

```text
What would make this opportunity apply_selectively instead of skip?
Can we position it as advisory-only?
What evidence or scope change is needed?
```

---

## 18. Safe working rule

Before sending anything to a client or platform, manually verify:

- claims;
- experience;
- mandatory keywords;
- screening answers;
- evidence;
- budget/rate;
- safety boundaries;
- testing authorization;
- final tone.

The system is a serious assistant, not a replacement for judgment.



---

## v1.1 Update — Model Routing Profiles

Use role-based model routing instead of one model for everything.

### Recommended setup: premium hybrid

In `.env`:

```env
LLM_MODE=real
MODEL_PROFILE=premium_hybrid

OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

PERSISTENCE_BACKEND=json
```

This routes work like this:

| Role | Model | Used for |
|---|---|---|
| `architect` | `gpt-5.5` | prescreening, capability routing, strategy, complex QA decisions |
| `coding` | `anthropic/claude-sonnet-4-6` | code-related work, Playwright/scaffold notes, implementation tasks |
| `review` | `anthropic/claude-opus-4-7` | deep review, Quality Gate, self-health, difficult reasoning |
| `fast` | `anthropic/claude-sonnet-4-6` | proposals, summaries, delivery notes |
| `vision` | `gpt-5.5` | future screenshot/visual workflows |
| `fallback` | `gpt-5.4-mini` | backup |

### If you only have OpenAI key

```env
LLM_MODE=real
MODEL_PROFILE=openai_only
OPENAI_API_KEY=sk-...
```

### If you only have Anthropic key

```env
LLM_MODE=real
MODEL_PROFILE=anthropic_only
ANTHROPIC_API_KEY=sk-ant-...
```

### Check routing

```bash
python main.py system-health
```

The report should show selected `MODEL_PROFILE`, role model IDs, effort values, and whether the required provider keys are present.

### Optional manual overrides

```env
ARCHITECT_MODEL=gpt-5.5
CODING_MODEL=anthropic/claude-sonnet-4-6
REVIEW_MODEL=anthropic/claude-opus-4-7
FAST_MODEL=anthropic/claude-sonnet-4-6
VISION_MODEL=gpt-5.5
FALLBACK_MODEL=gpt-5.4-mini

ARCHITECT_EFFORT=high
CODING_EFFORT=medium
REVIEW_EFFORT=xhigh
FAST_EFFORT=low
VISION_EFFORT=high
FALLBACK_EFFORT=low
```

### First real test after keys

```bash
python main.py system-health
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
```

Open first:

```text
outputs/<project_id>/READ_ME_FIRST.md
outputs/<project_id>/DECISION.md
outputs/<project_id>/NEXT_ACTIONS.md
outputs/<project_id>/proposal.md
outputs/<project_id>/screening_answers.md
outputs/<project_id>/QUALITY_GATE_REPORT.md
```

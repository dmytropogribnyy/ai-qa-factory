# Real Testing Preparation — v5.0.8

This checklist prepares AI QA Factory for real LLM runs and controlled real-site testing.

## 0. Test execution modes

### Unit / smoke tests (default — no API keys needed)

`tests/conftest.py` forces `LLM_MODE=mock` and `MODEL_PROFILE=mock` before any app config is loaded, regardless of what `.env` contains.

```bash
# Always safe — uses mock mode even if .env has real keys
python -m pytest -q

# Equivalent explicit form
LLM_MODE=mock MODEL_PROFILE=mock python -m pytest -q
```

### Real-LLM smoke tests (explicit shell override)

```bash
LLM_MODE=real MODEL_PROFILE=premium_hybrid python -m pytest -q
```

### Real runtime validation (recommended before client work)

```bash
python main.py system-health
python main.py prescreen --input sample_inputs/upwork_job.txt --source-platform upwork --require-real-llm
```

### LiteLLM botocore warnings

Warnings like `No module named 'botocore'` or `boto3 not found` are printed by LiteLLM when AWS Bedrock/SageMaker providers are not installed. They are **harmless** unless you actually use AWS Bedrock or SageMaker. They are suppressed automatically during `pytest`. Do not add `botocore` or `boto3` to `requirements.txt` unless you add an AWS provider.

## 1. Start with system health

```bash
python -m pytest -q
python main.py system-health
```

## 2. Configure API keys

Create `.env` in the project root next to `main.py`.

### Recommended premium hybrid profile

```env
LLM_MODE=real
MODEL_PROFILE=premium_hybrid

OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...

PERSISTENCE_BACKEND=json
```

This routes roles as follows:

| Role | Model |
|---|---|
| Architect / prescreen / strategy | `gpt-5.5` |
| Coding / Playwright / implementation notes | `anthropic/claude-sonnet-4-6` |
| Review / quality / self-health | `anthropic/claude-opus-4-7` |
| Fast proposals / summaries | `anthropic/claude-sonnet-4-6` |
| Vision / future screenshots | `gpt-5.5` |
| Fallback | `gpt-5.4-mini` |

### OpenAI-only fallback

```env
LLM_MODE=real
MODEL_PROFILE=openai_only
OPENAI_API_KEY=sk-...
```

### Anthropic-only fallback

```env
LLM_MODE=real
MODEL_PROFILE=anthropic_only
ANTHROPIC_API_KEY=sk-ant-...
```

## 3. Verify model routing

```bash
python main.py system-health
```

The report should show:

- `LLM mode = real`;
- selected `MODEL_PROFILE`;
- `ARCHITECT_MODEL`, `CODING_MODEL`, `REVIEW_MODEL`, `FAST_MODEL`, `VISION_MODEL`, `FALLBACK_MODEL`;
- effort settings;
- required API keys present.

## 4. First real LLM test

Use one saved Upwork job:

```bash
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
```

Then:

```bash
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
```

Open first:

```text
outputs/<project_id>/READ_ME_FIRST.md
outputs/<project_id>/DECISION.md
outputs/<project_id>/NEXT_ACTIONS.md
outputs/<project_id>/screening_answers.md
outputs/<project_id>/proposal.md
outputs/<project_id>/QUALITY_GATE_REPORT.md
```

## 5. Real-site testing readiness

Before testing any real site, prepare:

```text
target URL
staging/test environment if possible
test accounts and roles
allowed test boundary
critical flows
browser/device matrix
bug-report format
Loom/Jam/Linear/Jira access if needed
```

For billing/Stripe flows:

```text
Stripe sandbox/test mode
test cards
no real charges
predefined test organizations/users
```

For API testing:

```text
OpenAPI/Postman collection
base URL
test tokens
allowed endpoints
rate limits
```

## 6. Current limitations

Do not rely on these yet as autonomous inputs:

- URL-only autonomous inspection;
- screenshot-only visual analysis;
- automated login/recon without explicit credentials and scope;
- real payment or destructive flows;
- automatic platform scraping or proposal submission.

Future adapters:

```text
URLIntakeAdapter
ScreenshotIntakeAdapter
PlaywrightReconAgent
VisionReviewAgent
```

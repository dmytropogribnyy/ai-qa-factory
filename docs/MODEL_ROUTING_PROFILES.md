# Model Routing Profiles — v5.0.8

AI QA Factory does **not** use one model for everything.

It uses role-based routing through `core/llm_router.py` and `core/config.py`:

| Role alias | Main purpose | Recommended premium model |
|---|---|---|
| `architect` | prescreening, opportunity routing, capability decisions, QA strategy | `gpt-5.5` |
| `coding` | Playwright scaffold notes, code-related generation, API/test implementation notes | `anthropic/claude-sonnet-4-6` |
| `review` | quality gate, deep review, risk critique, self-health checks | `anthropic/claude-opus-4-7` |
| `fast` | proposal drafts, summaries, delivery notes, quick documentation | `anthropic/claude-sonnet-4-6` |
| `vision` | future screenshot / visual review / UI recon | `gpt-5.5` |
| `fallback` | backup model if primary route fails | `gpt-5.4-mini` |

## Recommended profile for Dmytro

Use this once both OpenAI and Anthropic API keys are configured:

```env
LLM_MODE=real
MODEL_PROFILE=premium_hybrid

OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

This expands internally to:

```env
ARCHITECT_MODEL=gpt-5.5
CODING_MODEL=anthropic/claude-sonnet-4-6
REVIEW_MODEL=anthropic/claude-opus-4-7
FAST_MODEL=anthropic/claude-sonnet-4-6
VISION_MODEL=gpt-5.5
FALLBACK_MODEL=gpt-5.4-mini
```

Reasoning/adaptive effort defaults:

```env
ARCHITECT_EFFORT=high
CODING_EFFORT=medium
REVIEW_EFFORT=xhigh
FAST_EFFORT=low
VISION_EFFORT=high
FALLBACK_EFFORT=low
```

## Other profiles

### OpenAI only

Use when only `OPENAI_API_KEY` is configured:

```env
LLM_MODE=real
MODEL_PROFILE=openai_only
OPENAI_API_KEY=sk-...
```

### Anthropic only

Use when only `ANTHROPIC_API_KEY` is configured:

```env
LLM_MODE=real
MODEL_PROFILE=anthropic_only
ANTHROPIC_API_KEY=sk-ant-...
```

### Budget

Use for low-cost calibration or large batches:

```env
LLM_MODE=real
MODEL_PROFILE=budget
OPENAI_API_KEY=sk-...
```

## Manual overrides

Any profile value can be overridden directly:

```env
ARCHITECT_MODEL=gpt-5.5
CODING_MODEL=anthropic/claude-sonnet-4-6
REVIEW_MODEL=anthropic/claude-opus-4-7
FAST_MODEL=anthropic/claude-sonnet-4-6
VISION_MODEL=gpt-5.5
FALLBACK_MODEL=gpt-5.4-mini
```

## Safety behavior

- Mock mode remains the default and never calls paid APIs.
- `--require-real-llm` fails if `LLM_MODE=mock` unless `--allow-mock` is explicitly passed.
- The router logs model alias, model name, fallback usage, token usage, cost if available, and reasoning effort.
- If a provider rejects optional effort parameters, the router retries the same model without optional parameters before falling back.
- Claude Opus 4.7 is not used as the everyday coding model. It is reserved for deep review and complex reasoning.

## Quick verification

```bash
python main.py system-health
```

Check that the report shows:

- `MODEL_PROFILE=premium_hybrid` or your selected profile;
- the expected role model IDs;
- required API keys present for selected providers;
- effort values per role.

# v5.0.8 Model Routing Notes

This release synchronizes the code and documentation around role-based LLM routing.

Key additions:

- `MODEL_PROFILE` support: `mock`, `premium_hybrid`, `openai_only`, `anthropic_only`, `budget`.
- Premium hybrid routing: GPT-5.5 for architecture/reasoning, Claude Sonnet 4.6 for coding/fast drafting, Claude Opus 4.7 for deep review.
- Per-role effort settings: `ARCHITECT_EFFORT`, `CODING_EFFORT`, `REVIEW_EFFORT`, `FAST_EFFORT`, `VISION_EFFORT`, `FALLBACK_EFFORT`.
- System health reports selected model profile, model IDs, effort values and required provider keys.
- LLM router retries safely without optional effort params if a provider rejects them.

See `docs/MODEL_ROUTING_PROFILES.md`.

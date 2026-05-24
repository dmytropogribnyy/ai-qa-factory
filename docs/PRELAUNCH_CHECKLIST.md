# Pre-Launch Checklist

Before using with a real Upwork client:

1. Run `python -m pytest -q`.
2. Run `python main.py upwork --input sample_inputs/upwork_job.txt`.
3. Configure real LLM models in `.env` before client-facing proposals.
4. Use `--require-real-llm` for real jobs.
5. Manually edit every proposal.
6. Never run generated tests against production without explicit approval.
7. Check `QUALITY_GATE_REPORT.md` and `HUMAN_REVIEW_REQUIRED.md`.
8. Keep first milestone small: audit, smoke suite, flaky fix, migration sample.

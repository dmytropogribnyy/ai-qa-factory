# Global Audit and Real Testing Readiness — v5.0.8

## What is covered now

- Opportunity pre-screening from copied text / brief.
- Batch filtering for folders of job texts.
- Multi-platform routing with source hints.
- Capability routing beyond Playwright.
- Commercial strategy / pricing as negotiation guidance.
- Screening answers and evidence requirements.
- Human-readable control pack.
- Step / dry-run / only / from-step execution modes.
- Project extension pack suggestions.
- Self-health report and safe repair plan.
- Test strategy / test plan / test case generation.
- Playwright scaffold and safe test runner.

## What is intentionally not automatic yet

- No platform scraping.
- No auto-application submission.
- No URL-only or screenshot-only full commitment.
- No autonomous client-site testing.
- No destructive testing, real payments, or unauthorized security probing.
- No automatic GitHub push.
- No full web UI / dashboard.

## What is needed for real website testing

1. Real LLM configuration in `.env`.
2. Target URL and explicit testing boundary.
3. Staging/test environment where possible.
4. Test accounts and role matrix.
5. Payment sandbox/test cards for billing flows.
6. API docs or Postman/OpenAPI if API testing is expected.
7. Bug-reporting destination: Linear/Jira/Google Doc.
8. Screen recording tool if client expects Loom/Jam evidence.
9. Device/browser matrix.
10. Human approval before any real-site execution.

## Suggested next validation order

1. `python main.py system-health`
2. `python main.py batch-filter --input real_jobs/ --allow-mock`
3. `python main.py prescreen --input real_jobs/best_job.txt --source-platform upwork --allow-mock`
4. Configure real LLM.
5. `python main.py upwork --input real_jobs/best_job.txt --source-platform upwork --require-real-llm`
6. Review generated proposal/screening/evidence pack manually.
7. Only then test controlled demo/local sites.

## Remaining future adapters

- `URLIntakeAdapter` for safe page metadata capture.
- `ScreenshotIntakeAdapter` with vision model support.
- `PlaywrightReconAgent` for approved staging/demo UI snapshots.
- `EvidenceLibraryManager` for selecting real bug reports / Loom examples.
- `ExtensionPackActivator` for approved project-scoped prompt/checklist activation.

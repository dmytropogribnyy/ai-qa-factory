# v5.0.8 Model Routing Profiles Notes

v5.0.8 is a synchronization and readiness release.

It does not introduce a new architecture. It aligns the codebase and documentation around the current operating model:

- opportunity pre-screening before work commitment;
- human-readable reporting first;
- approvals before client-facing or real-site actions;
- broad capability routing with focused execution;
- project-specific extension packs;
- safe self-health monitoring;
- test strategy / test plan / test cases generation;
- multi-platform opportunity routing;
- clear real-testing preparation rules.

## Main code-level confirmations

- `system-health` is the local readiness command.
- `prescreen` is the first command for uncertain opportunities.
- `batch-filter` is the first command for many copied jobs.
- `--source-platform` can be used when the text has no platform metadata.
- `--project-id` can be used for saved project re-runs with `--only` / `--from-step`.

## Main documentation additions

- `OPPORTUNITY_PRESCREENING_APPROVAL_FLOW.md`
- `REAL_TESTING_PREPARATION.md`
- this sync note

## Recommended first real test sequence

```bash
python main.py system-health
python main.py batch-filter --input real_jobs/ --allow-mock
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --allow-mock
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
```

# Recommended Local Usage in VS Code

1. Open this folder in VS Code.
2. Create and activate a Python virtual environment.
3. Install dependencies.
4. Run CLI commands from the integrated terminal.
5. Review outputs in `outputs/{project_id}/`.
6. Copy approved proposals/reports into Upwork/client messages.

Suggested flow:

```bash
python main.py prescreen --input sample_inputs/upwork_job.txt --auto
python main.py scaffold --input sample_inputs/client_brief.txt
python main.py review --input sample_inputs/test_to_review.ts
```

## Archive and sharing hygiene

When creating a zip or archive to share:

**Exclude these paths:**

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

**Do not share archives containing `.env` or generated outputs.** If an archive containing `.env` was shared externally, rotate all API keys immediately (OpenAI, Anthropic, any others present in `.env`).

A safe archive includes: source code, `sample_inputs/`, `docs/`, `tests/`, `requirements.txt`, `README.md`, `.env.example`. It does not include secrets, virtual environments, or generated run artifacts.

"""
Phase 5H — CLI tool: fetch task source issues and derive test scenarios.

Usage:
  python tools/fetch_task_source.py \\
    --project-id my-project \\
    --provider linear \\
    --token-env-var LINEAR_API_TOKEN \\
    --team-key ENG \\
    --approve-task-source-integration

  python tools/fetch_task_source.py \\
    --project-id my-project \\
    --provider linear \\
    --token-env-var LINEAR_API_TOKEN \\
    --issue-ids QA-123 QA-124 \\
    --approve-task-source-integration

SAFETY:
- --token-env-var accepts an env var NAME only — never a raw token value.
- No writeback. No status changes. No comments.
- Linear is a task source (requirements input), NOT an app-under-test.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Raw value patterns: reject if token looks like an actual secret
_BLOCKED_FLAGS = (
    "--token", "--api-key", "--secret", "--password",
    "--linear-token", "--bearer",
)

_BLOCKED_ENV_VAR_SUBSTRINGS = (
    "lin_api_", "xoxb-", "xoxp-", "ghp_", "gho_", "Bearer ", "eyJ",
)


def _check_blocked_flags(argv: list) -> None:
    for flag in argv:
        flag_lower = flag.lower()
        for blocked in _BLOCKED_FLAGS:
            # Match exact flag or flag=value, but not prefix-of-longer-flag
            # e.g. --token matches --token=val but NOT --token-env-var
            if flag_lower == blocked or flag_lower.startswith(blocked + "="):
                print(f"[BLOCKED] Flag '{blocked}' is not allowed. "
                      f"Pass an env var NAME via --token-env-var (e.g. LINEAR_API_TOKEN).",
                      file=sys.stderr)
                sys.exit(2)


def main() -> None:
    _check_blocked_flags(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Phase 5H: Fetch task source issues and derive test scenarios."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--provider", default="linear",
                        choices=["linear"],
                        help="Task source provider (default: linear)")
    parser.add_argument("--token-env-var", required=True,
                        help="Name of env var holding the API token (e.g. LINEAR_API_TOKEN)")
    parser.add_argument("--team-key",
                        help="Linear team key (e.g. ENG, QA). Used when fetching by team.")
    parser.add_argument("--issue-ids", nargs="+",
                        help="Specific issue IDs to fetch (e.g. QA-123 QA-124)")
    parser.add_argument("--max-issues", type=int, default=50,
                        help="Maximum issues to fetch (max 50, default 50)")
    parser.add_argument("--approve-task-source-integration", action="store_true",
                        help="Confirm read-only access to client task board")
    parser.add_argument("--no-write", action="store_true",
                        help="Skip writing artifacts to outputs/")

    args = parser.parse_args()

    # Safety: reject if token_env_var looks like a raw value
    tev = args.token_env_var.strip()
    for substr in _BLOCKED_ENV_VAR_SUBSTRINGS:
        if substr.lower() in tev.lower():
            print(f"[BLOCKED] --token-env-var '{tev}' looks like a raw token value. "
                  "Pass the env var NAME (e.g. LINEAR_API_TOKEN), not the token itself.",
                  file=sys.stderr)
            sys.exit(2)

    from core.task_source_fetcher import TaskSourceFetcher
    outputs_root = Path("outputs")
    fetcher = TaskSourceFetcher(outputs_root=outputs_root)

    report = fetcher.fetch(
        project_id=args.project_id,
        provider=args.provider,
        token_env_var=tev,
        team_key=args.team_key or "",
        issue_ids=args.issue_ids,
        max_issues=args.max_issues,
        approve_task_source_integration=args.approve_task_source_integration,
        write=not args.no_write,
    )

    print(f"Status:           {report.status}")
    print(f"Provider:         {report.provider}")
    print(f"Issues fetched:   {report.issues_fetched}")
    print(f"Scenarios:        {len(report.scenarios)}")
    if report.blockers:
        print("\nBlockers:")
        for b in report.blockers:
            print(f"  - {b}")
    if report.artifacts_written:
        print("\nArtifacts written:")
        for a in report.artifacts_written:
            print(f"  {a}")

    sys.exit(0 if report.status == "success" else 1)


if __name__ == "__main__":
    main()

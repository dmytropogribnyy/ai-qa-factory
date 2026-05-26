"""CLI: run_dedicated_auth.py — Phase 5AB Approved Dedicated Test-Account Auth Execution.

Runs approval-gated auth smoke against a dedicated test-account target.
No raw secret values accepted through CLI args.
No personal accounts. No production accounts.
No Google OAuth. No Alza/Amazon/LinkedIn/Upwork.
No .env reading. No storageState reading.

Usage:

  # Preview (no execution, no env var reading):
  python tools/run_dedicated_auth.py --project-id demo-5ab

  # Approved dedicated auth smoke (OrangeHRM):
  python tools/run_dedicated_auth.py --project-id demo-5ab \\
      --approve-dedicated-auth-execution \\
      --scenario-lane dedicated_test_account_auth_future \\
      --target-category orangehrm_demo_auth \\
      --target-url https://opensource-demo.orangehrmlive.com \\
      --username-env-var QA_TEST_USERNAME \\
      --password-env-var QA_TEST_PASSWORD \\
      --dedicated-test-account-confirmed \\
      --staging-environment-confirmed \\
      --command-mode auth_smoke

  # Approved staging client env:
  python tools/run_dedicated_auth.py --project-id demo-5ab \\
      --approve-dedicated-auth-execution \\
      --scenario-lane staging_client_app_future \\
      --target-category staging \\
      --target-url https://staging.example.com \\
      --username-env-var QA_TEST_USERNAME \\
      --password-env-var QA_TEST_PASSWORD \\
      --dedicated-test-account-confirmed \\
      --client-scope-confirmed \\
      --command-mode auth_smoke

  # JSON output:
  python tools/run_dedicated_auth.py --project-id demo-5ab --json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))


def main(argv: Optional[List[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description=(
            "Phase 5AB: Approved dedicated test-account auth execution. "
            "No raw secrets in CLI args. No personal/production accounts."
        )
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--scaffold-root", default=None)
    parser.add_argument("--from-output", action="store_true")
    parser.add_argument("--approve-dedicated-auth-execution", action="store_true")
    parser.add_argument("--scenario-lane", default="")
    parser.add_argument("--target-category", default="")
    parser.add_argument("--target-url", default=None)
    parser.add_argument("--username-env-var", default=None)
    parser.add_argument("--password-env-var", default=None)
    parser.add_argument("--token-env-var", default=None)
    parser.add_argument("--dedicated-test-account-confirmed", action="store_true")
    parser.add_argument("--staging-environment-confirmed", action="store_true")
    parser.add_argument("--client-scope-confirmed", action="store_true")
    parser.add_argument("--personal-account-confirmed", action="store_true")
    parser.add_argument("--production-account-confirmed", action="store_true")
    parser.add_argument("--command-mode", default="auth_smoke",
                        choices=["auth_smoke", "auth_setup"])
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--outputs-root", default="outputs")

    args, unknown = parser.parse_known_args(argv)

    # Reject any unknown args that look like raw secret flags
    if unknown:
        print("ERROR: Unexpected arguments detected.")
        for u in unknown:
            if any(kw in u.lower() for kw in
                   ["--password", "--username", "--token", "--secret", "--api-key", "--key"]):
                print(f"  BLOCKED: '{u}' looks like a raw secret flag. "
                      "Use --username-env-var / --password-env-var with env var NAMES only.")
            else:
                print(f"  Unknown argument: '{u}'")
        return 2

    from core.dedicated_auth_runner import DedicatedAuthRunner

    scaffold_root = (
        Path(args.scaffold_root) if args.scaffold_root else None
    )

    runner = DedicatedAuthRunner(outputs_root=Path(args.outputs_root))

    report = runner.run_dedicated_auth(
        project_id=args.project_id,
        approve_dedicated_auth_execution=args.approve_dedicated_auth_execution,
        scenario_lane=args.scenario_lane,
        target_category=args.target_category,
        target_url=args.target_url,
        username_env_var=args.username_env_var,
        password_env_var=args.password_env_var,
        token_env_var=args.token_env_var,
        dedicated_test_account_confirmed=args.dedicated_test_account_confirmed,
        staging_environment_confirmed=args.staging_environment_confirmed,
        client_scope_confirmed=args.client_scope_confirmed,
        personal_account_confirmed=args.personal_account_confirmed,
        production_account_confirmed=args.production_account_confirmed,
        command_mode=args.command_mode,
        scaffold_root=scaffold_root,
        timeout=args.timeout,
    )

    if args.json_output:
        print(json.dumps(report.to_dict(), indent=2))
        return 0 if report.execution_status not in ("blocked", "error") else 1

    _print_report(report)
    _print_safety_boundary()

    return 0 if report.execution_status not in ("blocked", "error") else 1


def _print_report(report: object) -> None:
    print("Dedicated Auth Execution — Phase 5AB")
    print(f"  project_id:        {report.project_id}")
    print(f"  status:            {report.execution_status.upper()}")
    print(f"  approved:          {report.approved}")
    print(f"  scenario_lane:     {report.scenario_lane or '(none)'}")
    print(f"  target_category:   {report.target_category or '(none)'}")
    print(f"  target_url:        {report.target_url or '(none)'}")

    if report.blockers:
        print("\nBlockers:")
        for b in report.blockers:
            print(f"  BLOCKED: {b}")

    if report.notes:
        print("\nNotes:")
        for n in report.notes:
            print(f"  {n}")

    if getattr(report, "commands", []):
        print("\nCommands:")
        for cmd in report.commands:
            print(f"  [{cmd.status}] {cmd.command}")
            print(f"    exit_code={cmd.exit_code}  duration={cmd.duration_seconds}s")
            if cmd.stdout_excerpt:
                print(f"    stdout: {cmd.stdout_excerpt[:200]}")
            if cmd.stderr_excerpt:
                print(f"    stderr: {cmd.stderr_excerpt[:200]}")

    if getattr(report, "session_artifacts", []):
        print("\nSession artifacts:")
        for a in report.session_artifacts:
            print(f"  {a.artifact_type}: {a.path}")
            print(f"    internal_only={a.internal_only}  approved_for_commit={a.approved_for_commit}")

    print()
    print(f"  raw_credentials_logged:      {report.raw_credentials_logged}")
    print(f"  raw_credentials_serialized:  {report.raw_credentials_serialized}")
    print(f"  personal_account_used:       {report.personal_account_used}")
    print(f"  production_account_used:     {report.production_account_used}")
    print(f"  safe_to_deliver:             {report.safe_to_deliver}")
    print(f"  approved_for_client_delivery:{report.approved_for_client_delivery}")


def _print_safety_boundary() -> None:
    print("\nSafety boundary:")
    print("  No raw secret values accepted through CLI args.")
    print("  No .env files read.")
    print("  No existing storageState files read.")
    print("  No personal accounts allowed.")
    print("  No production accounts allowed.")
    print("  Google OAuth (accounts.google.com) strictly blocked.")
    print("  Alza/Amazon/LinkedIn/Upwork strictly blocked.")
    print("  No payment/checkout/order/scraping/crawling/load/security.")
    print("  safe_to_deliver=False. approved_for_client_delivery=False.")


if __name__ == "__main__":
    sys.exit(main())

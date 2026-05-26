"""
Phase 5E — API Auth Smoke CLI.

Approval-gated: requires --approve-api-auth-execution.
Accepts env var NAMES only — never raw credential values as CLI args.

Example:
    python tools/run_api_auth_smoke.py \\
        --project-id restful-booker-api-smoke \\
        --approve-api-auth-execution \\
        --target-profile restful_booker_public_api \\
        --username-env-var RESTFUL_BOOKER_USERNAME \\
        --password-env-var RESTFUL_BOOKER_PASSWORD
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.api_auth_runner import APIAuthRunner


def _print_report(report, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
        return

    status_sym = "PASSED" if report.execution_status == "passed" else (
        "BLOCKED" if report.execution_status == "blocked" else
        "FAILED" if report.execution_status == "failed" else report.execution_status.upper()
    )

    print("\nAPI Auth Execution — Phase 5E")
    print(f"  project_id:      {report.project_id}")
    print(f"  status:          {status_sym}")
    print(f"  approved:        {report.approved}")
    print(f"  target_profile:  {report.target_profile}")
    print(f"  base_url:        {report.base_url}")

    if report.blockers:
        print("\nBlockers:")
        for b in report.blockers:
            print(f"  BLOCKED: {b}")

    if report.notes:
        print("\nNotes:")
        for n in report.notes:
            print(f"  {n}")

    if report.commands:
        print("\nCommands:")
        for c in report.commands:
            sym = "[passed]" if c.status == "passed" else f"[{c.status}]"
            print(f"  {sym} {c.method} {c.url}")
            print(f"    http_code={c.status_code}  token_present={c.token_present}  duration={c.duration_seconds}s")
            if c.stdout_excerpt:
                print(f"    response: {c.stdout_excerpt[:200]}")
            if c.stderr_excerpt:
                print(f"    error: {c.stderr_excerpt[:200]}")

    print(f"\n  raw_credentials_logged:      {report.raw_credentials_logged}")
    print(f"  raw_credentials_serialized:  {report.raw_credentials_serialized}")
    print(f"  token_logged:                {report.token_logged}")
    print(f"  token_serialized:            {report.token_serialized}")
    print(f"  personal_account_used:       {report.personal_account_used}")
    print(f"  production_account_used:     {report.production_account_used}")
    print(f"  safe_to_deliver:             {report.safe_to_deliver}")
    print(f"  approved_for_client_delivery:{report.approved_for_client_delivery}")
    print()
    print("Safety boundary:")
    print("  No raw secret values accepted through CLI args.")
    print("  Credentials sent as HTTP request body — not in URL, headers, or logs.")
    print("  Token value masked in all artifacts — only presence recorded.")
    print("  No .env files read.")
    print("  No personal accounts allowed.")
    print("  No production accounts allowed.")
    print("  Google OAuth (accounts.google.com) strictly blocked.")
    print("  Alza/Amazon/LinkedIn/Upwork strictly blocked.")
    print("  No DELETE / destructive writes in Phase 5E.")
    print("  safe_to_deliver=False. approved_for_client_delivery=False.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 5E — API Auth Smoke Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument(
        "--approve-api-auth-execution",
        action="store_true",
        default=False,
        help="Approval gate. Without this: no env lookup, no network calls.",
    )
    parser.add_argument(
        "--target-profile",
        default="",
        help="API target profile name (e.g. restful_booker_public_api)",
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help="Optional base URL override (default: from profile)",
    )
    parser.add_argument(
        "--username-env-var",
        default=None,
        metavar="ENV_VAR_NAME",
        help="Name of env var holding the username (e.g. RESTFUL_BOOKER_USERNAME)",
    )
    parser.add_argument(
        "--password-env-var",
        default=None,
        metavar="ENV_VAR_NAME",
        help="Name of env var holding the password (e.g. RESTFUL_BOOKER_PASSWORD)",
    )
    parser.add_argument(
        "--no-read-check",
        action="store_true",
        default=False,
        help="Skip optional safe GET read check after auth",
    )
    parser.add_argument("--outputs-root", default="outputs")
    parser.add_argument("--json", action="store_true", default=False)

    # Blocked raw secret flags — detected and rejected
    for blocked_flag in ("--password", "--username", "--token", "--secret", "--api-key"):
        if blocked_flag in sys.argv:
            print(
                f"ERROR: '{blocked_flag}' is blocked. "
                "Pass env var NAME via --username-env-var / --password-env-var. "
                "Never pass raw secret values as CLI args.",
                file=sys.stderr,
            )
            return 2

    args = parser.parse_args()

    runner = APIAuthRunner(outputs_root=Path(args.outputs_root))
    report = runner.run_api_auth(
        project_id=args.project_id,
        approve_api_auth_execution=args.approve_api_auth_execution,
        target_profile=args.target_profile,
        base_url=args.base_url,
        username_env_var=args.username_env_var,
        password_env_var=args.password_env_var,
        run_safe_read_check=not args.no_read_check,
    )

    _print_report(report, as_json=args.json)

    return 0 if report.execution_status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())

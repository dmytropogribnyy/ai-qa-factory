"""
Phase 7D — Email/Password Auth Runner CLI.

Usage:
  python tools/run_email_password_smoke.py --project-id <id> [options]

Safety:
  - Raw secrets NEVER accepted via CLI flags.
  - Credentials read from env vars by Node.js subprocess only.
  - Personal/production accounts blocked.
  - CAPTCHA bypass blocked.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

# ---------------------------------------------------------------------------
# Blocked-flag guard — must run BEFORE argparse so no secret ever touches argv
# ---------------------------------------------------------------------------
_BLOCKED_FLAGS = (
    "--username",
    "--password",
    "--secret",
    "--token",
    "--cookie",
    "--access-token",
    "--bearer",
    "--client-secret",
)

for _arg in sys.argv[1:]:
    for _blocked in _BLOCKED_FLAGS:
        if _arg == _blocked or _arg.startswith(_blocked + "="):
            print(
                f"[7D] BLOCKED: '{_blocked}' is not accepted. "
                "Set credentials as OS-level env vars only — never via CLI flags.",
                file=sys.stderr,
            )
            sys.exit(1)

# ---------------------------------------------------------------------------
# Imports (after guard)
# ---------------------------------------------------------------------------
from core.email_password_runner import EmailPasswordRunner  # noqa: E402
from core.schemas.email_password import (  # noqa: E402
    ORANGEHRM_DEFAULT_LOGIN_URL,
    ORANGEHRM_DEFAULT_SUCCESS_URL,
    EmailPasswordInputs,
)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Phase 7D — Email/Password Auth Smoke (OrangeHRM demo)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Plan only (check env var presence):
  python tools/run_email_password_smoke.py --project-id my-proj

  # Execute smoke (env vars must be set at OS level):
  python tools/run_email_password_smoke.py --project-id my-proj \\
    --dedicated-test-account-confirmed --approve-execution

Safety: --username / --password / --secret / --token / --cookie are blocked.
Set ORANGEHRM_USERNAME and ORANGEHRM_PASSWORD at the OS level instead.
        """,
    )
    p.add_argument("--project-id", required=True, help="Project identifier")
    p.add_argument(
        "--target-name",
        default="orangehrm_demo",
        help="Target site name (default: orangehrm_demo)",
    )
    p.add_argument(
        "--login-url",
        default=ORANGEHRM_DEFAULT_LOGIN_URL,
        help="Login page URL (must start with https:// or http://localhost)",
    )
    p.add_argument(
        "--success-url",
        default=ORANGEHRM_DEFAULT_SUCCESS_URL,
        help="URL or path suffix expected after successful login",
    )
    p.add_argument(
        "--username-env-var",
        default="ORANGEHRM_USERNAME",
        help="Name of env var holding username (default: ORANGEHRM_USERNAME)",
    )
    p.add_argument(
        "--password-env-var",
        default="ORANGEHRM_PASSWORD",
        help="Name of env var holding password (default: ORANGEHRM_PASSWORD)",
    )
    p.add_argument(
        "--account-label",
        default="",
        help="Human-readable label for the test account (e.g. 'demo-admin')",
    )
    p.add_argument(
        "--dedicated-test-account-confirmed",
        action="store_true",
        help="Confirm credentials belong to a dedicated test account",
    )
    p.add_argument(
        "--approve-execution",
        action="store_true",
        help="Approve actual browser smoke execution",
    )
    p.add_argument(
        "--outputs-root",
        default="outputs",
        help="Root directory for output artifacts (default: outputs)",
    )
    p.add_argument(
        "--plan-only",
        action="store_true",
        help="Print plan JSON and exit without running smoke",
    )
    p.add_argument(
        "--json",
        action="store_true",
        dest="output_json",
        help="Print result as JSON instead of human-readable summary",
    )
    return p


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    inputs = EmailPasswordInputs(
        project_id=args.project_id,
        target_name=args.target_name,
        login_url=args.login_url,
        success_url=args.success_url,
        username_env_var=args.username_env_var,
        password_env_var=args.password_env_var,
        account_label=args.account_label,
        dedicated_test_account_confirmed=args.dedicated_test_account_confirmed,
        approve_execution=args.approve_execution,
    )

    runner = EmailPasswordRunner(outputs_root=Path(args.outputs_root))

    if args.plan_only:
        plan = runner.build_plan(inputs)
        print(json.dumps(plan.to_dict(), indent=2, default=str))
        sys.exit(0)

    plan = runner.build_plan(inputs)
    result = runner.run(inputs)
    artifact_paths = runner.render_artifacts(plan, result, args.project_id)

    if args.output_json:
        print(json.dumps(result.to_dict(), indent=2, default=str))
    else:
        print(f"\n[7D] Email/Password Auth Smoke — {args.project_id}")
        print(f"  Target  : {result.target_name}")
        print(f"  Status  : {result.status.value.upper()}")
        print(f"  Login   : {result.login_url}")
        print(f"  Account : {result.account_label or '(none)'}")
        print(f"  Duration: {result.duration_seconds}s")
        print(f"\n  Auth coverage: {result.auth_coverage_summary}")

        if result.blockers:
            print("\n  Blockers:")
            for b in result.blockers:
                print(f"    - {b}")

        if result.notes:
            print("\n  Notes:")
            for n in result.notes:
                print(f"    - {n}")

        if artifact_paths:
            print("\n  Artifacts:")
            for k, v in artifact_paths.items():
                print(f"    {k}: {v}")

    status = result.status.value
    sys.exit(0 if status in ("passed", "planning_only") else 1)


if __name__ == "__main__":
    main()

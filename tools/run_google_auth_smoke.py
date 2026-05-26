"""
Phase 5G — Read-only Google Auth Smoke CLI.

Loads a previously captured storageState and runs a read-only smoke check:
navigate to the target URL, verify response, optionally take a screenshot.

No content extraction, no email/file reads, no admin actions, no CAPTCHA bypass.

Usage:

    python tools/run_google_auth_smoke.py \\
        --project-id my-google-smoke \\
        --approve-google-test-account \\
        --google-test-account-confirmed \\
        --dedicated-test-account-confirmed \\
        --auth-mode storage_state_reuse \\
        --storage-state-path outputs/my-google-smoke/15_google_auth/.auth/google-storageState.json \\
        --target-url https://myaccount.google.com
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.google_auth_runner import GoogleAuthRunner

_BLOCKED_FLAGS = (
    "--password",
    "--secret",
    "--token",
    "--api-key",
    "--cookie",
    "--username",
    "--email",
    "--service-account-json",
    "--totp-seed",
)


def _check_blocked_flags(argv) -> None:
    for arg in argv:
        for bf in _BLOCKED_FLAGS:
            if arg == bf or arg.startswith(bf + "="):
                print(
                    f"ERROR: raw-secret flag {bf} is never accepted by Phase 5G smoke. "
                    "Only env var name references and storageState paths are permitted.",
                    file=sys.stderr,
                )
                sys.exit(2)


def main() -> int:
    _check_blocked_flags(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Phase 5G — Read-only Google auth smoke with storageState reuse",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--outputs-root", default="outputs")
    parser.add_argument(
        "--auth-mode",
        default="storage_state_reuse",
        choices=("storage_state_reuse",),
        help="Only storage_state_reuse is executable in Phase 5G",
    )
    parser.add_argument("--storage-state-path", required=True)
    parser.add_argument("--target-url", required=True)
    parser.add_argument(
        "--target-kind",
        default="google_account_ui",
        choices=("google_account_ui", "sign_in_with_google_oauth"),
    )
    parser.add_argument("--account-email-label", default="")
    parser.add_argument("--approve-google-test-account", action="store_true", default=False)
    parser.add_argument("--google-test-account-confirmed", action="store_true", default=False)
    parser.add_argument("--dedicated-test-account-confirmed", action="store_true", default=False)
    parser.add_argument("--personal-account-confirmed", action="store_true", default=False)
    parser.add_argument("--production-account-confirmed", action="store_true", default=False)
    parser.add_argument("--timeout-seconds", type=int, default=90)
    parser.add_argument("--json", action="store_true", default=False)

    args = parser.parse_args()

    runner = GoogleAuthRunner(outputs_root=Path(args.outputs_root))

    report = runner.run_storage_state_smoke(
        project_id=args.project_id,
        target_url=args.target_url,
        storage_state_path=args.storage_state_path,
        approve_google_test_account=args.approve_google_test_account,
        google_test_account_confirmed=args.google_test_account_confirmed,
        dedicated_test_account_confirmed=args.dedicated_test_account_confirmed,
        personal_account_confirmed=args.personal_account_confirmed,
        production_account_confirmed=args.production_account_confirmed,
        account_email_label=args.account_email_label,
        target_kind=args.target_kind,
        timeout_seconds=args.timeout_seconds,
    )

    runner.render_evidence_artifacts(report, args.project_id)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print("\nPhase 5G — Google Auth Smoke")
        print(f"  auth_mode:           {report.auth_mode}")
        print(f"  execution_performed: {report.execution_performed}")
        print(f"  target_url:          {report.target_url}")
        print(f"  duration_seconds:    {report.duration_seconds}")
        if report.smoke_results:
            print("\nResults:")
            for r in report.smoke_results:
                print(f"  - {r}")
        print("\nSafety boundary:")
        print(f"  storage_state_content_read:   {report.storage_state_content_read}")
        print(f"  cookies_logged:               {report.cookies_logged}")
        print(f"  tokens_logged:                {report.tokens_logged}")
        print(f"  captcha_bypass_attempted:     {report.captcha_bypass_attempted}")
        print(f"  anti_bot_bypass_attempted:    {report.anti_bot_bypass_attempted}")
        print(f"  safe_to_deliver:              {report.safe_to_deliver}")
        print(f"  approved_for_client_delivery: {report.approved_for_client_delivery}")
        if report.notes:
            print("\nNotes:")
            for n in report.notes:
                print(f"  - {n}")

    return 0 if report.execution_performed else 1


if __name__ == "__main__":
    sys.exit(main())

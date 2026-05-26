"""
Phase 5G — Approved Manual Google Storage State Capture CLI.

Opens a Playwright-driven Chromium for the USER to manually log into the
dedicated Google test account. Does NOT automate password entry, does NOT
bypass CAPTCHA or 2FA challenges. Saves storageState to:

    outputs/<project_id>/15_google_auth/.auth/google-storageState.json

The path is .gitignored. Content is never read or printed by this tool.

Usage:

    python tools/capture_google_storage_state.py \\
        --project-id my-google-smoke \\
        --approve-google-test-account \\
        --google-test-account-confirmed \\
        --dedicated-test-account-confirmed \\
        --account-email-label danrobinson_artist_gmail \\
        --target-url https://accounts.google.com

DO NOT pass --personal-account-confirmed or --production-account-confirmed.
DO NOT pass raw secrets via CLI — none are accepted.
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
                    f"ERROR: raw-secret flag {bf} is never accepted. "
                    "Login is manual — type credentials in the browser, not on the CLI.",
                    file=sys.stderr,
                )
                sys.exit(2)


def main() -> int:
    _check_blocked_flags(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Phase 5G — Manual Google storageState capture (browser opens, user logs in)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--outputs-root", default="outputs")
    parser.add_argument("--target-url", default="https://accounts.google.com",
                        help="Allowlisted Google target URL prefix")
    parser.add_argument("--account-email-label", default="",
                        help="Display label for the dedicated test account (NOT the email value)")
    parser.add_argument("--approve-google-test-account", action="store_true", default=False)
    parser.add_argument("--google-test-account-confirmed", action="store_true", default=False)
    parser.add_argument("--dedicated-test-account-confirmed", action="store_true", default=False)
    parser.add_argument("--personal-account-confirmed", action="store_true", default=False,
                        help="If set, capture is blocked. Use only the dedicated test account.")
    parser.add_argument("--production-account-confirmed", action="store_true", default=False,
                        help="If set, capture is blocked. Use only the dedicated test account.")
    parser.add_argument("--timeout-seconds", type=int, default=300,
                        help="Max time to wait for the user to finish login (default: 300s)")
    parser.add_argument("--json", action="store_true", default=False)

    args = parser.parse_args()

    runner = GoogleAuthRunner(outputs_root=Path(args.outputs_root))

    print("Phase 5G — Manual Google storageState capture")
    print("  Browser will open. Log in MANUALLY with the dedicated Google test account.")
    print("  Solve any CAPTCHA/2FA challenge yourself. Do NOT use personal accounts.")
    print("  Close the browser window when login is fully complete to save the session.\n")

    report = runner.capture_storage_state(
        project_id=args.project_id,
        target_url=args.target_url,
        approve_google_test_account=args.approve_google_test_account,
        google_test_account_confirmed=args.google_test_account_confirmed,
        dedicated_test_account_confirmed=args.dedicated_test_account_confirmed,
        personal_account_confirmed=args.personal_account_confirmed,
        production_account_confirmed=args.production_account_confirmed,
        account_email_label=args.account_email_label,
        timeout_seconds=args.timeout_seconds,
    )

    runner.render_evidence_artifacts(report, args.project_id)

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, default=str))
    else:
        print("\nResult:")
        print(f"  auth_mode:               {report.auth_mode}")
        print(f"  execution_performed:     {report.execution_performed}")
        print(f"  storage_state_captured:  {report.storage_state_captured}")
        print(f"  storage_state_path:      {report.storage_state_path}")
        print(f"  duration_seconds:        {report.duration_seconds}")
        print("\nSafety boundary:")
        print(f"  storage_state_content_read:   {report.storage_state_content_read}")
        print(f"  browser_profile_content_read: {report.browser_profile_content_read}")
        print(f"  cookies_logged:               {report.cookies_logged}")
        print(f"  tokens_logged:                {report.tokens_logged}")
        print(f"  captcha_bypass_attempted:     {report.captcha_bypass_attempted}")
        print(f"  anti_bot_bypass_attempted:    {report.anti_bot_bypass_attempted}")
        print(f"  safe_to_deliver:              {report.safe_to_deliver}")
        if report.notes:
            print("\nNotes:")
            for n in report.notes:
                print(f"  - {n}")

    return 0 if report.storage_state_captured else 1


if __name__ == "__main__":
    sys.exit(main())

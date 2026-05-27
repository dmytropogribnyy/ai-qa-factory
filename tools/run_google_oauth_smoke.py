"""Phase 7C — Google OAuth storageState reuse smoke CLI."""
from __future__ import annotations

import sys

# Blocked flags checked before all imports to prevent accidental credential handling.
_BLOCKED_FLAGS: list[tuple[str, str]] = [
    ("--personal-account", "Personal Google accounts are always blocked."),
    ("--production-account", "Production Google accounts are always blocked."),
    ("--captcha-bypass", "CAPTCHA bypass is always blocked."),
    ("--read-storage-state", "Reading storageState content is always blocked."),
    ("--password", "Password-based automation is always blocked for Google OAuth."),
    ("--username", "Username/password automation is always blocked for Google OAuth."),
]
for _flag, _reason in _BLOCKED_FLAGS:
    if _flag in sys.argv:
        print(f"[BLOCKED] {_reason}", file=sys.stderr)
        sys.exit(1)

from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

import argparse  # noqa: E402
import json  # noqa: E402

from core.google_oauth_runner import GoogleOAuthRunner  # noqa: E402
from core.schemas.google_oauth import GoogleOAuthInputs  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 7C -- Google OAuth storageState reuse smoke runner.\n"
            "Requires a previously captured storageState file from a dedicated "
            "Google test account. Never automates password entry."
        )
    )
    parser.add_argument("--project-id", required=True, help="Project identifier")
    parser.add_argument(
        "--target-url",
        default="https://accounts.google.com",
        help="Allowlisted Google target URL",
    )
    parser.add_argument(
        "--storage-state-path",
        default="",
        help="Path to previously captured storageState JSON file",
    )
    parser.add_argument(
        "--account-email-label",
        default="",
        help="Label for the dedicated test account (no raw email address)",
    )
    parser.add_argument(
        "--dedicated-test-account-confirmed",
        action="store_true",
        help="Confirm that a dedicated test account (not personal) is being used",
    )
    parser.add_argument(
        "--google-test-account-confirmed",
        action="store_true",
        help="Confirm that this is a Google test account, not a production account",
    )
    parser.add_argument(
        "--approve-execution",
        action="store_true",
        help="Approve actual Playwright smoke execution (default: planning-only)",
    )
    parser.add_argument(
        "--outputs-root",
        default="outputs",
        help="Root directory for output artifacts",
    )
    args = parser.parse_args()

    inputs = GoogleOAuthInputs(
        project_id=args.project_id,
        target_url=args.target_url,
        storage_state_path=args.storage_state_path,
        account_email_label=args.account_email_label,
        dedicated_test_account_confirmed=args.dedicated_test_account_confirmed,
        google_test_account_confirmed=args.google_test_account_confirmed,
        approve_execution=args.approve_execution,
    )

    runner = GoogleOAuthRunner(outputs_root=Path(args.outputs_root))
    plan = runner.build_plan(inputs)
    result = runner.run(inputs)
    artifacts = runner.render_artifacts(plan, result, args.project_id)

    print(f"[7C] Mode: {result.mode.value}")
    print(f"[7C] Status: {result.status.value}")
    print(f"[7C] Auth coverage: {result.auth_coverage_summary}")

    if result.blockers:
        print("[7C] Blockers:")
        for b in result.blockers:
            print(f"  - {b}")

    if result.notes:
        print("[7C] Notes:")
        for n in result.notes:
            print(f"  - {n}")

    print("[7C] Artifacts:")
    for name, path in artifacts.items():
        print(f"  {name}: {path}")

    print()
    print(json.dumps(result.to_dict(), indent=2))

    print(f"\n[OK] Phase 7C Google OAuth smoke complete. Status: {result.status.value}")

    if result.status.value in ("blocked", "failed"):
        sys.exit(1)


if __name__ == "__main__":
    main()

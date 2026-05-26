"""
Phase 5G — Google Auth Capability Planner CLI.

Planning and policy only. No browser. No network. No credentials.
Decides whether a Google auth request is permitted under the safety policy,
and renders capability/decision artifacts.

Examples:

    # Full capability plan for a project with a dedicated test account:
    python tools/plan_google_auth.py \\
        --project-id my-google-smoke \\
        --account-email-label danrobinson_artist_gmail \\
        --dedicated-test-account-confirmed \\
        --google-test-account-confirmed

    # Per-request decision for storage_state_reuse:
    python tools/plan_google_auth.py \\
        --project-id my-google-smoke \\
        --decide \\
        --auth-mode storage_state_reuse \\
        --target-url https://myaccount.google.com \\
        --target-kind google_account_ui \\
        --storage-state-path outputs/my-google-smoke/15_google_auth/.auth/google-storageState.json \\
        --approve-google-test-account \\
        --google-test-account-confirmed \\
        --dedicated-test-account-confirmed
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.google_auth_capability import GoogleAuthCapabilityPlanner

# Blocked raw-secret CLI flags — fail fast if any appear
_BLOCKED_FLAGS = (
    "--password",
    "--secret",
    "--token",
    "--api-key",
    "--cookie",
    "--storage-state-content",
    "--service-account-json",
    "--totp-seed",
)


def _check_blocked_flags(argv) -> None:
    for arg in argv:
        for bf in _BLOCKED_FLAGS:
            if arg == bf or arg.startswith(bf + "="):
                print(
                    f"ERROR: raw-secret flag {bf} is never accepted. "
                    "Only env var name references are permitted.",
                    file=sys.stderr,
                )
                sys.exit(2)


def _print_capability(cap, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(cap.to_dict(), indent=2, default=str))
        return

    profile = cap.account_profile
    print("\nGoogle Auth Capability Plan — Phase 5G")
    print(f"  project_id:         {cap.project_id}")
    if profile:
        print(f"  account label:      {profile.account_email_label or '(none)'}")
        print(f"  account_type:       {profile.account_type}")
        print(f"  workspace_account:  {profile.workspace_account}")
        print(f"  two_factor_enabled: {profile.two_factor_enabled}")

    print("\nMode summary:")
    for mp in cap.mode_policies:
        sym = "ALLOWED" if mp.allowed_now else "BLOCKED"
        print(f"  [{sym}] {mp.auth_mode}: blockers={len(mp.blockers)}, warnings={len(mp.warnings)}")

    print("\nInvariants:")
    print(f"  raw_secrets_allowed:         {cap.raw_secrets_allowed}")
    print(f"  storage_state_content_read:  {cap.storage_state_content_read}")
    print(f"  browser_profile_content_read:{cap.browser_profile_content_read}")
    print(f"  captcha_bypass_allowed:      {cap.captcha_bypass_allowed}")
    print(f"  anti_bot_bypass_allowed:     {cap.anti_bot_bypass_allowed}")
    print(f"  client_delivery_allowed:     {cap.client_delivery_allowed}")


def _print_decision(dec, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(dec.to_dict(), indent=2, default=str))
        return
    sym = "ALLOWED" if dec.allowed_now else "BLOCKED"
    print(f"\nGoogle Auth Execution Decision — {sym}")
    print(f"  project_id:    {dec.project_id}")
    print(f"  auth_mode:     {dec.auth_mode}")
    print(f"  target_url:    {dec.target_url}")
    print(f"  target_kind:   {dec.target_kind}")
    print(f"  account label: {dec.account_email_label or '(none)'}")
    if dec.blockers:
        print("\nBlockers:")
        for b in dec.blockers:
            print(f"  - {b}")
    if dec.warnings:
        print("\nWarnings:")
        for w in dec.warnings:
            print(f"  - {w}")
    print("\nRequired approval flags:")
    for f in dec.required_approval_flags:
        print(f"  - {f}")


def main() -> int:
    _check_blocked_flags(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Phase 5G — Google Auth Capability planner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--outputs-root", default="outputs")
    parser.add_argument("--no-write", action="store_true", default=False)
    parser.add_argument("--json", action="store_true", default=False)

    # Account profile (labels only — never raw email value as credential)
    parser.add_argument("--account-email-label", default="")
    parser.add_argument(
        "--account-type",
        default="dedicated_test",
        choices=("dedicated_test", "personal", "production"),
    )
    parser.add_argument("--workspace-account", action="store_true", default=False)
    parser.add_argument(
        "--two-factor-enabled",
        default="unknown",
        choices=("yes", "no", "unknown"),
    )
    parser.add_argument("--dedicated-test-account-confirmed", action="store_true", default=False)
    parser.add_argument("--google-test-account-confirmed", action="store_true", default=False)
    parser.add_argument("--personal-account-confirmed", action="store_true", default=False)
    parser.add_argument("--production-account-confirmed", action="store_true", default=False)

    # Per-request decision mode
    parser.add_argument("--decide", action="store_true", default=False,
                        help="Produce a per-request decision instead of full capability plan")
    parser.add_argument("--auth-mode", default="")
    parser.add_argument("--target-url", default="")
    parser.add_argument("--target-kind", default="")
    parser.add_argument("--storage-state-path", default="")
    parser.add_argument("--cdp-port", type=int, default=None)
    parser.add_argument("--user-data-dir", default="")
    parser.add_argument("--api-token-env-var", default="",
                        help="Env var NAME holding the API token (value never read by planner)")
    parser.add_argument("--service-account-reference", default="",
                        help="Reference label for the service account (no JSON content)")
    parser.add_argument("--totp-seed-env-var", default="",
                        help="Env var NAME holding the TOTP seed (value never read by planner)")
    parser.add_argument("--approve-google-test-account", action="store_true", default=False)

    args = parser.parse_args()

    two_fa = None if args.two_factor_enabled == "unknown" else (
        args.two_factor_enabled == "yes"
    )

    planner = GoogleAuthCapabilityPlanner(outputs_root=Path(args.outputs_root))

    if args.decide:
        if not args.auth_mode:
            print("ERROR: --decide requires --auth-mode", file=sys.stderr)
            return 2
        dec = planner.decide_execution(
            project_id=args.project_id,
            target_url=args.target_url,
            target_kind=args.target_kind,
            auth_mode=args.auth_mode,
            account_email_label=args.account_email_label,
            approve_google_test_account=args.approve_google_test_account,
            google_test_account_confirmed=args.google_test_account_confirmed,
            dedicated_test_account_confirmed=args.dedicated_test_account_confirmed,
            personal_account_confirmed=args.personal_account_confirmed,
            production_account_confirmed=args.production_account_confirmed,
            storage_state_path=args.storage_state_path,
            cdp_port=args.cdp_port,
            user_data_dir=args.user_data_dir,
            api_token_env_var=args.api_token_env_var,
            service_account_reference=args.service_account_reference,
            totp_seed_env_var=args.totp_seed_env_var,
        )
        _print_decision(dec, as_json=args.json)
        if not args.no_write:
            paths = planner.render_decision_artifacts(dec, args.project_id)
            print("\nArtifacts written:")
            for k, v in paths.items():
                print(f"  {k}: {v}")
        return 0 if dec.allowed_now else 1

    # Default: full capability plan
    cap = planner.build_capability(
        project_id=args.project_id,
        account_email_label=args.account_email_label,
        account_type=args.account_type,
        workspace_account=args.workspace_account,
        two_factor_enabled=two_fa,
        dedicated_test_account_confirmed=args.dedicated_test_account_confirmed,
        google_test_account_confirmed=args.google_test_account_confirmed,
        personal_account_confirmed=args.personal_account_confirmed,
        production_account_confirmed=args.production_account_confirmed,
    )
    _print_capability(cap, as_json=args.json)
    if not args.no_write:
        paths = planner.render_capability_artifacts(cap, args.project_id)
        print("\nArtifacts written:")
        for k, v in paths.items():
            print(f"  {k}: {v}")
    any_allowed = any(mp.allowed_now for mp in cap.mode_policies)
    return 0 if any_allowed else 1


if __name__ == "__main__":
    sys.exit(main())

"""
Phase 5I — CLI: GitHub OAuth test-account capability planner and smoke runner.

Usage:
  # Capability plan:
  python tools/run_github_auth_smoke.py \\
    --project-id my-project \\
    --account-email-label qa_bot_github \\
    --approve-github-test-account \\
    --dedicated-test-account-confirmed \\
    --target-url https://github.com \\
    --target-kind github_login_ui

  # Per-request decision:
  python tools/run_github_auth_smoke.py \\
    --project-id my-project \\
    --decide \\
    --auth-mode storage_state_reuse \\
    --target-url https://github.com \\
    --target-kind github_login_ui \\
    --storage-state-path outputs/my-project/19_github_auth/.auth/github-storageState.json \\
    --approve-github-test-account \\
    --dedicated-test-account-confirmed

SAFETY:
- Personal GitHub accounts: always blocked.
- Production GitHub org accounts: always blocked.
- Raw secrets never accepted via CLI flags.
- storageState content never read by Python.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BLOCKED_FLAGS = (
    "--password", "--token", "--secret", "--api-key",
    "--cookie", "--pat", "--access-token", "--bearer",
)


def _check_blocked_flags(argv: list) -> None:
    for flag in argv:
        flag_lower = flag.lower()
        for blocked in _BLOCKED_FLAGS:
            if flag_lower == blocked or flag_lower.startswith(blocked + "="):
                print(
                    f"[BLOCKED] Flag '{blocked}' is not allowed. "
                    "Pass credentials via env var only.",
                    file=sys.stderr,
                )
                sys.exit(2)


def main() -> None:
    _check_blocked_flags(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Phase 5I: GitHub OAuth test-account capability planner + smoke."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--account-email-label",
                        help="Label of the dedicated GitHub test account (not the actual email)")
    parser.add_argument("--target-url", default="https://github.com")
    parser.add_argument("--target-kind", default="github_login_ui",
                        choices=["github_login_ui", "github_protected_resource", "github_api_endpoint"])
    parser.add_argument("--auth-mode", default="storage_state_reuse",
                        help="Auth mode for --decide")
    parser.add_argument("--storage-state-path",
                        help="Path to captured GitHub storageState JSON")
    parser.add_argument("--approve-github-test-account", action="store_true")
    parser.add_argument("--dedicated-test-account-confirmed", action="store_true")
    parser.add_argument("--personal-account-confirmed", action="store_true",
                        help="Always blocked — providing this flag will block execution")
    parser.add_argument("--production-account-confirmed", action="store_true",
                        help="Always blocked — providing this flag will block execution")
    parser.add_argument("--decide", action="store_true",
                        help="Output per-request execution decision instead of full capability plan")
    parser.add_argument("--run-smoke", action="store_true",
                        help="Run storage_state_reuse smoke after decision")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)

    args = parser.parse_args()

    from core.github_auth_runner import GitHubAuthRunner
    runner = GitHubAuthRunner(outputs_root=Path("outputs"))

    if args.decide or args.run_smoke:
        decision = runner.decide_execution(
            project_id=args.project_id,
            auth_mode=args.auth_mode,
            target_url=args.target_url,
            target_kind=args.target_kind,
            storage_state_path=args.storage_state_path,
            approve_github_test_account=args.approve_github_test_account,
            dedicated_test_account_confirmed=args.dedicated_test_account_confirmed,
            personal_account_confirmed=args.personal_account_confirmed,
            production_account_confirmed=args.production_account_confirmed,
        )
        print(f"Decision:       {'ALLOWED' if decision.allowed_now else 'BLOCKED'}")
        print(f"Auth mode:      {decision.auth_mode}")
        print(f"Target URL:     {decision.target_url}")
        if decision.blockers:
            print("\nBlockers:")
            for b in decision.blockers:
                print(f"  - {b}")

        if not decision.allowed_now:
            if not args.no_write:
                runner.render_artifacts(None, decision, None, args.project_id)
            sys.exit(1)

        evidence = None
        if args.run_smoke and args.auth_mode == "storage_state_reuse":
            evidence = runner.run_storage_state_reuse_smoke(
                project_id=args.project_id,
                target_url=args.target_url,
                target_kind=args.target_kind,
                storage_state_path=args.storage_state_path or "",
                approve_github_test_account=args.approve_github_test_account,
                dedicated_test_account_confirmed=args.dedicated_test_account_confirmed,
                timeout=args.timeout,
            )
            print(f"\nSmoke status:   {evidence.execution_status}")
            if evidence.screenshot_path:
                print(f"Screenshot:     {evidence.screenshot_path}")
            if evidence.blockers:
                print("Smoke blockers:")
                for b in evidence.blockers:
                    print(f"  - {b}")

        if not args.no_write:
            runner.render_artifacts(None, decision, evidence, args.project_id)
        sys.exit(0)

    # Full capability plan
    capability = runner.plan_capability(
        project_id=args.project_id,
        account_label=args.account_email_label or "",
        target_url=args.target_url,
        target_kind=args.target_kind,
        storage_state_path=args.storage_state_path,
        approve_github_test_account=args.approve_github_test_account,
        dedicated_test_account_confirmed=args.dedicated_test_account_confirmed,
        personal_account_confirmed=args.personal_account_confirmed,
        production_account_confirmed=args.production_account_confirmed,
    )

    print(f"Executable modes:  {', '.join(capability.executable_modes) or 'none'}")
    print(f"Planning-only:     {', '.join(capability.planning_only_modes)}")
    if capability.blockers:
        print("\nBlockers:")
        for b in capability.blockers:
            print(f"  - {b}")
    if capability.notes:
        print("\nNotes:")
        for n in capability.notes:
            print(f"  - {n}")

    if not args.no_write:
        runner.render_artifacts(capability, None, None, args.project_id)

    sys.exit(0 if not capability.blockers else 1)


if __name__ == "__main__":
    main()

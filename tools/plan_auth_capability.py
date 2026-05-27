"""Phase 7A -- Auth Capability Planner CLI.

Classifies authentication methods for a project and writes a capability plan.
No auth flows are executed -- planning and classification only.

Usage:
  python tools/plan_auth_capability.py --project-id demo
  python tools/plan_auth_capability.py --project-id demo --has-google-account --has-storage-state
  python tools/plan_auth_capability.py --project-id demo --has-dedicated-test-account --password-env-var QA_PASSWORD
  python tools/plan_auth_capability.py --project-id demo --api-token-env-var QA_API_TOKEN --no-write
  python tools/plan_auth_capability.py --project-id demo --no-write --json-output

Blocked flags (always exit 1 -- raw secrets never accepted):
  --password, --secret, --token, --cookie, --totp-seed,
  --access-token, --bearer, --client-secret, --api-key
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from core.auth_capability_planner import AuthCapabilityPlanner, _plan_to_dict
from core.schemas.auth_capability import AuthCapabilityInputs

_APP_VERSION = "7.0.0"
_SEP = "-" * 60

_BLOCKED_FLAGS = frozenset([
    "--password", "--secret", "--token", "--cookie", "--totp-seed",
    "--access-token", "--bearer", "--client-secret", "--api-key",
])

_READINESS_MARKERS = {
    "allowed_now": "[ok]",
    "planning_only": "[plan]",
    "blocked": "[blocked]",
    "requires_manual_step": "[manual]",
    "requires_test_account": "[need-account]",
    "requires_env_var_secret": "[need-env]",
    "requires_client_confirmation": "[need-confirm]",
}


def _blocked_flag_check(argv: list[str]) -> None:
    found = [f for f in argv if f in _BLOCKED_FLAGS]
    if found:
        print(f"[blocked] Forbidden flags detected: {', '.join(found)}")
        print("  Raw secrets are never accepted via CLI flags.")
        print("  Use --password-env-var, --api-token-env-var, --bearer-token-env-var, --totp-seed-env-var")
        print("  to pass the NAME of the environment variable, not its value.")
        sys.exit(1)


def _print_plan(plan_dict: dict) -> None:
    print(f"\n{_SEP}")
    print("  AI QA Factory v{} -- Auth Capability Plan".format(_APP_VERSION))
    print(_SEP)
    print(f"  Project:    {plan_dict['project_id']}")
    print(f"  Target URL: {plan_dict['target_url'] or 'not provided'}")
    print("")
    print("  Safety invariants:")
    print(f"    personal_account_allowed:   {plan_dict['personal_account_allowed']}")
    print(f"    production_account_allowed: {plan_dict['production_account_allowed']}")
    print(f"    captcha_bypass_allowed:     {plan_dict['captcha_bypass_allowed']}")
    print(f"    auth_bypass_allowed:        {plan_dict['auth_bypass_allowed']}")
    print(f"    human_review_required:      {plan_dict['human_review_required']}")
    print("")
    print("  Auth method readiness:")
    for cap in plan_dict.get("capabilities", []):
        marker = _READINESS_MARKERS.get(cap["readiness"], "[?]")
        print(f"    {marker:<15} {cap['method']}")
    print("")
    allowed = plan_dict.get("allowed_now_methods", [])
    if allowed:
        print(f"  Allowed now ({len(allowed)}):")
        for m in allowed:
            print(f"    - {m}")
    else:
        print("  Allowed now: (none with current inputs)")
    needs = plan_dict.get("requires_action_methods", [])
    if needs:
        print(f"\n  Requires action ({len(needs)}):")
        for m in needs:
            cap = next((c for c in plan_dict["capabilities"] if c["method"] == m), {})
            ri = cap.get("required_inputs", [])
            req = ri[0] if ri else ""
            print(f"    - {m}: {req}")
    steps = plan_dict.get("recommended_next_steps", [])
    if steps:
        print("\n  Recommended next steps:")
        for step in steps:
            print(f"    => {step}")
    print(_SEP)


def main(argv: list[str] | None = None) -> None:
    _blocked_flag_check(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        description=f"AI QA Factory v{_APP_VERSION} -- Auth Capability Planner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project-id", default="auth-plan-demo",
                        help="Project identifier (default: auth-plan-demo)")
    parser.add_argument("--target-url", default="",
                        help="Target URL for browser-based auth methods")
    parser.add_argument("--has-dedicated-test-account", action="store_true",
                        help="Confirm a dedicated test account exists (not personal, not production)")
    parser.add_argument("--password-env-var", default="",
                        help="Name of env var holding the test account password (not the value)")
    parser.add_argument("--api-token-env-var", default="",
                        help="Name of env var holding the API token (not the value)")
    parser.add_argument("--bearer-token-env-var", default="",
                        help="Name of env var holding the bearer token (not the value)")
    parser.add_argument("--totp-seed-env-var", default="",
                        help="Name of env var holding the TOTP seed (not the value)")
    parser.add_argument("--storage-state-file", default="",
                        help="Path to existing storageState file (existence checked, content never read)")
    parser.add_argument("--has-storage-state", action="store_true",
                        help="Confirm a storageState file is available")
    parser.add_argument("--has-google-account", action="store_true",
                        help="Confirm a Google dedicated test account is available")
    parser.add_argument("--has-github-account", action="store_true",
                        help="Confirm a GitHub dedicated test account is available")
    parser.add_argument("--has-microsoft-account", action="store_true",
                        help="Confirm a Microsoft (M365 test tenant) account is available")
    parser.add_argument("--outputs-root", default="outputs",
                        help="Root directory for output artifacts (default: outputs)")
    parser.add_argument("--no-write", action="store_true",
                        help="Dry run -- do not write any files")
    parser.add_argument("--json-output", action="store_true",
                        help="Print full JSON plan to stdout after summary")

    args = parser.parse_args(argv)

    inputs = AuthCapabilityInputs(
        project_id=args.project_id,
        target_url=args.target_url,
        has_dedicated_test_account=args.has_dedicated_test_account,
        password_env_var=args.password_env_var,
        api_token_env_var=args.api_token_env_var,
        bearer_token_env_var=args.bearer_token_env_var,
        totp_seed_env_var=args.totp_seed_env_var,
        storage_state_file=args.storage_state_file,
        has_storage_state=args.has_storage_state,
        has_google_account=args.has_google_account,
        has_github_account=args.has_github_account,
        has_microsoft_account=args.has_microsoft_account,
        outputs_root=args.outputs_root,
        write_files=not args.no_write,
    )

    planner = AuthCapabilityPlanner(inputs)
    plan = planner.run()
    plan_dict = _plan_to_dict(plan)

    _print_plan(plan_dict)

    if args.json_output:
        print("\n--- JSON Output ---")
        print(json.dumps(plan_dict, indent=2))

    print(f"\n[OK] Auth capability plan complete -- project: {args.project_id}")
    if not args.no_write:
        print(f"     Artifacts in: {args.outputs_root}/{args.project_id}/34_auth_capability/")


if __name__ == "__main__":
    main()

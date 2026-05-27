"""Phase 7B -- Auth Strategy Selector CLI.

Selects the safest executable auth strategy from a Phase 7A capability plan.
No auth flows are executed -- strategy selection and decision only.

Usage:
  python tools/select_auth_strategy.py --project-id demo --plan-file outputs/demo/34_auth_capability/auth_capability_plan.json
  python tools/select_auth_strategy.py --project-id demo --has-dedicated-test-account --password-env-var QA_PASSWORD
  python tools/select_auth_strategy.py --project-id demo --has-google-account --has-storage-state --no-write
  python tools/select_auth_strategy.py --project-id demo --no-write --json-output

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

from core.auth_capability_planner import AuthCapabilityPlanner
from core.auth_strategy_selector import AuthStrategySelector, _decision_to_dict
from core.schemas.auth_capability import AuthCapabilityInputs, AuthCapabilityPlan
from core.schemas.auth_strategy import DecisionStatus  # noqa: F401

_APP_VERSION = "7.1.0"
_SEP = "-" * 60

_BLOCKED_FLAGS = frozenset([
    "--password", "--secret", "--token", "--cookie", "--totp-seed",
    "--access-token", "--bearer", "--client-secret", "--api-key",
])

_STATUS_MARKERS = {
    "ready_for_execution": "[ready]",
    "missing_required_input": "[need-input]",
    "planning_only": "[plan]",
    "blocked": "[blocked]",
    "no_methods_available": "[no-methods]",
}


def _blocked_flag_check(argv: list[str]) -> None:
    found = [f for f in argv if f in _BLOCKED_FLAGS]
    if found:
        print(f"[blocked] Forbidden flags detected: {', '.join(found)}")
        print("  Raw secrets are never accepted via CLI flags.")
        print("  Use --password-env-var, --api-token-env-var, --bearer-token-env-var, --totp-seed-env-var")
        print("  to pass the NAME of the environment variable, not its value.")
        sys.exit(1)


def _print_decision(d: dict) -> None:
    status = d.get("decision_status", "")
    marker = _STATUS_MARKERS.get(status, "[?]")
    print(f"\n{_SEP}")
    print(f"  AI QA Factory v{_APP_VERSION} -- Auth Strategy Decision")
    print(_SEP)
    print(f"  Project:         {d['project_id']}")
    print(f"  Status:          {marker} {status}")
    print(f"  Safe to execute: {d['safe_to_execute']}")
    print("")
    print("  Safety invariants:")
    print(f"    personal_account_allowed:   {d['personal_account_allowed']}")
    print(f"    production_account_allowed: {d['production_account_allowed']}")
    print(f"    captcha_bypass_allowed:     {d['captcha_bypass_allowed']}")
    print(f"    raw_secrets_allowed:        {d['raw_secrets_allowed']}")
    print(f"    human_review_required:      {d['human_review_required']}")
    print("")
    if d.get("selected_method"):
        print("  Selected strategy:")
        print(f"    method:      {d['selected_method']}")
        print(f"    provider:    {d['selected_provider']}")
        print(f"    mode:        {d['selected_mode']}")
        print(f"    next_runner: {d['next_runner'] or '(none)'}")
    print(f"\n  Reason: {d['reason']}")
    missing = d.get("missing_inputs", [])
    if missing:
        print(f"\n  Missing inputs ({len(missing)}):")
        for inp in missing:
            print(f"    - {inp}")
    blocked_r = d.get("blocked_reasons", [])
    if blocked_r:
        print(f"\n  Blocked reasons ({len(blocked_r)}):")
        for r in blocked_r:
            print(f"    - {r}")
    print(_SEP)


def main(argv: list[str] | None = None) -> None:
    _blocked_flag_check(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        description=f"AI QA Factory v{_APP_VERSION} -- Auth Strategy Selector",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project-id", default="auth-strategy-demo",
                        help="Project identifier (default: auth-strategy-demo)")
    parser.add_argument("--plan-file", default="",
                        help="Path to existing auth_capability_plan.json (if omitted, planner runs inline)")
    parser.add_argument("--target-url", default="")
    parser.add_argument("--has-dedicated-test-account", action="store_true")
    parser.add_argument("--password-env-var", default="")
    parser.add_argument("--api-token-env-var", default="")
    parser.add_argument("--bearer-token-env-var", default="")
    parser.add_argument("--totp-seed-env-var", default="")
    parser.add_argument("--storage-state-file", default="")
    parser.add_argument("--has-storage-state", action="store_true")
    parser.add_argument("--has-google-account", action="store_true")
    parser.add_argument("--has-github-account", action="store_true")
    parser.add_argument("--has-microsoft-account", action="store_true")
    parser.add_argument("--outputs-root", default="outputs")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--json-output", action="store_true")

    args = parser.parse_args(argv)

    if args.plan_file:
        raw = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
        plan = AuthCapabilityPlan.from_dict(raw)
        if args.project_id and args.project_id != "auth-strategy-demo":
            plan = AuthCapabilityPlan(
                project_id=args.project_id,
                target_url=plan.target_url,
                capabilities=plan.capabilities,
                blocked_methods=plan.blocked_methods,
                allowed_now_methods=plan.allowed_now_methods,
                planning_only_methods=plan.planning_only_methods,
                requires_action_methods=plan.requires_action_methods,
                recommended_next_steps=plan.recommended_next_steps,
            )
    else:
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
            write_files=False,
        )
        plan = AuthCapabilityPlanner(inputs).build_plan()

    selector = AuthStrategySelector(
        plan,
        outputs_root=args.outputs_root,
        write_files=not args.no_write,
    )
    decision = selector.run()
    decision_dict = _decision_to_dict(decision)

    _print_decision(decision_dict)

    if args.json_output:
        print("\n--- JSON Output ---")
        print(json.dumps(decision_dict, indent=2))

    print(f"\n[OK] Auth strategy selection complete -- project: {args.project_id}")
    if not args.no_write:
        print(f"     Artifacts in: {args.outputs_root}/{args.project_id}/35_auth_strategy/")


if __name__ == "__main__":
    main()

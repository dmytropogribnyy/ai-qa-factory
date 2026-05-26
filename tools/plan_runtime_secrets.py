"""CLI: plan_runtime_secrets.py — Phase 5AB Runtime Secret Routing Planner.

Validates a dedicated test-account intake request and produces routing artifacts.
No execution. No env var value reading. No external calls. No raw secrets accepted.

Usage:
    python tools/plan_runtime_secrets.py --project-id demo-5ab
    python tools/plan_runtime_secrets.py --project-id demo-5ab --json --no-write
    python tools/plan_runtime_secrets.py --project-id demo-5ab \\
        --scenario-lane dedicated_test_account_auth_future \\
        --target-category staging \\
        --account-type dedicated_test_account \\
        --username-env-var QA_TEST_USERNAME \\
        --password-env-var QA_TEST_PASSWORD \\
        --dedicated-test-account-confirmed \\
        --staging-environment-confirmed
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
        description="Phase 5AB: Runtime secret routing planner (no execution, no raw secrets)."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--json", action="store_true", dest="json_output")
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--target-url")
    parser.add_argument("--target-category", default="")
    parser.add_argument("--scenario-lane", default="")
    parser.add_argument("--account-provider", default="")
    parser.add_argument("--account-type", default="")
    parser.add_argument("--route-type", default="runtime_env_reference")
    parser.add_argument("--username-env-var", default=None)
    parser.add_argument("--password-env-var", default=None)
    parser.add_argument("--token-env-var", default=None)
    parser.add_argument("--dedicated-test-account-confirmed", action="store_true")
    parser.add_argument("--staging-environment-confirmed", action="store_true")
    parser.add_argument("--client-scope-confirmed", action="store_true")
    parser.add_argument("--personal-account-confirmed", action="store_true")
    parser.add_argument("--production-account-confirmed", action="store_true")
    parser.add_argument("--outputs-root", default="outputs")

    args = parser.parse_args(argv)

    from core.dedicated_auth_runner import DedicatedAuthRunner

    runner = DedicatedAuthRunner(outputs_root=Path(args.outputs_root))

    # Validate intake request (no values read, no execution)
    validation = runner.validate_intake(
        project_id=args.project_id,
        target_url=args.target_url,
        target_category=args.target_category,
        scenario_lane=args.scenario_lane,
        account_provider=args.account_provider,
        account_type=args.account_type,
        username_env_var=args.username_env_var,
        password_env_var=args.password_env_var,
        token_env_var=args.token_env_var,
        dedicated_test_account_confirmed=args.dedicated_test_account_confirmed,
        personal_account_confirmed=args.personal_account_confirmed,
        production_account_confirmed=args.production_account_confirmed,
        staging_environment_confirmed=args.staging_environment_confirmed,
        client_scope_confirmed=args.client_scope_confirmed,
    )

    if args.json_output:
        print(json.dumps(validation.to_dict(), indent=2))
        return 0

    # Human-readable output
    print("Runtime Secret Routing Plan — Phase 5AB")
    print(f"  project_id:     {args.project_id}")
    print(f"  scenario_lane:  {args.scenario_lane or '(not specified)'}")
    print(f"  target_category:{args.target_category or '(not specified)'}")
    print(f"  route_type:     {args.route_type}")
    print()

    if args.username_env_var:
        print(f"  username_env_var: {args.username_env_var}  (name only — value NOT read)")
    if args.password_env_var:
        print(f"  password_env_var: {args.password_env_var}  (name only — value NOT read)")
    if args.token_env_var:
        print(f"  token_env_var:    {args.token_env_var}  (name only — value NOT read)")
    print()

    print(f"Validation status: {validation.status.upper()}")

    if validation.blockers:
        print("\nBlockers:")
        for b in validation.blockers:
            print(f"  BLOCKED: {b}")

    if validation.warnings:
        print("\nWarnings:")
        for w in validation.warnings:
            print(f"  WARN: {w}")

    if validation.accepted_secret_references:
        print("\nAccepted secret references (env var names only):")
        for ref in validation.accepted_secret_references:
            print(f"  - {ref.label}: env_var={ref.env_var_name}  raw_value_present=False")

    if validation.rejected_secret_references:
        print("\nRejected secret references:")
        for ref in validation.rejected_secret_references:
            print(f"  - {ref.label}: env_var={ref.env_var_name}  REJECTED")

    print(f"\n  safe_for_future_execution:   {validation.safe_for_future_execution}")
    print(f"  approved_for_execution_now:  {validation.approved_for_execution_now}")

    if not args.no_write and args.scenario_lane:
        out_dir = Path(args.outputs_root) / args.project_id / "11_runtime_secrets"
        out_dir.mkdir(parents=True, exist_ok=True)
        import json as _json
        (out_dir / "TEST_ACCOUNT_INTAKE_VALIDATION.json").write_text(
            _json.dumps(validation.to_dict(), indent=2), encoding="utf-8"
        )
        _write_routing_md(out_dir, args, validation)
        print(f"\nArtifacts written to: {out_dir}/")

    print("\nSafety boundary:")
    print("  No env var values read.")
    print("  No execution performed.")
    print("  No external calls made.")
    print("  No raw secrets accepted through CLI args.")
    print("  personal_account_confirmed is blocked.")
    print("  production_account_confirmed is blocked.")
    print("  Google OAuth (accounts.google.com) is strictly blocked.")

    return 0


def _write_routing_md(out_dir: Path, args: object, validation: object) -> None:
    text = f"""# Runtime Secret Routing Plan

**Project:** {args.project_id}
**Scenario lane:** {args.scenario_lane or "not specified"}
**Target category:** {args.target_category or "not specified"}
**Validation status:** {validation.status.upper()}

## Secret reference model

| Reference | Env var name | Route type | Safe to persist | Value read here |
|---|---|---|---|---|
"""
    for ref in getattr(validation, "accepted_secret_references", []):
        text += f"| {ref.label} | `{ref.env_var_name}` | runtime_env_reference | False | **No** |\n"
    for ref in getattr(validation, "rejected_secret_references", []):
        text += f"| {ref.label} | `{ref.env_var_name}` | REJECTED | False | **No** |\n"

    text += """
## Allowed routes

| Route | Allowed now | Notes |
|---|---|---|
| `public_demo_profile` | Yes (demo lanes only) | SauceDemo public credentials |
| `runtime_env_reference` | Yes (dedicated auth with approval) | Env var names only — values read at execution time |
| `vault_reference_future` | No — Phase 5C+ | Planned |
| `client_secure_channel_future` | No — Phase 5C+ | Planned |

## Blocked routes

- `repo_file` — secrets committed to repo are always blocked
- `chat_message` — secrets pasted in chat are always blocked
- `cli_raw_value` — --username/--password raw value flags are blocked
- Personal accounts — always blocked
- Production accounts — always blocked
- Google OAuth (accounts.google.com) — always blocked
- Alza/Amazon/LinkedIn/Upwork — always blocked

## Notes

No raw credential values are stored in this artifact.
Validation checks env var name format and lane/category constraints only.
Execution approval requires `--approve-dedicated-auth-execution` flag in run_dedicated_auth.py.
"""
    if getattr(validation, "blockers", []):
        text += "\n## Blockers\n\n"
        for b in validation.blockers:
            text += f"- {b}\n"

    (out_dir / "RUNTIME_SECRET_ROUTING_PLAN.md").write_text(text, encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())

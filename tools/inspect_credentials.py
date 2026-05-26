"""CLI: inspect_credentials.py — Phase 4E Credential Safety Inspector.

Scans local safe text artifacts for credential references, unsafe patterns,
and sandbox profile classifications. Produces credential safety artifacts.

No real credentials are used, stored, or read.
No login or auth execution is performed.
No .env, .auth, or storageState files are read.

Usage:
    python tools/inspect_credentials.py --project-id demo
    python tools/inspect_credentials.py --project-id demo --json
    python tools/inspect_credentials.py --project-id demo --no-write
    python tools/inspect_credentials.py --project-id demo --include-fixtures
    python tools/inspect_credentials.py --project-id demo --include-scaffold
    python tools/inspect_credentials.py --project-id demo --classify-sandbox "Amazon Pay Sandbox"
    python tools/inspect_credentials.py --project-id demo --classify-sandbox "Alza production account"
    python tools/inspect_credentials.py --from-output outputs/demo
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.credential_safety_inspector import CredentialSafetyInspector


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Phase 4E: Credential Safety Inspector — scan/report/classification only.\n"
            "Never reads real .env or .auth files. Never uses credentials. No login."
        )
    )
    parser.add_argument("--project-id", default=None, help="Project ID")
    parser.add_argument("--from-output", default=None, help="Path to outputs/<project_id> directory")
    parser.add_argument("--json", action="store_true", dest="json_out", help="Print JSON to stdout")
    parser.add_argument("--no-write", action="store_true", help="Do not write artifacts to disk")
    parser.add_argument(
        "--include-fixtures", action="store_true",
        help="Also scan fixtures/client_scenarios/ (FakeSecret123 allowed in fixture context)",
    )
    parser.add_argument(
        "--include-scaffold", action="store_true",
        help="Also scan generated scaffold under outputs/<project_id>/03_framework/",
    )
    parser.add_argument(
        "--classify-sandbox", default=None, metavar="LABEL",
        help="Classify a sandbox/account label (e.g. 'Amazon Pay Sandbox', 'Alza production account')",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Treat warnings as blockers",
    )
    parser.add_argument(
        "--outputs-root", default="outputs", help="Outputs root directory (default: outputs)"
    )
    args = parser.parse_args(argv)

    if not args.project_id and not args.from_output:
        print("Error: --project-id or --from-output is required.", file=sys.stderr)
        return 2

    outputs_root = Path(args.outputs_root)
    inspector = CredentialSafetyInspector(outputs_root=outputs_root)

    project_id = args.project_id
    if not project_id and args.from_output:
        project_id = Path(args.from_output).name

    # Sandbox classification shortcut
    if args.classify_sandbox:
        profile = inspector.classify_single_sandbox(args.classify_sandbox)
        if args.json_out:
            print(json.dumps(profile.to_dict(), indent=2))
            return 0
        print(f"\nSandbox Classification: '{args.classify_sandbox}'")
        print(f"  provider:                    {profile.provider}")
        print(f"  profile_type:                {profile.profile_type}")
        print(f"  classification:              {profile.classification}")
        print(f"  official_sandbox:            {profile.official_sandbox}")
        print(f"  production_retail_account:   {profile.production_retail_account}")
        print(f"  payment_sandbox:             {profile.payment_sandbox}")
        print(f"  blocked_in_current_phase:    {profile.blocked_in_current_phase}")
        print(f"  allowed_in_future_phase:     {profile.allowed_in_future_phase}")
        print("\nNotes:")
        for n in profile.notes:
            print(f"  - {n}")
        print("\nSafety boundary:")
        print("  No credentials used. No external calls. No login.")
        if profile.blocked_in_current_phase:
            return 1
        return 0

    # Full inspection
    report = inspector.inspect_credentials(
        project_id=project_id,
        include_fixtures=args.include_fixtures,
        include_scaffold=args.include_scaffold,
        strict=args.strict,
    )
    policy = inspector.build_credential_policy(project_id)
    storage_policy = inspector.build_storage_state_policy(project_id)
    auth_approval = inspector.build_auth_execution_approval(project_id)

    if args.json_out:
        print(json.dumps({
            "policy": policy.to_dict(),
            "report": report.to_dict(),
            "storage_state_policy": storage_policy.to_dict(),
            "auth_execution_approval": auth_approval.to_dict(),
        }, indent=2))
        return 0

    if not args.no_write:
        paths = inspector.render_credential_safety_artifacts(
            policy, report, storage_policy, auth_approval, project_id
        )
        print("Credential safety artifacts written to:")
        for key, path in paths.items():
            print(f"  {key}: {path}")

    print("\nCredential Safety Report")
    print(f"  project_id:                  {report.project_id}")
    print(f"  status:                      {report.status}")
    print(f"  credentials_detected:        {len(report.credentials_detected)}")
    print(f"  safe_for_auth_execution:     {report.safe_for_auth_execution}")
    print(f"  safe_for_storage_state:      {report.safe_for_storage_state}")
    print(f"  safe_for_client_visibility:  {report.safe_for_client_visibility}")
    print(f"  storageState approved_for_commit: {storage_policy.approved_for_commit}")
    print(f"  blockers:                    {len(report.blockers)}")
    print(f"  warnings:                    {len(report.warnings)}")

    if report.blockers:
        print("\nBlockers:")
        for b in report.blockers:
            print(f"  - {b}")

    if report.warnings:
        print("\nWarnings:")
        for w in report.warnings:
            print(f"  - {w}")

    print("\nSafety boundary:")
    print("  No real credentials were used or read.")
    print("  No login or auth execution was performed.")
    print("  No .env or .auth files were read.")
    print("  safe_for_auth_execution=False.")
    print("  safe_for_client_visibility=False.")
    print("  storageState approved_for_commit=False.")

    if report.status == "blocked":
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

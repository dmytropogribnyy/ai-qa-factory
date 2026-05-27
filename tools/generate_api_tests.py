"""Phase 5M — Generate API Tests CLI.

Reads an APIContractReport (from 25_api_contract/) and generates Playwright
API test skeleton files into outputs/<project_id>/26_generated_tests/.

Blocked flags: --password, --token, --secret, --api-key, --cookie,
               --pat, --access-token, --bearer, --db-url, --connection-string, --dsn
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_BLOCKED_FLAGS = (
    "--password", "--token", "--secret", "--api-key", "--cookie",
    "--pat", "--access-token", "--bearer", "--db-url",
    "--connection-string", "--dsn",
)

_ARTIFACT_DIR = "26_generated_tests"


def _check_blocked_flags(argv: list[str]) -> None:
    for flag in _BLOCKED_FLAGS:
        if flag in argv:
            print(f"[BLOCKED] Flag '{flag}' is not allowed. Exit 2.", file=sys.stderr)
            sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    _check_blocked_flags(argv if argv is not None else sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Generate Playwright API test skeletons from an APIContractReport."
    )
    parser.add_argument("--project-id", required=True, help="Project identifier")
    parser.add_argument(
        "--contract-report-path",
        required=True,
        help="Path to api_contract_inventory.json",
    )
    parser.add_argument("--outputs-root", default="outputs", help="Root outputs directory")
    parser.add_argument("--no-write", action="store_true", help="Skip writing artifacts")

    args = parser.parse_args(argv)

    contract_path = Path(args.contract_report_path)
    if not contract_path.exists():
        print(f"[ERROR] Contract report not found: {contract_path}", file=sys.stderr)
        return 1

    from core.schemas.api_contract import APIContractReport
    from core.api_test_generator import APITestGenerator

    raw = json.loads(contract_path.read_text(encoding="utf-8"))
    report = APIContractReport.from_dict(raw)

    output_dir = Path(args.outputs_root) / args.project_id / _ARTIFACT_DIR

    generator = APITestGenerator()
    gen_report = generator.generate(
        report,
        output_dir=str(output_dir),
        write=not args.no_write,
    )

    if not args.no_write:
        # Write manifest
        output_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "project_id": gen_report.project_id,
            "source_contract_file": gen_report.source_contract_file,
            "total_test_stubs": gen_report.total_test_stubs,
            "safe_endpoints_covered": gen_report.safe_endpoints_covered,
            "skipped_blocked_endpoints": gen_report.skipped_blocked_endpoints,
            "generated_files": [f.to_dict() for f in gen_report.generated_files],
            "executable_without_approval": False,
            "human_review_required": True,
            "notes": gen_report.notes,
        }
        (output_dir / "generated_tests_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
        print(f"[OK] Artifacts written to {output_dir}")

    print(f"[OK] Generated {gen_report.total_test_stubs} test stubs "
          f"covering {gen_report.safe_endpoints_covered} safe endpoints")
    print(f"     Skipped {gen_report.skipped_blocked_endpoints} blocked endpoints")
    print("     [NOTE] executable_without_approval=False — review before running")

    return 0


if __name__ == "__main__":
    sys.exit(main())

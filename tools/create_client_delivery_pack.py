#!/usr/bin/env python3
"""Phase 5P — Create Client Delivery Pack CLI.

Aggregates outputs from previous phases and generates a client-ready delivery
package with Markdown/HTML reports, test cases, risk matrix, and a ZIP archive.

Usage:
    python tools/create_client_delivery_pack.py --project-id demo-5m
    python tools/create_client_delivery_pack.py \\
        --project-id demo-5m \\
        --include-screenshots \\
        --include-generated-tests \\
        --include-cicd \\
        --require-human-review

Safety invariants (always enforced, no override possible):
    approved_for_client_delivery=False
    auto_send_to_client=False
    secret_scan_before_delivery=True
    human_review_required=True
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.client_delivery_pack import APP_VERSION, ClientDeliveryPack  # noqa: E402


def _blocked(flag: str) -> None:
    print(f"[BLOCKED] Flag '{flag}' is not permitted.", file=sys.stderr)
    print("  approved_for_client_delivery is always False.", file=sys.stderr)
    print("  auto_send_to_client is always False.", file=sys.stderr)
    print("  secret_scan_before_delivery is always True.", file=sys.stderr)
    sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="create_client_delivery_pack.py",
        description=f"AI QA Factory v{APP_VERSION} — Client Delivery Pack generator",
    )
    parser.add_argument("--project-id", required=True, help="Project identifier")
    parser.add_argument(
        "--include-screenshots", action="store_true",
        help="Include screenshot references in report",
    )
    parser.add_argument(
        "--include-generated-tests", action="store_true", default=True,
        help="Include generated test file references (default: True)",
    )
    parser.add_argument(
        "--include-cicd", action="store_true", default=True,
        help="Include CI/CD config references (default: True)",
    )
    parser.add_argument(
        "--require-human-review", action="store_true",
        help="(Always enforced; flag is informational only)",
    )
    parser.add_argument(
        "--no-write", action="store_true",
        help="Skip writing artifacts to disk (dry run)",
    )
    parser.add_argument(
        "--outputs-root", default="outputs",
        help="Root outputs directory (default: outputs/)",
    )
    # Blocked flags — accepted by argparse to give a clear error, not silently ignored
    parser.add_argument("--approve", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--auto-send", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--skip-secret-scan", action="store_true", help=argparse.SUPPRESS)

    args = parser.parse_args()

    if args.approve:
        _blocked("--approve")
    if args.auto_send:
        _blocked("--auto-send")
    if args.skip_secret_scan:
        _blocked("--skip-secret-scan")

    pack = ClientDeliveryPack(outputs_root=args.outputs_root)
    manifest = pack.build(
        project_id=args.project_id,
        include_screenshots=args.include_screenshots,
        include_generated_tests=args.include_generated_tests,
        include_cicd=args.include_cicd,
        write=not args.no_write,
    )

    print(f"[OK] Client delivery pack generated — project: {args.project_id}")
    print(f"     Artifacts:              {manifest.total_artifacts}")
    print(f"     Secret scan:            {'PASSED' if manifest.secret_scan.scan_passed else 'FAILED'}")
    print(f"     Approved for delivery:  {manifest.approved_for_client_delivery}")
    print(f"     Human review required:  {manifest.human_review_required}")
    print()
    print("[REVIEW REQUIRED] This package is NOT approved for client delivery.")
    print("  Complete Delivery_Checklist.md and obtain sign-off before sending.")

    if not manifest.secret_scan.scan_passed:
        blocked = manifest.secret_scan.blocked_files
        print(f"\n[BLOCKED] Secret scan failed — {len(blocked)} blocked file(s):", file=sys.stderr)
        for bf in blocked:
            print(f"  - {bf}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()

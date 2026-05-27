"""Phase 5N — Passive security smoke CLI.

Default mode: generate Playwright header-check skeleton spec (no network calls).
Approved execution mode: perform real passive HEAD request and check OWASP headers.

Safety: blocked flags (--active-scan, --exploit, --bypass-auth) always exit 1.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from core.passive_security_runner import PassiveSecurityRunner  # noqa: E402

_BLOCKED_FLAGS = {
    "--active-scan": "Active security scanning is always blocked (safety invariant).",
    "--exploit": "Exploit attempts are always blocked (safety invariant).",
    "--bypass-auth": "Auth bypass is always blocked (safety invariant).",
    "--fuzzing": "Fuzzing is always blocked (safety invariant).",
    "--skip-human-review": "Human review cannot be skipped (safety invariant).",
    "--approve-delivery": "Delivery approval must be done via human review, not CLI.",
}


def _blocked_flag_check(args_list: list[str]) -> None:
    for flag, reason in _BLOCKED_FLAGS.items():
        if flag in args_list:
            print(f"[BLOCKED] {flag}: {reason}", file=sys.stderr)
            sys.exit(1)


def main(argv: list[str] | None = None) -> None:
    _blocked_flag_check(sys.argv[1:] if argv is None else argv)

    parser = argparse.ArgumentParser(
        description="AI QA Factory — Phase 5N Passive Security Smoke",
    )
    parser.add_argument("--project-id", required=True, help="Project identifier")
    parser.add_argument("--target-url", required=True, help="Target URL for header inspection")
    parser.add_argument(
        "--outputs-root",
        default="outputs",
        help="Root directory for output artifacts (default: outputs)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Perform approved passive HEAD request (requires approval flag below)",
    )
    parser.add_argument(
        "--approve-public-readonly-execution",
        action="store_true",
        default=False,
        help="Approve passive public read-only HEAD request",
    )
    parser.add_argument(
        "--no-write",
        action="store_true",
        default=False,
        help="Dry run — do not write output files",
    )
    args = parser.parse_args(argv)

    runner = PassiveSecurityRunner(
        project_id=args.project_id,
        target_url=args.target_url,
        outputs_root=args.outputs_root,
    )

    if args.execute:
        try:
            report = runner.execute(
                approve_public_readonly=args.approve_public_readonly_execution,
                write_files=not args.no_write,
            )
        except ValueError as exc:
            print(f"[BLOCKED] {exc}", file=sys.stderr)
            sys.exit(1)
        except RuntimeError as exc:
            print(f"[ERROR] HEAD request failed: {exc}", file=sys.stderr)
            sys.exit(2)
    else:
        report = runner.generate_plan(write_files=not args.no_write)

    print(f"[OK] Passive security smoke — status: {report.status}")
    print(f"     Project:  {report.project_id}")
    print(f"     Target:   {report.target_url}")
    if report.status == "executed":
        print(f"     Headers:  {report.total_headers_checked} checked, {report.missing_headers} missing")
        if report.headers_missing:
            print(f"     Missing:  {', '.join(report.headers_missing)}")
        if report.headers_found:
            print(f"     Present:  {', '.join(report.headers_found)}")
    else:
        print(f"     Planned:  {len(report.headers_checked)} headers")
    if report.generated_test_file:
        print(f"     Spec:     {report.generated_test_file}")
    print(f"     Active scan: {report.active_scan_allowed} | Exploit: {report.exploit_attempts_allowed}")
    print(f"     Human review required: {report.human_review_required}")
    if report.status == "planning_only":
        print()
        print("[NOTE] Delivery report will show 'Generated checks only' until execution is approved.")


if __name__ == "__main__":
    main()

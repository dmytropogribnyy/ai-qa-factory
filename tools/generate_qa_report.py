"""
Phase 5F — QA Evidence Report Generator CLI.

Read-only. No execution. No network calls. No credentials.
Aggregates evidence from one or multiple source project outputs.

Example (single source):
    python tools/generate_qa_report.py \\
        --project-id first-real-auth-smoke

Example (multi-source combined report):
    python tools/generate_qa_report.py \\
        --project-id qa-demo-evidence-report \\
        --source-project-id first-real-auth-smoke \\
        --source-project-id restful-booker-api-smoke
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.qa_report_generator import QAReportGenerator


def _print_report(report, *, as_json: bool) -> None:
    if as_json:
        from core.qa_report_generator import QAReportGenerator as G
        gen = G()
        print(json.dumps(gen._report_to_dict(report), indent=2, default=str))
        return

    cov = report.coverage
    scan = report.secret_scan

    print("\nQA Evidence Report — Phase 5F")
    print(f"  project_id:      {report.project_id}")
    print(f"  sources:         {', '.join(report.source_project_ids)}")
    print(f"  generated_at:    {report.generated_at}")

    if cov:
        print("\nCoverage:")
        print(f"  total items:     {cov.total_evidence_items}")
        print(f"  passed:          {cov.passed}")
        print(f"  failed:          {cov.failed}")
        print(f"  missing:         {cov.missing}")
        print(f"  covered lanes:   {', '.join(cov.covered_lanes) or 'none'}")
        print(f"  not covered:     {', '.join(cov.not_covered) or 'none'}")

    print("\nEvidence items:")
    for src in report.sources:
        for item in src.evidence_items:
            sym = "PASS" if item.status == "passed" else (
                "FAIL" if item.status == "failed" else "MISS"
            )
            print(f"  [{sym}] {item.lane} — {item.target or item.target_category} "
                  f"({item.source_project_id}) — {item.commands_executed} cmd / {item.duration_seconds}s")

    if scan:
        verdict = scan.verdict.upper()
        print(f"\nSecret scan: {verdict}")
        for f in scan.findings:
            print(f"  WARN: {f}")
        if not scan.findings:
            print("  No raw secrets or unmasked tokens detected.")

    print(f"\n  execution_performed:          {report.execution_performed}")
    print(f"  network_calls_performed:      {report.network_calls_performed}")
    print(f"  raw_credentials_in_report:    {report.raw_credentials_in_report}")
    print(f"  storage_state_content_read:   {report.storage_state_content_read}")
    print(f"  safe_to_deliver:              {report.safe_to_deliver}")
    print(f"  approved_for_client_delivery: {report.approved_for_client_delivery}")
    print(f"  client_ready:                 {report.client_ready}")
    print(f"  human_review_required:        {report.human_review_required}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 5F — QA Evidence Report Generator",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--project-id", required=True,
                        help="Output project ID for this report")
    parser.add_argument("--source-project-id", action="append", dest="source_ids",
                        default=[], metavar="SOURCE_ID",
                        help="Source project ID to read evidence from (repeatable)")
    parser.add_argument("--source-projects",
                        default=None, metavar="ID1,ID2,...",
                        help="Comma-separated source project IDs (alternative to --source-project-id)")
    parser.add_argument("--outputs-root", default="outputs")
    parser.add_argument("--no-write", action="store_true", default=False)
    parser.add_argument("--json", action="store_true", default=False)

    args = parser.parse_args()

    # Combine sources from both flags
    source_ids = list(args.source_ids)
    if args.source_projects:
        source_ids += [s.strip() for s in args.source_projects.split(",") if s.strip()]
    # Deduplicate, preserve order
    seen = set()
    unique_sources = []
    for s in source_ids:
        if s not in seen:
            seen.add(s)
            unique_sources.append(s)

    gen = QAReportGenerator(outputs_root=Path(args.outputs_root))
    report = gen.generate(
        project_id=args.project_id,
        source_project_ids=unique_sources,
        write=not args.no_write,
    )

    _print_report(report, as_json=args.json)

    if not args.no_write:
        out = Path(args.outputs_root) / args.project_id / "14_qa_report"
        print(f"\nArtifacts written to: {out}/")

    scan = report.secret_scan
    if scan and scan.verdict == "fail":
        print("SECRET SCAN FAILED — review QA_REPORT_SECRET_SCAN.md", file=sys.stderr)
        return 2

    all_items = [i for s in report.sources for i in s.evidence_items]
    any_passed = any(i.status == "passed" for i in all_items)
    return 0 if any_passed else 1


if __name__ == "__main__":
    sys.exit(main())

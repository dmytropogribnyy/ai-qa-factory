"""CLI: build_report_drafts.py — Phase 4C Report Draft Builder.

Generates internal QA summary, client report draft, delivery note draft,
and report quality checklist from local artifacts.
No execution, no delivery approval, no client-ready marking.

Usage:
    python tools/build_report_drafts.py --project-id <id>
    python tools/build_report_drafts.py --project-id <id> --no-write
    python tools/build_report_drafts.py --project-id <id> --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.report_draft_builder import ReportDraftBuilder


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4C: Report Draft Builder — local artifacts only, no execution or delivery."
    )
    parser.add_argument("--project-id", required=True, help="Project ID")
    parser.add_argument("--scaffold-root", default=None, help="Scaffold root path (optional)")
    parser.add_argument("--no-write", action="store_true", help="Do not write artifacts to disk")
    parser.add_argument("--json", action="store_true", dest="json_out", help="Print JSON to stdout")
    parser.add_argument(
        "--outputs-root", default="outputs", help="Outputs root directory (default: outputs)"
    )
    args = parser.parse_args(argv)

    outputs_root = Path(args.outputs_root)
    builder = ReportDraftBuilder(outputs_root=outputs_root)

    scaffold_root = Path(args.scaffold_root) if args.scaffold_root else None
    internal, client_report, delivery_note, checklist = builder.build_report_drafts(
        args.project_id, scaffold_root
    )

    if args.json_out:
        print(json.dumps({
            "internal_qa_summary": internal.to_dict(),
            "client_report": client_report.to_dict(),
            "delivery_note": delivery_note.to_dict(),
            "quality_checklist": checklist.to_dict(),
        }, indent=2))
        return 0

    if not args.no_write:
        paths = builder.render_report_drafts(
            internal, client_report, delivery_note, checklist, args.project_id
        )
        print("Report draft artifacts written to:")
        for key, path in paths.items():
            print(f"  {key}: {path}")

    print("\nReport Drafts")
    print(f"  project_id:              {client_report.project_id}")
    print(f"  client report status:    {client_report.status}")
    print(f"  approved_for_delivery:   {client_report.approved_for_delivery}")
    print(f"  client_ready:            {checklist.client_ready}")
    print(f"  safe_to_deliver:         {checklist.safe_to_deliver}")
    print(f"  approval_checked:        {checklist.approval_checked}")

    print("\nSafety boundary:")
    print("  No execution performed.")
    print("  No URL fetching performed.")
    print("  No credentials used.")
    print("  approved_for_delivery=False.")
    print("  client_ready=False.")
    print("  safe_to_deliver=False.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

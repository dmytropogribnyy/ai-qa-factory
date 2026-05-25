"""CLI: build_evidence_foundation.py — Phase 4B Evidence Manager.

Registers existing local validation artifacts as internal evidence.
Creates evidence directory structure and quality gate.
No browser evidence collection, no Playwright, no URL fetching, no credentials.

Usage:
    python tools/build_evidence_foundation.py --project-id <id>
    python tools/build_evidence_foundation.py --project-id <id> --no-write
    python tools/build_evidence_foundation.py --project-id <id> --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.evidence_manager import EvidenceManager


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4B: Evidence Foundation — register local artifacts, no execution."
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
    manager = EvidenceManager(outputs_root=outputs_root)

    scaffold_root = Path(args.scaffold_root) if args.scaffold_root else None
    collection, quality_gate, redaction_report = manager.build_evidence_foundation(
        args.project_id, scaffold_root
    )

    if args.json_out:
        print(json.dumps({
            "collection": collection.to_dict(),
            "quality_gate": quality_gate.to_dict(),
            "redaction_report": redaction_report.to_dict(),
        }, indent=2))
        return 0

    if not args.no_write:
        paths = manager.render_evidence_artifacts(
            collection, quality_gate, redaction_report, args.project_id
        )
        print("Evidence artifacts written to:")
        for key, path in paths.items():
            print(f"  {key}: {path}")

    print("\nEvidence Foundation")
    print(f"  project_id:               {collection.project_id}")
    print(f"  total records:            {len(collection.records)}")
    print(f"  client_visible_count:     {collection.client_visible_count}")
    print(f"  internal_only_count:      {collection.internal_only_count}")
    print(f"  ready_for_client_review:  {collection.ready_for_client_review}")
    print(f"  approved_for_client_view: {quality_gate.approved_for_client_view}")
    print(f"  client_visible_blocked:   {redaction_report.client_visible_blocked}")

    print("\nSafety boundary:")
    print("  No browser evidence collection performed.")
    print("  No Playwright execution performed.")
    print("  No URL fetching performed.")
    print("  No credentials used.")
    print("  client_visible=False for all evidence records.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

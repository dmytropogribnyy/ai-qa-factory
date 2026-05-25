"""CLI: build_delivery_preview.py — Phase 4C Delivery Preview Builder.

Builds a delivery package preview manifest and safety checklist.
No zip/package creation, no approved_for_delivery=True.

Usage:
    python tools/build_delivery_preview.py --project-id <id>
    python tools/build_delivery_preview.py --project-id <id> --no-write
    python tools/build_delivery_preview.py --project-id <id> --json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.delivery_preview_builder import DeliveryPreviewBuilder


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Phase 4C: Delivery Preview Builder — preview manifest only, no packaging."
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
    builder = DeliveryPreviewBuilder(outputs_root=outputs_root)

    scaffold_root = Path(args.scaffold_root) if args.scaffold_root else None
    preview, checklist = builder.build_delivery_preview(args.project_id, scaffold_root)

    if args.json_out:
        print(json.dumps({
            "delivery_package_preview": preview.to_dict(),
            "delivery_safety_checklist": checklist.to_dict(),
        }, indent=2))
        return 0

    if not args.no_write:
        paths = builder.render_delivery_preview_artifacts(preview, checklist, args.project_id)
        print("Delivery preview artifacts written to:")
        for key, path in paths.items():
            print(f"  {key}: {path}")

    print("\nDelivery Preview")
    print(f"  project_id:           {preview.project_id}")
    print(f"  preview_status:       {preview.preview_status}")
    print(f"  package_created:      {preview.package_created}")
    print(f"  zip_created:          {preview.zip_created}")
    print(f"  approved_for_delivery:{preview.approved_for_delivery}")
    print(f"  candidate items:      {len(preview.items)}")
    print(f"  excluded items:       {len(preview.excluded_items)}")
    print(f"  safe_to_package:      {checklist.safe_to_package}")

    print("\nSafety boundary:")
    print("  No package created.")
    print("  No zip archive created.")
    print("  No execution performed.")
    print("  No URL fetching performed.")
    print("  approved_for_delivery=False.")
    print("  safe_to_package=False.")

    return 0


if __name__ == "__main__":
    sys.exit(main())

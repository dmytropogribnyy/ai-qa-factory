"""Session-independent writer relaunch runner (Issue #17).

Launches a bounded Claude writer on the next pending product packet — a FRESH ``claude`` process via the
existing ClaudeCodeWorker adapter, NOT the interactive session. A failed launch (most importantly an
exhausted Claude quota) releases the packet for a free retry next cycle, so a brand-new session resumes
the work automatically once quota returns. Invoked by the durable supervisor (or manually).

    python tools/collab_relaunch.py --once
    python tools/collab_relaunch.py --status
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.collaboration.product_packet import ProductPacketStore  # noqa: E402
from core.collaboration.relaunch import relaunch_once, summary  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AI QA Factory session-independent writer relaunch")
    ap.add_argument("--output-root", default="outputs")
    ap.add_argument("--workspace", default=str(REPO))
    ap.add_argument("--once", action="store_true", help="run a single relaunch cycle and exit")
    ap.add_argument("--status", action="store_true", help="print packet summary and exit")
    args = ap.parse_args(argv)

    store = ProductPacketStore(args.output_root)
    if args.status:
        print(json.dumps(summary(store), ensure_ascii=False, default=str))
        return 0

    from core.orchestration.claude_worker import ClaudeCodeWorker
    out = relaunch_once(store, ClaudeCodeWorker(), workspace=args.workspace)
    print(json.dumps(out, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())

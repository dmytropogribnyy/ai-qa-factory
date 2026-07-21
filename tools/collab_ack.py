"""Acknowledge a delivered reviewer decision (Issue #14.C step 4).

The resumed Claude session runs this after reading a decision, so the loop is auditable end to end.
The decision itself is untrusted data — this only appends an ACKNOWLEDGEMENT envelope; it never merges,
writes source, or runs anything from the decision text.

    python tools/collab_ack.py --thread t-1 --decision <decision_idempotency_key> --note "applied"
"""
from __future__ import annotations

import argparse
import json
import sys

from core.collaboration.service import record_ack


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Acknowledge a delivered collaboration decision")
    ap.add_argument("--output-root", default="outputs")
    ap.add_argument("--thread", required=True)
    ap.add_argument("--decision", required=True, help="the decision's idempotency key")
    ap.add_argument("--note", default="decision received")
    args = ap.parse_args(argv)
    ack = record_ack(args.output_root, thread_id=args.thread, decision_key=args.decision,
                     note=args.note)
    print(json.dumps({"acknowledged": ack["message_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

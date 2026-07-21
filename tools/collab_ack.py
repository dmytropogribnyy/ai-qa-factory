"""Acknowledge a delivered reviewer reply (Issue #14.C step 4).

The resumed Claude session runs this after reading the decision, so the loop is auditable end to end.
Identifiers are read ONLY from the validated immutable decision data file (``--decision-file``) — they
are never interpolated into the command Claude is told to run, so a crafted id can never alter it. The
decision is untrusted data; this only appends an ACKNOWLEDGEMENT envelope and never merges, writes
source, or runs anything from the decision text.

    python tools/collab_ack.py --decision-file "<path-to>.decision.json"
    python tools/collab_ack.py --output-root outputs --thread t-1 --decision <key>   # manual form
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.collaboration.service import record_ack


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Acknowledge a delivered collaboration reply")
    ap.add_argument("--decision-file", default="",
                    help="path to the immutable decision data file; ids are read from it")
    ap.add_argument("--output-root", default="outputs")
    ap.add_argument("--thread", default="")
    ap.add_argument("--decision", default="", help="the decision's idempotency key (manual form)")
    ap.add_argument("--note", default="decision received")
    args = ap.parse_args(argv)

    if args.decision_file:
        path = Path(args.decision_file).resolve()
        data = json.loads(path.read_text(encoding="utf-8"))
        thread = str(data.get("thread_id", ""))
        decision_key = str(data.get("idempotency_key", ""))
        # The file lives at <output_root>/_review_relay/collab_delivery/<name>.decision.json.
        output_root = str(path.parent.parent.parent)
    else:
        thread, decision_key, output_root = args.thread, args.decision, args.output_root

    if not thread or not decision_key:
        print(json.dumps({"error": "missing thread_id / decision key"}), file=sys.stderr)
        return 2
    ack = record_ack(output_root, thread_id=thread, decision_key=decision_key, note=args.note)
    print(json.dumps({"acknowledged": ack["message_id"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())

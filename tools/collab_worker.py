"""Session-independent writer state-machine CLI (Issue #17, GPT pull-first direction).

The fresh detached Claude writer drives the canonical protocol with these subcommands over the shared
Direct-Driver store (no network, no MCP, no spend while waiting):

    proposal   --output-root <ctrl> --thread <pkt> --branch <b> --body-file plan.md
    wait       --output-root <ctrl> --thread <pkt> --in-reply-to <key> --timeout 900
    ack        --output-root <ctrl> --thread <pkt> --decision-key <key>
    checkpoint --output-root <ctrl> --thread <pkt> --branch <b> --body-file cp.md
    status     --output-root <ctrl> --thread <pkt>

proposal/checkpoint are phase-idempotent (a restart never re-asks the reviewer); wait blocks on a
bounded local poll and returns the reply correlated by exact in_reply_to (exit 3 on timeout); ack is
idempotent. All logic lives in core.collaboration.worker_protocol; this is a thin, safe wrapper.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.collaboration.envelopes import EnvelopeError  # noqa: E402
from core.collaboration.store import CollaborationStoreError  # noqa: E402
from core.collaboration.worker_protocol import (  # noqa: E402
    ack,
    submit_request,
    wait_for_reply,
    worker_status,
)


def _body(args) -> str:
    return Path(args.body_file).read_text(encoding="utf-8") if getattr(args, "body_file", "") else args.body


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AI QA Factory session-independent writer protocol CLI")
    ap.add_argument("--output-root", required=True, help="the CONTROLLER output root (shared store)")
    ap.add_argument("--thread", required=True, help="thread id == product packet id")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("proposal", "checkpoint"):
        sp = sub.add_parser(name)
        sp.add_argument("--branch", default="")
        sp.add_argument("--head-sha", default="")
        sp.add_argument("--pr", default=None)
        sp.add_argument("--body", default="")
        sp.add_argument("--body-file", default="")
        sp.add_argument("--workspace", default=".")

    wp = sub.add_parser("wait")
    wp.add_argument("--in-reply-to", required=True)
    wp.add_argument("--timeout", type=float, default=900.0)
    wp.add_argument("--poll", type=float, default=3.0)

    ap_ = sub.add_parser("ack")
    ap_.add_argument("--decision-key", required=True)
    ap_.add_argument("--note", default="")

    sub.add_parser("status")

    args = ap.parse_args(argv)
    out, thread = args.output_root, args.thread

    try:
        if args.cmd in ("proposal", "checkpoint"):
            res = submit_request(out, thread_id=thread, kind=args.cmd.upper(), body=_body(args),
                                 branch=args.branch, head_sha=args.head_sha, pr_number=args.pr,
                                 workspace=args.workspace)
            print(json.dumps(res, ensure_ascii=False))
            return 0
        if args.cmd == "wait":
            reply = wait_for_reply(out, thread_id=thread, in_reply_to=args.in_reply_to,
                                   timeout_s=args.timeout, poll_s=args.poll)
            if reply is None:
                print(json.dumps({"status": "timeout", "in_reply_to": args.in_reply_to}))
                return 3                                        # a free retry state, not an error
            print(json.dumps({"status": "reply", "kind": reply.get("kind"),
                              "verdict": reply.get("verdict", ""), "body": reply.get("body", ""),
                              "decision_key": reply.get("idempotency_key"),
                              "reviewed_sha": reply.get("reviewed_sha", "")}, ensure_ascii=False))
            return 0
        if args.cmd == "ack":
            rec = ack(out, thread_id=thread, decision_key=args.decision_key, note=args.note)
            print(json.dumps({"message_id": rec.get("message_id")}))
            return 0
        if args.cmd == "status":
            print(json.dumps(worker_status(out, {"packet_id": thread}), ensure_ascii=False))
            return 0
    except (EnvelopeError, CollaborationStoreError, ValueError) as exc:
        print(f"{args.cmd} rejected: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())

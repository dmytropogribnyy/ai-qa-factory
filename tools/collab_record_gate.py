"""Record the trusted gate manifest for one exact SHA (Issue #74 A3.5).

Without a manifest, `reviewer_driver` can never authorize a CHECKPOINT -> GO; it escalates with
"no trusted CI/test manifest for this exact SHA". This is the trusted local producer that writes it.

It takes no evidence VALUES. It derives them: the SHA must be the repository's real current HEAD on a
clean tree, the CI conclusion is looked up for that exact SHA, and the audits and test suite are
actually executed here so their real exit codes and real counts are recorded.

Run it from the repo root, on the exact candidate HEAD, AFTER pushing so CI has a conclusion:

    python tools/collab_record_gate.py --sha <40-hex>

This runs the full required gate, so expect it to take as long as that gate takes. It is a material
gate, not an inner-loop command. A `success: false` result is a legitimate outcome, not an error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Same bootstrap idiom as tools/collab_supervisor.py: this must work as the exact command shape a
# bounded session is told to run, where Python puts `tools/` on sys.path rather than the repo root.
REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))


def main(argv=None) -> int:
    from core.collaboration.gate_producer import GateEvidenceError, produce_gate_manifest

    ap = argparse.ArgumentParser(description="Record the trusted CI/test gate manifest for one SHA")
    ap.add_argument("--sha", required=True, help="the exact full 40-character head SHA")
    ap.add_argument("--output-root", default="outputs")
    ap.add_argument("--repo-root", default=str(REPO))
    ap.add_argument("--python", default=sys.executable,
                    help="interpreter used to run the audits and the test suite")
    ap.add_argument("--notes", default="")
    args = ap.parse_args(argv)

    try:
        manifest = produce_gate_manifest(args.output_root, args.repo_root, args.sha,
                                         python_bin=args.python, notes=args.notes)
    except GateEvidenceError as exc:
        # Fail closed and say exactly why the evidence could not describe this SHA.
        print(json.dumps({"status": "refused", "reason": str(exc)}), file=sys.stderr)
        return 2

    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    # A recorded-but-unsuccessful gate is a valid, useful outcome — distinguish it from a refusal.
    return 0 if manifest.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())

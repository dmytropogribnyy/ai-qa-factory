"""v3.2 P0-D - a representative MULTI-FILE autonomous workload through the PRODUCTION lifecycle.

Not a one-line edit: a small multi-file project with a cross-file defect is driven through the real
WorkExecutionService end to end — worker implementation, a STRUCTURED pre-approved validation command
(from operator policy, never HTTP), a genuine failing-before validation with redacted failure
evidence, an OPERATOR-TRIGGERED resume/repair (not an autonomous loop), passing-after validation,
review, prepared delivery with manifest/hash verification, and a fresh-process resume.

The worker is the deterministic, labelled `FixtureClaudeWorker` (CI-safe); the identical lifecycle is
driven live by the operator-gated `ClaudeCodeWorker` (see docs/LIVE_CLAUDE_ACCEPTANCE_V32.md), and
real TypeScript/Playwright *execution* is separately proven by the browser-acceptance job. Automatic
repair is deliberately operator-triggered (a second approved execution), not a self-looping agent.
"""
from __future__ import annotations

import json
import sys

from core.orchestration.claude_worker import ClaudeWorkerExecutor, FixtureClaudeWorker
from core.orchestration.client_work import ClientWorkService
from core.orchestration.operator_executor import CommandValidationExecutor
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionService

_BRIEF = "Fix a small multi-module Python project so its regression suite passes across files."
# The structured, pre-approved validation argv originates from operator policy — never from HTTP.
_VALIDATION_ARGV = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_pkg.py"]


def _svc(tmp_path):
    return WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))


def test_golden_multifile_lifecycle(tmp_path):
    pid = "golden"
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(_BRIEF, pid)
    ws = tmp_path / pid / "40_ark_work"
    # A multi-FILE project with a cross-file defect: a.py and b.py are both wrong; the suite imports
    # both and fails until BOTH are corrected.
    (ws / "a.py").write_text("def val_a():\n    return 1  # bug: should be 2\n", encoding="utf-8")
    (ws / "b.py").write_text("def val_b():\n    return 10  # bug: should be 20\n", encoding="utf-8")
    (ws / "test_pkg.py").write_text(
        "from a import val_a\nfrom b import val_b\n\n"
        "def test_values():\n    assert val_a() == 2\n    assert val_b() == 20\n", encoding="utf-8")

    svc = _svc(tmp_path)
    svc.approve(pid, reviewer="op")

    # --- Attempt 1: worker produces an INCOMPLETE multi-file change (b.py still wrong) ---
    attempt1 = ClaudeWorkerExecutor(FixtureClaudeWorker(
        edits={"b.py": "def val_b():\n    return 99  # still wrong\n"}))
    state, outcome = svc.execute(pid, attempt1)
    assert state.status == "VERIFYING" and "b.py" in outcome.files_changed

    # Validation genuinely FAILS (val_a still 1) -> REPAIR_REQUIRED, with redacted evidence recorded.
    state, res = svc.validate(pid, CommandValidationExecutor(_VALIDATION_ARGV))
    assert not res.passed and state.status == "REPAIR_REQUIRED"
    ev_idx = json.loads((ws / "EVIDENCE_INDEX.json").read_text(encoding="utf-8"))
    val_ev = [e for e in ev_idx["evidence"] if e["relative_path"].startswith("evidence/validation/")]
    assert val_ev, "the failing validation must record evidence"
    # The recorded stdout/stderr are bounded + secret-redacted (no raw token-like content).
    meta = next(e for e in val_ev if e["relative_path"].endswith("metadata.json"))
    md = json.loads((ws / meta["relative_path"]).read_text(encoding="utf-8"))
    assert md["passed"] is False and md["cwd_confined_to_workspace"] is True

    # --- Operator-triggered resume/repair: a second APPROVED execution completes BOTH files ---
    attempt2 = ClaudeWorkerExecutor(FixtureClaudeWorker(edits={
        "a.py": "def val_a():\n    return 2\n", "b.py": "def val_b():\n    return 20\n"}), resume=True)
    state, outcome2 = svc.execute(pid, attempt2)
    assert state.status == "VERIFYING"
    assert "a.py" in outcome2.files_changed and "b.py" in outcome2.files_changed   # multi-file

    # Passing-after validation.
    state, res2 = svc.validate(pid, CommandValidationExecutor(_VALIDATION_ARGV))
    assert res2.passed and state.status == "READY_FOR_REVIEW"

    # Review -> prepared delivery -> manifest/hash verification (the exact multi-file package).
    svc.review(pid, reviewer="op", approved=True)
    manifest = svc.prepare_delivery(pid)
    assert svc.status(pid).status == "DELIVERY_PREPARED"
    assert "a.py" in manifest["included"]["artifacts"] and "b.py" in manifest["included"]["artifacts"]
    assert manifest["manifest_digest"].startswith("sha256:")
    hashes = manifest["artifact_hashes"]
    assert "a.py" in hashes and "b.py" in hashes and "DELIVERY_REPORT.md" in hashes

    # Fresh-process resume: a brand-new service instance reloads the sealed state from disk, and
    # mark_delivered re-verifies every included file's hash before completing.
    fresh = _svc(tmp_path)
    assert fresh.resume(pid).status == "DELIVERY_PREPARED"
    done = fresh.mark_delivered(pid, note="operator sent the package manually")
    assert done.status == "COMPLETED"


def test_autorepair_is_operator_triggered_not_a_loop(tmp_path):
    # Honesty guard for the narrowed autonomy claim: the service exposes NO automatic
    # repair/revalidation loop. Repair happens only when the operator triggers a new execution.
    assert not hasattr(WorkExecutionService, "auto_repair")
    assert not hasattr(WorkExecutionService, "run_until_green")

"""v3.0.2 M1 - the non-bypassable delivery-preparation boundary (DELIVERY_PREPARED).

COMPLETED is reachable only through prepare_delivery(): the final rehash, post-validation change
detection, the delivery secret scan, manifest creation, and exact content verification can never be
skipped by calling mark-delivered directly. mark_delivered records the operator's assertion that
the prepared package was sent manually - it sends nothing itself.
"""
from __future__ import annotations

import json

import pytest

from core.orchestration.client_work import ClientWorkService
from core.orchestration.operator_executor import OperatorWorkspaceExecutor, ProducedArtifact
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionError, WorkExecutionService
from core.orchestration.work_state_manager import InvalidTransitionError
from core.schemas.work_execution import ValidationOutcome
from core.schemas.work_run_state import ALLOWED_TRANSITIONS


def _svc(tmp_path):
    return WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))


def _passing_validator(_ctx):
    return ValidationOutcome(passed=True, tests_run=1, tests_passed=1, report="ok")


def _ws(tmp_path, pid):
    return tmp_path / pid / "40_ark_work"


def _drive_to(tmp_path, pid, upto):
    """Drive a real project to a named lifecycle point using the public service API."""
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Reproduce and fix a defect in a small Python module and add a regression test.", pid)
    ws = _ws(tmp_path, pid)
    (ws / "deliverable.txt").write_text("the fix\n", encoding="utf-8")
    (ws / "evidence").mkdir(exist_ok=True)
    (ws / "evidence" / "run.txt").write_text("regression output\n", encoding="utf-8")
    svc = _svc(tmp_path)
    svc.approve(pid, reviewer="op")
    ex = OperatorWorkspaceExecutor(
        [ProducedArtifact("deliverable.txt", "fix"),
         ProducedArtifact("evidence/run.txt", "report", is_evidence=True,
                          evidence_kind="test_output", description="regression evidence")],
        _passing_validator)
    svc.execute(pid, ex)
    svc.validate(pid, ex)
    if upto == "validated":
        return svc
    svc.review(pid, reviewer="op", approved=True, note="reviewed")
    if upto == "reviewed":
        return svc
    svc.prepare_delivery(pid)
    assert svc.status(pid).status == "DELIVERY_PREPARED"
    return svc


def test_direct_ready_for_delivery_to_completed_is_impossible():
    assert "COMPLETED" not in ALLOWED_TRANSITIONS["READY_FOR_DELIVERY"]
    assert "COMPLETED" in ALLOWED_TRANSITIONS["DELIVERY_PREPARED"]


def test_mark_delivered_before_prepare_delivery_is_rejected(tmp_path):
    svc = _drive_to(tmp_path, "p", "reviewed")           # READY_FOR_DELIVERY, never prepared
    with pytest.raises(WorkExecutionError) as exc:
        svc.mark_delivered("p")
    assert "DELIVERY_PREPARED" in str(exc.value)
    assert svc.status("p").status == "READY_FOR_DELIVERY"


def test_mark_delivered_after_validation_without_review_is_rejected(tmp_path):
    svc = _drive_to(tmp_path, "p", "validated")          # READY_FOR_REVIEW, no review
    with pytest.raises(WorkExecutionError):
        svc.mark_delivered("p")
    with pytest.raises(WorkExecutionError):              # preparation itself needs the review too
        svc.prepare_delivery("p")


def test_mark_delivered_after_artifact_change_is_rejected(tmp_path):
    svc = _drive_to(tmp_path, "p", "prepared")
    (_ws(tmp_path, "p") / "deliverable.txt").write_text("tampered\n", encoding="utf-8")
    with pytest.raises(WorkExecutionError) as exc:
        svc.mark_delivered("p")
    assert "changed after preparation" in str(exc.value)


def test_mark_delivered_after_evidence_change_is_rejected(tmp_path):
    svc = _drive_to(tmp_path, "p", "prepared")
    (_ws(tmp_path, "p") / "evidence" / "run.txt").write_text("edited evidence\n", encoding="utf-8")
    with pytest.raises(WorkExecutionError) as exc:
        svc.mark_delivered("p")
    assert "changed after preparation" in str(exc.value)


def test_mark_delivered_after_manifest_change_is_rejected(tmp_path):
    svc = _drive_to(tmp_path, "p", "prepared")
    mpath = _ws(tmp_path, "p") / "WORK_DELIVERY_MANIFEST.json"
    manifest = json.loads(mpath.read_text(encoding="utf-8"))
    manifest["note"] = "edited after preparation"
    mpath.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    with pytest.raises(WorkExecutionError) as exc:
        svc.mark_delivered("p")
    assert "manifest changed after preparation" in str(exc.value)


def test_mark_delivered_with_missing_prepared_file_is_rejected(tmp_path):
    svc = _drive_to(tmp_path, "p", "prepared")
    (_ws(tmp_path, "p") / "deliverable.txt").unlink()
    with pytest.raises(WorkExecutionError) as exc:
        svc.mark_delivered("p")
    assert "changed after preparation" in str(exc.value)


def test_mark_delivered_with_missing_manifest_is_rejected(tmp_path):
    svc = _drive_to(tmp_path, "p", "prepared")
    (_ws(tmp_path, "p") / "WORK_DELIVERY_MANIFEST.json").unlink()
    with pytest.raises(WorkExecutionError) as exc:
        svc.mark_delivered("p")
    assert "missing or corrupt" in str(exc.value)


def test_secret_content_cannot_reach_delivery_prepared(tmp_path):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Reproduce and fix a defect in a small Python module.", "s")
    ws = _ws(tmp_path, "s")
    (ws / "config.txt").write_text("aws_key=AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8")
    svc = _svc(tmp_path)
    svc.approve("s", reviewer="op")
    ex = OperatorWorkspaceExecutor([ProducedArtifact("config.txt", "report")], _passing_validator)
    svc.execute("s", ex)
    svc.validate("s", ex)
    svc.review("s", reviewer="op", approved=True)
    with pytest.raises(WorkExecutionError) as exc:
        svc.prepare_delivery("s")
    assert "secret-like content" in str(exc.value)
    assert svc.status("s").status == "READY_FOR_DELIVERY"   # never DELIVERY_PREPARED
    with pytest.raises(WorkExecutionError):                 # and completion stays impossible
        svc.mark_delivered("s")


def test_valid_prepared_delivery_completes_exactly_once_and_stays_terminal(tmp_path):
    svc = _drive_to(tmp_path, "p", "prepared")
    state = svc.mark_delivered("p", note="sent by hand")
    assert state.status == "COMPLETED"
    record = json.loads((_ws(tmp_path, "p") / "DELIVERY_RECORD.json").read_text(encoding="utf-8"))
    assert "sent nothing itself" in record["statement"]
    with pytest.raises((WorkExecutionError, InvalidTransitionError)):   # exactly once; terminal
        svc.mark_delivered("p")
    assert svc.status("p").status == "COMPLETED"


def test_prepared_manifest_records_every_included_file_hash(tmp_path):
    svc = _drive_to(tmp_path, "p", "prepared")
    ws = _ws(tmp_path, "p")
    manifest = json.loads((ws / "WORK_DELIVERY_MANIFEST.json").read_text(encoding="utf-8"))
    assert set(manifest["included_files"]) == {"deliverable.txt", "evidence/run.txt"}
    assert all(len(h) == 64 for h in manifest["artifact_hashes"].values())
    assert manifest["manifest_digest"].startswith("sha256:")
    prepared = json.loads((ws / "DELIVERY_PREPARED.json").read_text(encoding="utf-8"))
    assert prepared["manifest_digest"] == manifest["manifest_digest"]
    assert len(prepared["manifest_sha256"]) == 64
    assert svc.status("p").delivery_ready

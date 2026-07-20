"""v3.1 M0.1 - reopen-delivery recovery + M0.2 exact-package delivery documents.

reopen-delivery is only allowed from DELIVERY_PREPARED. It archives the prepared manifest + seal as
audit history, then either returns to READY_FOR_DELIVERY (drafts/metadata only) or drops to
REPAIR_REQUIRED and invalidates the review when the validated registered content changed. The exact
delivery package includes DELIVERY_REPORT.md + CLIENT_MESSAGE.md, hashed and integrity-checked.
"""
from __future__ import annotations

import json

import pytest

from core.orchestration.client_work import ClientWorkService
from core.orchestration.operator_executor import OperatorWorkspaceExecutor, ProducedArtifact
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionError, WorkExecutionService
from core.schemas.work_execution import ValidationOutcome


def _svc(tmp_path):
    return WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))


def _ws(tmp_path, pid):
    return tmp_path / pid / "40_ark_work"


def _passing(_ctx):
    return ValidationOutcome(passed=True, tests_run=1, tests_passed=1, report="ok")


def _prepared(tmp_path, pid="p"):
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
                          evidence_kind="test_output", description="evidence")], _passing)
    svc.execute(pid, ex)
    svc.validate(pid, ex)
    svc.review(pid, reviewer="op", approved=True)
    svc.prepare_delivery(pid)
    assert svc.status(pid).status == "DELIVERY_PREPARED"
    return svc


# --------------------------------------------------------------------- M0.2 exact package
def test_delivery_docs_are_in_the_exact_package_and_hashed(tmp_path):
    _prepared(tmp_path)
    ws = _ws(tmp_path, "p")
    manifest = json.loads((ws / "WORK_DELIVERY_MANIFEST.json").read_text(encoding="utf-8"))
    assert "DELIVERY_REPORT.md" in manifest["included_files"]
    assert "CLIENT_MESSAGE.md" in manifest["included_files"]
    assert manifest["included"]["delivery_docs"] == ["DELIVERY_REPORT.md", "CLIENT_MESSAGE.md"]
    assert len(manifest["artifact_hashes"]["DELIVERY_REPORT.md"]) == 64
    assert len(manifest["artifact_hashes"]["CLIENT_MESSAGE.md"]) == 64
    assert manifest["client_message_source"] == "generated"


def test_editing_a_delivery_doc_after_preparation_blocks_completion(tmp_path):
    svc = _prepared(tmp_path)
    (_ws(tmp_path, "p") / "DELIVERY_REPORT.md").write_text("tampered report\n", encoding="utf-8")
    with pytest.raises(WorkExecutionError) as exc:
        svc.mark_delivered("p")
    assert "changed after preparation" in str(exc.value)


def test_operator_edited_client_message_is_preserved_on_reprepare(tmp_path):
    svc = _prepared(tmp_path)
    ws = _ws(tmp_path, "p")
    (ws / "CLIENT_MESSAGE.md").write_text("Operator's hand-written note.\n", encoding="utf-8")
    # Reopen (drafts/metadata only) then re-prepare - the edited client message is preserved.
    svc.reopen_delivery("p", reviewer="op", reason="tweak the message")
    assert svc.status("p").status == "READY_FOR_DELIVERY"
    manifest = svc.prepare_delivery("p")
    assert manifest["client_message_source"] == "preserved"
    assert "hand-written" in (ws / "CLIENT_MESSAGE.md").read_text(encoding="utf-8")


# --------------------------------------------------------------------- M0.1 reopen-delivery
def test_reopen_requires_delivery_prepared(tmp_path):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Reproduce and fix a defect.", "q")
    svc = _svc(tmp_path)
    with pytest.raises(WorkExecutionError):
        svc.reopen_delivery("q", reviewer="op", reason="nope")


def test_reopen_drafts_only_returns_to_ready_for_delivery(tmp_path):
    svc = _prepared(tmp_path)
    entry = svc.reopen_delivery("p", reviewer="op", reason="fix a typo in the client message")
    assert entry["outcome"] == "READY_FOR_DELIVERY" and entry["registered_changed"] == []
    assert svc.status("p").status == "READY_FOR_DELIVERY"
    # The seal is gone; the operator can re-prepare cleanly.
    assert not (_ws(tmp_path, "p") / "DELIVERY_PREPARED.json").exists()
    svc.prepare_delivery("p")
    assert svc.status("p").status == "DELIVERY_PREPARED"


def test_reopen_after_validated_content_change_forces_repair(tmp_path):
    svc = _prepared(tmp_path)
    (_ws(tmp_path, "p") / "deliverable.txt").write_text("changed the fix\n", encoding="utf-8")
    entry = svc.reopen_delivery("p", reviewer="op", reason="the fix was wrong")
    assert entry["outcome"] == "REPAIR_REQUIRED" and "deliverable.txt" in entry["registered_changed"]
    assert svc.status("p").status == "REPAIR_REQUIRED"
    # Review is invalidated; you cannot jump back to prepare-delivery.
    review = json.loads((_ws(tmp_path, "p") / "REVIEW.json").read_text(encoding="utf-8"))
    assert review["approved"] is False


def test_reopen_preserves_audit_history(tmp_path):
    svc = _prepared(tmp_path)
    manifest = json.loads((_ws(tmp_path, "p") / "WORK_DELIVERY_MANIFEST.json").read_text(encoding="utf-8"))
    prev_digest = manifest["manifest_digest"]
    svc.reopen_delivery("p", reviewer="op", reason="audit please")
    hist = json.loads((_ws(tmp_path, "p") / "DELIVERY_HISTORY.json").read_text(encoding="utf-8"))
    assert hist["events"][0]["previous_manifest_digest"] == prev_digest
    assert hist["events"][0]["reviewer"] == "op" and hist["events"][0]["reason"] == "audit please"
    archived = _ws(tmp_path, "p") / "delivery_history" / "001" / "WORK_DELIVERY_MANIFEST.json"
    assert archived.exists()
    assert json.loads(archived.read_text(encoding="utf-8"))["manifest_digest"] == prev_digest


def test_reopen_then_repair_loop_completes(tmp_path):
    svc = _prepared(tmp_path)
    ws = _ws(tmp_path, "p")
    (ws / "deliverable.txt").write_text("v2 fix\n", encoding="utf-8")
    svc.reopen_delivery("p", reviewer="op", reason="content changed")
    assert svc.status("p").status == "REPAIR_REQUIRED"
    # Full loop again: execute -> validate -> review -> prepare -> mark delivered.
    ex = OperatorWorkspaceExecutor(
        [ProducedArtifact("deliverable.txt", "fix"),
         ProducedArtifact("evidence/run.txt", "report", is_evidence=True,
                          evidence_kind="test_output", description="evidence")], _passing)
    svc.execute("p", ex)
    svc.validate("p", ex)
    svc.review("p", reviewer="op", approved=True)
    svc.prepare_delivery("p")
    state = svc.mark_delivered("p", note="sent")
    assert state.status == "COMPLETED"

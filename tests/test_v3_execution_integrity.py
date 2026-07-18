"""v3.0.1 - WorkExecutionService integrity controls.

Project-id + artifact-path confinement, artifact/evidence hashing, post-validation change detection,
delivery-content secret scan, and the explicit operator review gate before READY_FOR_DELIVERY.
"""
from __future__ import annotations

import json

import pytest

from core.orchestration.client_work import ClientWorkService
from core.orchestration.operator_executor import OperatorWorkspaceExecutor, ProducedArtifact
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionError, WorkExecutionService
from core.schemas.work_execution import ExecutionArtifact, ExecutionOutcome, ValidationOutcome


def _analyze(tmp_path, pid):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Reproduce and fix a defect in a small Python module and add a regression test.", pid)


def _svc(tmp_path):
    return WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))


def _passing_validator(_ctx):
    return ValidationOutcome(passed=True, tests_run=1, tests_passed=1, report="ok")


class _TraversalExecutor:
    is_acceptance_fixture = False
    executor_id = "test:traversal"

    def execute(self, _ctx):
        return ExecutionOutcome(artifacts=[ExecutionArtifact("../escape.txt", "report")],
                                files_changed=["../escape.txt"])

    def validate(self, _ctx):
        return ValidationOutcome(passed=True)


def test_unsafe_project_id_is_rejected(tmp_path):
    svc = _svc(tmp_path)
    for bad in ("../evil", "a/b", "..", "c\\d"):
        with pytest.raises(WorkExecutionError):
            svc.status(bad)


def test_traversal_artifact_path_is_rejected(tmp_path):
    _analyze(tmp_path, "p")
    svc = _svc(tmp_path)
    svc.approve("p", reviewer="op")
    with pytest.raises(WorkExecutionError):
        svc.execute("p", _TraversalExecutor())


def test_artifact_hashes_recorded_at_execution(tmp_path):
    _analyze(tmp_path, "p")
    ws = tmp_path / "p" / "40_ark_work"
    (ws / "deliverable.txt").write_text("content\n", encoding="utf-8")
    svc = _svc(tmp_path)
    svc.approve("p", reviewer="op")
    svc.execute("p", OperatorWorkspaceExecutor([ProducedArtifact("deliverable.txt", "report")],
                                               _passing_validator))
    h = json.loads((ws / "ARTIFACT_HASHES.json").read_text(encoding="utf-8"))["hashes"]
    assert "deliverable.txt" in h and len(h["deliverable.txt"]) == 64


def test_post_validation_change_blocks_delivery(tmp_path):
    _analyze(tmp_path, "p")
    ws = tmp_path / "p" / "40_ark_work"
    (ws / "deliverable.txt").write_text("v1\n", encoding="utf-8")
    svc = _svc(tmp_path)
    svc.approve("p", reviewer="op")
    ex = OperatorWorkspaceExecutor([ProducedArtifact("deliverable.txt", "report")], _passing_validator)
    svc.execute("p", ex)
    svc.validate("p", ex)
    svc.review("p", reviewer="op", approved=True)
    (ws / "deliverable.txt").write_text("v2 tampered\n", encoding="utf-8")   # change AFTER review
    with pytest.raises(WorkExecutionError) as exc:
        svc.prepare_delivery("p")
    assert "changed after validation" in str(exc.value)


def test_delivery_secret_scan_blocks(tmp_path):
    _analyze(tmp_path, "p")
    ws = tmp_path / "p" / "40_ark_work"
    (ws / "config.txt").write_text("aws_key=AKIAIOSFODNN7EXAMPLE\n", encoding="utf-8")
    svc = _svc(tmp_path)
    svc.approve("p", reviewer="op")
    ex = OperatorWorkspaceExecutor([ProducedArtifact("config.txt", "report")], _passing_validator)
    svc.execute("p", ex)
    svc.validate("p", ex)
    svc.review("p", reviewer="op", approved=True)
    with pytest.raises(WorkExecutionError) as exc:
        svc.prepare_delivery("p")
    assert "secret-like content" in str(exc.value)


def test_review_gate_required_and_rejection_repairs(tmp_path):
    _analyze(tmp_path, "p")
    ws = tmp_path / "p" / "40_ark_work"
    (ws / "deliverable.txt").write_text("ok\n", encoding="utf-8")
    svc = _svc(tmp_path)
    svc.approve("p", reviewer="op")
    ex = OperatorWorkspaceExecutor([ProducedArtifact("deliverable.txt", "report")], _passing_validator)
    svc.execute("p", ex)
    state, _ = svc.validate("p", ex)
    assert state.status == "READY_FOR_REVIEW"
    with pytest.raises(WorkExecutionError):        # cannot skip the review gate
        svc.prepare_delivery("p")
    rejected = svc.review("p", reviewer="op", approved=False, note="needs work")
    assert rejected.status == "REPAIR_REQUIRED"

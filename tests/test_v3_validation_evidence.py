"""v3.0.2 M2 - validation output is real, registered, per-attempt evidence.

Every validation attempt gets a stable id and its own evidence/validation/<id>/ directory
(metadata.json + stdout.txt + stderr.txt) with structured provenance; attempts never overwrite
each other; the evidence is registered in EVIDENCE_INDEX.json and included in the validated +
delivery-prepared integrity snapshots; failures and timeouts still produce registered evidence;
no environment secrets are ever persisted.
"""
from __future__ import annotations

import json
import sys

import pytest

from core.orchestration.client_work import ClientWorkService
from core.orchestration.operator_executor import (
    CommandValidationExecutor,
    OperatorWorkspaceExecutor,
    ProducedArtifact,
    ValidationCommandError,
)
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionError, WorkExecutionService

_PY = sys.executable


def _svc(tmp_path):
    return WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))


def _ws(tmp_path, pid):
    return tmp_path / pid / "40_ark_work"


def _start(tmp_path, pid):
    """Analyze + approve + record a real operator artifact; leaves the project in VERIFYING."""
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Reproduce and fix a defect in a small Python module and add a regression test.", pid)
    ws = _ws(tmp_path, pid)
    (ws / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    svc = _svc(tmp_path)
    svc.approve(pid, reviewer="op")
    svc.execute(pid, OperatorWorkspaceExecutor([ProducedArtifact("calc.py", "fix")],
                                               executor_id="operator:cli"))
    return svc


def _index_paths(tmp_path, pid):
    idx = json.loads((_ws(tmp_path, pid) / "EVIDENCE_INDEX.json").read_text(encoding="utf-8"))
    return {e["relative_path"] for e in idx["evidence"]}


def test_successful_command_produces_registered_hashed_evidence(tmp_path):
    svc = _start(tmp_path, "p")
    state, result = svc.validate(
        "p", CommandValidationExecutor([_PY, "-c", "import calc; print('ok', calc.add(2, 3))"]))
    assert result.passed and state.status == "READY_FOR_REVIEW"
    vid = result.details["validation_id"]
    vdir = _ws(tmp_path, "p") / "evidence" / "validation" / vid
    meta = json.loads((vdir / "metadata.json").read_text(encoding="utf-8"))
    assert meta["exit_code"] == 0 and meta["passed"] is True and meta["argv"][0] == _PY
    assert meta["project_id"] == "p" and meta["timed_out"] is False
    assert meta["started_at"] and meta["finished_at"] and meta["timeout_s"] > 0
    assert "ok 5" in (vdir / "stdout.txt").read_text(encoding="utf-8")
    assert len(meta["stdout"]["sha256"]) == 64 and len(meta["stderr"]["sha256"]) == 64
    # Registered in the real evidence index AND in the validated integrity snapshot.
    paths = _index_paths(tmp_path, "p")
    assert f"evidence/validation/{vid}/stdout.txt" in paths
    validated = json.loads((_ws(tmp_path, "p") / "VALIDATED_ARTIFACTS.json")
                           .read_text(encoding="utf-8"))["hashes"]
    assert f"evidence/validation/{vid}/metadata.json" in validated


def test_failed_command_still_produces_registered_evidence(tmp_path):
    svc = _start(tmp_path, "p")
    state, result = svc.validate(
        "p", CommandValidationExecutor([_PY, "-c", "raise SystemExit(3)"]))
    assert not result.passed and state.status == "REPAIR_REQUIRED"
    vid = result.details["validation_id"]
    meta = json.loads((_ws(tmp_path, "p") / "evidence" / "validation" / vid / "metadata.json")
                      .read_text(encoding="utf-8"))
    assert meta["exit_code"] == 3 and meta["passed"] is False
    assert f"evidence/validation/{vid}/metadata.json" in _index_paths(tmp_path, "p")


def test_timeout_produces_registered_evidence(tmp_path):
    svc = _start(tmp_path, "p")
    state, result = svc.validate(
        "p", CommandValidationExecutor([_PY, "-c", "import time; time.sleep(60)"], timeout_s=1))
    assert not result.passed and result.details["timed_out"] is True
    vid = result.details["validation_id"]
    meta = json.loads((_ws(tmp_path, "p") / "evidence" / "validation" / vid / "metadata.json")
                      .read_text(encoding="utf-8"))
    assert meta["timed_out"] is True and meta["exit_code"] is None
    assert f"evidence/validation/{vid}/stderr.txt" in _index_paths(tmp_path, "p")


def test_multiple_attempts_are_preserved_independently(tmp_path):
    svc = _start(tmp_path, "p")
    _, r1 = svc.validate("p", CommandValidationExecutor([_PY, "-c", "raise SystemExit(1)"]))
    # Repair loop: re-execute, then validate again - the first attempt's evidence survives.
    svc.execute("p", OperatorWorkspaceExecutor([ProducedArtifact("calc.py", "fix")],
                                               executor_id="operator:cli"))
    _, r2 = svc.validate("p", CommandValidationExecutor([_PY, "-c", "print('fixed')"]))
    v1, v2 = r1.details["validation_id"], r2.details["validation_id"]
    assert v1 != v2
    base = _ws(tmp_path, "p") / "evidence" / "validation"
    assert (base / v1 / "stdout.txt").exists() and (base / v2 / "stdout.txt").exists()
    paths = _index_paths(tmp_path, "p")
    assert f"evidence/validation/{v1}/stdout.txt" in paths      # earlier attempt still indexed
    assert f"evidence/validation/{v2}/stdout.txt" in paths


def test_modified_validation_evidence_blocks_delivery(tmp_path):
    svc = _start(tmp_path, "p")
    _, result = svc.validate("p", CommandValidationExecutor([_PY, "-c", "print('ok')"]))
    svc.review("p", reviewer="op", approved=True)
    vid = result.details["validation_id"]
    out = _ws(tmp_path, "p") / "evidence" / "validation" / vid / "stdout.txt"
    out.write_text("doctored output\n", encoding="utf-8")       # tamper AFTER validation
    with pytest.raises(WorkExecutionError) as exc:
        svc.prepare_delivery("p")
    assert "changed after validation" in str(exc.value)


def test_no_environment_secrets_are_persisted(tmp_path, monkeypatch):
    canary = "canary-secret-value-1234567890"
    monkeypatch.setenv("FACTORY_TEST_CANARY", canary)
    svc = _start(tmp_path, "p")
    _, result = svc.validate("p", CommandValidationExecutor([_PY, "-c", "print('done')"]))
    vdir = _ws(tmp_path, "p") / "evidence" / "validation" / result.details["validation_id"]
    for f in vdir.iterdir():
        text = f.read_text(encoding="utf-8")
        assert canary not in text, f.name                # no env value leaked
        assert "FACTORY_TEST_CANARY" not in text, f.name  # no env dump at all


def test_structured_argv_bounds_are_enforced():
    with pytest.raises(ValidationCommandError):
        CommandValidationExecutor([])
    with pytest.raises(ValidationCommandError):
        CommandValidationExecutor(["x"] * 65)
    with pytest.raises(ValidationCommandError):
        CommandValidationExecutor(["a" * 5000])
    with pytest.raises(ValidationCommandError):
        CommandValidationExecutor(["python", ""])

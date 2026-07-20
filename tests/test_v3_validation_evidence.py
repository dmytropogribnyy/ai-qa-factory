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


def test_secret_bearing_argv_is_redacted_in_evidence(tmp_path):
    # v3.1 M0.4: a token passed as an argument is redacted before being persisted as evidence.
    svc = _start(tmp_path, "p")
    token = "ghp_" + "a" * 36
    _, result = svc.validate("p", CommandValidationExecutor(
        [_PY, "-c", f"print('using {token}')"]))
    vdir = _ws(tmp_path, "p") / "evidence" / "validation" / result.details["validation_id"]
    meta = json.loads((vdir / "metadata.json").read_text(encoding="utf-8"))
    joined = " ".join(meta["argv"])
    assert token not in joined and "[REDACTED_github_token]" in joined
    # The redacted display is what is stored; the real command still ran (produced stdout).
    assert token not in (vdir / "metadata.json").read_text(encoding="utf-8")


def test_stdout_stderr_secret_canary_never_persisted_anywhere(tmp_path):
    # v3.2 5.4: a distinct GitHub-like token in EVERY field (argv, stdout, stderr) must not leave a
    # raw token ANYWHERE in the workspace (evidence, metadata, TEST_RESULTS, EVIDENCE_INDEX, state,
    # and — after delivery — manifest/report). Redaction metadata reports every affected field.
    t_argv, t_out, t_err = "ghp_" + "a" * 36, "ghp_" + "b" * 36, "ghp_" + "c" * 36
    svc = _start(tmp_path, "p")
    code = (f"import sys; print('stdout has {t_out} here'); "
            f"print('stderr has {t_err} too', file=sys.stderr)")
    _, result = svc.validate("p", CommandValidationExecutor(
        [_PY, "-c", code, "--token", t_argv]))
    vid = result.details["validation_id"]
    vdir = _ws(tmp_path, "p") / "evidence" / "validation" / vid
    meta = json.loads((vdir / "metadata.json").read_text(encoding="utf-8"))
    assert meta["redacted"] is True
    assert set(meta["redacted_fields"]) == {"argv", "stdout", "stderr"}
    assert meta["argv_redacted"] is True and meta["stdout"]["redacted"] is True
    # Advance to review so a delivery is prepared and also scanned.
    svc.review("p", reviewer="op", approved=True)
    svc.prepare_delivery("p")
    ws_root = tmp_path / "p"
    leaked = []
    for f in ws_root.rglob("*"):
        if f.is_file():
            try:
                text = f.read_text(encoding="utf-8", errors="strict")
            except (OSError, UnicodeDecodeError):
                continue
            for tok in (t_argv, t_out, t_err):
                if tok in text:
                    leaked.append(f"{f.relative_to(ws_root)}::{tok[:8]}")
    assert leaked == [], f"raw token leaked into: {leaked}"


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


def test_structured_argv_handles_spaces_in_paths_cross_platform(tmp_path):
    # v3.0.2 M3: structured argv is unambiguous for Windows paths and spaces (runs on both the
    # Linux core job and the windows-smoke job).
    from core.schemas.work_execution import ExecutionContext
    scripts = tmp_path / "my scripts dir"
    scripts.mkdir()
    (scripts / "check me.py").write_text("print('spaced ok')\n", encoding="utf-8")
    ctx = ExecutionContext(project_id="x", profile="", workspace_dir=str(tmp_path),
                           requirements=[], now="t")
    res = CommandValidationExecutor([_PY, str(scripts / "check me.py")]).validate(ctx)
    assert res.passed
    out = (tmp_path / "evidence" / "validation" / res.details["validation_id"] / "stdout.txt")
    assert "spaced ok" in out.read_text(encoding="utf-8")


def test_structured_argv_python_dash_c_with_quotes(tmp_path):
    from core.schemas.work_execution import ExecutionContext
    ctx = ExecutionContext(project_id="x", profile="", workspace_dir=str(tmp_path),
                           requirements=[], now="t")
    res = CommandValidationExecutor(
        [_PY, "-c", "print('hello world with \"quotes\"')"]).validate(ctx)
    assert res.passed
    out = (tmp_path / "evidence" / "validation" / res.details["validation_id"] / "stdout.txt")
    assert 'hello world with "quotes"' in out.read_text(encoding="utf-8")


def test_command_string_compatibility_tokenizes_posix_style():
    ex = CommandValidationExecutor('tool "an arg with spaces" plain')
    assert ex._argv == ["tool", "an arg with spaces", "plain"]


def test_structured_argv_bounds_are_enforced():
    with pytest.raises(ValidationCommandError):
        CommandValidationExecutor([])
    with pytest.raises(ValidationCommandError):
        CommandValidationExecutor(["x"] * 65)
    with pytest.raises(ValidationCommandError):
        CommandValidationExecutor(["a" * 5000])
    with pytest.raises(ValidationCommandError):
        CommandValidationExecutor(["python", ""])

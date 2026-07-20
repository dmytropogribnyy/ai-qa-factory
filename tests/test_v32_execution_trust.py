"""v3.2 P0-E / P0-1 / P0-2 - client-repo execution trust (control-store authority), private-work-dir
preflight, credential-stripped env, and fail-closed execution-boundary enforcement."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from core.orchestration.client_work import ClientWorkService
from core.orchestration.execution_trust import (
    CONTROL_DIR_ENV,
    TRUST_MARKER,
    TRUSTED_ROOTS_ENV,
    assess_execution_trust,
    preflight_work_isolation,
    revoke_execution_authority,
    stripped_subprocess_env,
)
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionError, WorkExecutionService
from core.schemas.work_execution import ExecutionOutcome

_REPO = Path(__file__).resolve().parents[1]


def _approved_ws(tmp_path, pid="p", reviewer="op"):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Fix a defect and add a regression test.", pid)
    WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).approve(
        pid, reviewer=reviewer)
    return tmp_path / pid / "40_ark_work"


# ------------------------------------------------------------ control-store authority (P0-1)
def test_untrusted_workspace_is_refused_with_exact_action(tmp_path):
    d = assess_execution_trust(str(tmp_path / "p" / "40_ark_work"))
    assert d.trusted is False and CONTROL_DIR_ENV in d.action and TRUSTED_ROOTS_ENV in d.action


def test_genuine_approval_writes_grant_outside_workdir_and_is_trusted(tmp_path):
    ws = _approved_ws(tmp_path)
    # The authoritative grant lives in the control store OUTSIDE the client work dir.
    grant = tmp_path / ".aiqa_control" / "p.grant.json"
    assert grant.is_file() and not (ws / "p.grant.json").exists()
    assert assess_execution_trust(str(ws)).trusted is True


def test_forged_consistent_workspace_files_without_grant_are_untrusted_and_never_execute(tmp_path):
    # P0-1 regression: a client checkout can pre-create ALL THREE mutually-consistent workspace files
    # (marker + APPROVAL + a READY_TO_EXECUTE state history) — with no genuine control-store grant it
    # is still untrusted, and a client-code executor is refused with ZERO invocations.
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze("x", "p")
    ws = tmp_path / "p" / "40_ark_work"
    at = "2026-07-19T00:00:00+00:00"
    (ws / TRUST_MARKER).write_text(json.dumps(
        {"approved_for_execution": True, "reviewer": "op", "project_id": "p", "at": at}),
        encoding="utf-8")
    (ws / "APPROVAL.json").write_text(json.dumps({"approved": True, "reviewer": "op", "at": at}),
                                      encoding="utf-8")
    state = json.loads((ws / "WORK_RUN_STATE.json").read_text(encoding="utf-8"))
    state["status"] = "READY_TO_EXECUTE"
    state.setdefault("history", []).append({"to_state": "READY_TO_EXECUTE", "actor": "op", "at": at})
    (ws / "WORK_RUN_STATE.json").write_text(json.dumps(state), encoding="utf-8")

    assert assess_execution_trust(str(ws)).trusted is False    # no control-store grant

    calls = []

    class _Spy:
        is_acceptance_fixture = False
        executes_client_code = True
        executor_id = "spy:client-code"

        def execute(self, ctx):
            calls.append("execute")
            return ExecutionOutcome()

    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    try:
        svc.execute("p", _Spy())
        raise AssertionError("execution must be refused on a forged trust set")
    except WorkExecutionError as exc:
        assert "grant" in str(exc).lower() or "untrusted" in str(exc).lower()
    assert calls == []                                          # the client-code executor never ran


def test_revoked_grant_fails_closed(tmp_path):
    ws = _approved_ws(tmp_path)
    assert assess_execution_trust(str(ws)).trusted is True
    revoke_execution_authority(str(ws))
    assert assess_execution_trust(str(ws)).trusted is False


def test_stale_tampered_approval_fails_closed(tmp_path):
    # Tampering the approval EVIDENCE (without a genuine approve, which rewrites the grant) breaks the
    # grant<->evidence generation binding and fails closed.
    ws = _approved_ws(tmp_path)
    assert assess_execution_trust(str(ws)).trusted is True
    a = json.loads((ws / "APPROVAL.json").read_text(encoding="utf-8"))
    a["at"] = "2099-01-01T00:00:00+00:00"
    (ws / "APPROVAL.json").write_text(json.dumps(a), encoding="utf-8")
    assert assess_execution_trust(str(ws)).trusted is False


def test_grant_workspace_binding_is_enforced(tmp_path):
    # A grant minted for one workspace must not authorise a different workspace path.
    ws = _approved_ws(tmp_path, pid="p")
    grant = tmp_path / ".aiqa_control" / "p.grant.json"
    g = json.loads(grant.read_text(encoding="utf-8"))
    g["workspace"] = str((tmp_path / "elsewhere").resolve())
    grant.write_text(json.dumps(g), encoding="utf-8")
    assert assess_execution_trust(str(ws)).trusted is False


def test_trusted_root_env_makes_workspace_trusted(tmp_path):
    ws = tmp_path / "root" / "proj"
    ws.mkdir(parents=True)
    d = assess_execution_trust(str(ws), env={TRUSTED_ROOTS_ENV: str(tmp_path / "root")})
    assert d.trusted is True


# ------------------------------------------------------------ private-work-dir preflight
def test_preflight_passes_outside_a_repo(tmp_path):
    assert preflight_work_isolation(str(tmp_path / "ws")).ok is True


def test_preflight_fails_closed_for_a_tracked_public_path():
    res = preflight_work_isolation(str(_REPO / "core" / "orchestration"))
    assert res.ok is False and "private" in res.action.lower()


def test_preflight_passes_for_gitignored_output_workspace():
    import shutil
    ws = _REPO / "outputs" / "_trust_probe_" / "40_ark_work"
    try:
        res = preflight_work_isolation(str(ws))
        assert res.ok is True and "git-ignored" in res.reason
    finally:
        shutil.rmtree(_REPO / "outputs" / "_trust_probe_", ignore_errors=True)


def test_stripped_env_removes_credentials_keeps_runtime():
    base = {"PATH": "/usr/bin", "HOME": "/home/op", "AWS_SECRET_ACCESS_KEY": "x", "GITHUB_TOKEN": "y",
            "MY_PASSWORD": "z", "SESSION_COOKIE": "c", "AIQA_CLAUDE_BIN": "/x/claude.exe",
            "PLAYWRIGHT_TEST_RUNTIME": "/rt"}
    out = stripped_subprocess_env(base)
    assert out["PATH"] == "/usr/bin" and out["HOME"] == "/home/op"
    assert out["AIQA_CLAUDE_BIN"] == "/x/claude.exe" and out["PLAYWRIGHT_TEST_RUNTIME"] == "/rt"
    for leaked in ("AWS_SECRET_ACCESS_KEY", "GITHUB_TOKEN", "MY_PASSWORD", "SESSION_COOKIE"):
        assert leaked not in out


# ------------------------------------------------------------ fail-closed boundary (P0-2)
def test_execute_fails_closed_when_capability_missing(tmp_path):
    # An executor that does not declare a boolean executes_client_code must be REFUSED (not assumed
    # safe), even on an approved workspace.
    _approved_ws(tmp_path, pid="p")
    calls = []

    class _NoCap:                                              # missing executes_client_code
        is_acceptance_fixture = False
        executor_id = "nocap"

        def execute(self, ctx):
            calls.append("x")
            return ExecutionOutcome()

    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    try:
        svc.execute("p", _NoCap())
        raise AssertionError("missing capability must fail closed")
    except WorkExecutionError as exc:
        assert "executes_client_code" in str(exc)
    assert calls == []


def test_operator_validator_callback_is_gated_and_not_invoked_when_untrusted(tmp_path):
    # OperatorWorkspaceExecutor with a validator runs arbitrary code -> it is code-running and gated.
    from core.orchestration.operator_executor import OperatorWorkspaceExecutor, ProducedArtifact
    from core.schemas.work_execution import ValidationOutcome
    ws = _approved_ws(tmp_path, pid="p")
    (ws / "fix.py").write_text("x = 1\n", encoding="utf-8")
    called = []

    def _validator(ctx):
        called.append("validate")
        return ValidationOutcome(passed=True, tests_run=1, tests_passed=1)

    ex = OperatorWorkspaceExecutor([ProducedArtifact("fix.py", "fix")], _validator)
    assert ex.executes_client_code is True                    # validator present => code-running
    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    svc.execute("p", ex)                                       # trusted (approved) -> records execution
    revoke_execution_authority(str(ws))                        # revoke -> validate must be refused
    try:
        svc.validate("p", ex)
        raise AssertionError("validate must be refused after revocation")
    except WorkExecutionError:
        pass
    assert called == []                                        # the validator callback never ran


def test_direct_service_validate_refuses_untrusted_client_code(tmp_path):
    from core.orchestration.claude_worker import ClaudeWorkerExecutor, FixtureClaudeWorker
    from core.orchestration.operator_executor import CommandValidationExecutor
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze("x", "np")
    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    svc.approve("np", reviewer="op")
    ws = tmp_path / "np" / "40_ark_work"
    (ws / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    svc.execute("np", ClaudeWorkerExecutor(FixtureClaudeWorker(edits={"calc.py":
                "def add(a, b):\n    return a + b\n"})))       # fixture is exempt -> VERIFYING
    revoke_execution_authority(str(ws))                        # revoke the control-store grant
    val = CommandValidationExecutor([sys.executable, "-c", "pass"])
    try:
        svc.validate("np", val)
        raise AssertionError("validate must refuse client-code execution on an untrusted workspace")
    except WorkExecutionError as exc:
        assert "untrusted" in str(exc).lower() or "grant" in str(exc).lower()


def test_cli_worker_start_refuses_untrusted_and_creates_nothing(tmp_path):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path / "out")).analyze(
        "Fix a defect and add a regression test.", "np")           # analyze does not approve => no grant
    ws = tmp_path / "out" / "np" / "40_ark_work"
    before = {p for p in ws.rglob("*") if p.is_file()}
    proc = subprocess.run([sys.executable, "main.py", "client-work", "--project-id", "np",
                           "worker-start"], cwd=str(_REPO),
                          env=dict(os.environ, OUTPUT_DIR=str(tmp_path / "out")),
                          capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode != 0 and "untrusted" in (proc.stdout + proc.stderr).lower()
    after = {p for p in ws.rglob("*") if p.is_file()}
    assert after == before and not (ws / "WORKER_CANCEL.json").exists()

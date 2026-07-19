"""v3.2 P0-E - client-repo execution trust + private-work-dir preflight + credential-stripped env."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from core.orchestration.client_work import ClientWorkService
from core.orchestration.execution_trust import (
    TRUST_MARKER,
    TRUSTED_ROOTS_ENV,
    assess_execution_trust,
    preflight_work_isolation,
    stripped_subprocess_env,
)
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionService

_REPO = Path(__file__).resolve().parents[1]


def _approved_ws(tmp_path, pid="p", reviewer="op"):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Fix a defect and add a regression test.", pid)
    WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).approve(
        pid, reviewer=reviewer)
    return tmp_path / pid / "40_ark_work"


def test_untrusted_workspace_is_refused_with_exact_action(tmp_path):
    d = assess_execution_trust(str(tmp_path / "ws"))
    assert d.trusted is False and TRUST_MARKER in d.action and TRUSTED_ROOTS_ENV in d.action


def test_empty_or_forged_marker_is_untrusted(tmp_path):
    # A bare/empty/forged marker file (as a client checkout could pre-create) must NOT grant trust.
    ws = tmp_path / "p" / "40_ark_work"
    ws.mkdir(parents=True)
    for body in ("{}", "not json", '{"approved_for_execution": false}',
                 '{"approved_for_execution": true}',                      # no reviewer
                 '{"approved_for_execution": true, "reviewer": "x"}'):     # no canonical APPROVAL/state
        (ws / TRUST_MARKER).write_text(body, encoding="utf-8")
        assert assess_execution_trust(str(ws)).trusted is False, body


def test_genuine_approval_is_trusted(tmp_path):
    ws = _approved_ws(tmp_path)
    assert (ws / TRUST_MARKER).is_file()
    assert assess_execution_trust(str(ws)).trusted is True


def test_forged_marker_without_matching_canonical_approval_is_untrusted(tmp_path):
    # Genuine approval by "op", but a forged marker claims a different reviewer -> inconsistent -> deny.
    ws = _approved_ws(tmp_path, reviewer="op")
    (ws / TRUST_MARKER).write_text(
        '{"approved_for_execution": true, "reviewer": "attacker", "project_id": "p"}', encoding="utf-8")
    assert assess_execution_trust(str(ws)).trusted is False


def test_marker_project_mismatch_is_untrusted(tmp_path):
    ws = _approved_ws(tmp_path, pid="p")
    import json as _j
    m = _j.loads((ws / TRUST_MARKER).read_text(encoding="utf-8"))
    m["project_id"] = "other"                                  # workspace binding broken
    (ws / TRUST_MARKER).write_text(_j.dumps(m), encoding="utf-8")
    assert assess_execution_trust(str(ws)).trusted is False


def test_trusted_root_env_makes_workspace_trusted(tmp_path):
    ws = tmp_path / "root" / "proj"
    ws.mkdir(parents=True)
    d = assess_execution_trust(str(ws), env={TRUSTED_ROOTS_ENV: str(tmp_path / "root")})
    assert d.trusted is True


def test_preflight_passes_outside_a_repo(tmp_path):
    assert preflight_work_isolation(str(tmp_path / "ws")).ok is True


def test_preflight_fails_closed_for_a_tracked_public_path():
    # A path tracked by THIS public repo (not git-ignored) must be refused, fail closed.
    res = preflight_work_isolation(str(_REPO / "core" / "orchestration"))
    assert res.ok is False and "private" in res.action.lower()


def test_preflight_passes_for_gitignored_output_workspace():
    # A real workspace under outputs/ (outputs/* is git-ignored) is a private work directory.
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


def test_direct_service_validate_refuses_untrusted_client_code(tmp_path):
    # Enforcement is at the EXECUTION BOUNDARY: a direct service call with a client-code executor is
    # refused on an untrusted workspace, even bypassing the CLI/Dashboard.
    import sys as _sys

    from core.orchestration.claude_worker import ClaudeWorkerExecutor, FixtureClaudeWorker
    from core.orchestration.operator_executor import CommandValidationExecutor
    from core.orchestration.work_execution import WorkExecutionError
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Fix a defect.", "np")
    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    svc.approve("np", reviewer="op")
    ws = tmp_path / "np" / "40_ark_work"
    (ws / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    # A deterministic fixture worker (executes_client_code=False) is exempt and advances to VERIFYING.
    svc.execute("np", ClaudeWorkerExecutor(FixtureClaudeWorker(edits={"calc.py":
                "def add(a, b):\n    return a + b\n"})))
    # Now forge the workspace as untrusted by removing the validated marker.
    (ws / TRUST_MARKER).unlink()
    val = CommandValidationExecutor([_sys.executable, "-c", "pass"])   # executes_client_code=True
    try:
        svc.validate("np", val)
        assert False, "validate must refuse client-code execution on an untrusted workspace"
    except WorkExecutionError as exc:
        assert "untrusted" in str(exc).lower()


def test_cli_worker_start_refuses_untrusted_and_creates_nothing(tmp_path):
    # A project that exists but is NOT approved (no trust marker) is refused; nothing new is written.
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path / "out")).analyze(
        "Fix a defect and add a regression test.", "np")
    ws = tmp_path / "out" / "np" / "40_ark_work"
    (ws / TRUST_MARKER).unlink(missing_ok=True)   # ensure not trusted (analyze does not approve)
    before = {p for p in ws.rglob("*") if p.is_file()}
    proc = subprocess.run([sys.executable, "main.py", "client-work", "--project-id", "np",
                           "worker-start"], cwd=str(_REPO),
                          env=dict(os.environ, OUTPUT_DIR=str(tmp_path / "out")),
                          capture_output=True, text=True, timeout=60, check=False)
    assert proc.returncode != 0 and "untrusted" in (proc.stdout + proc.stderr).lower()
    after = {p for p in ws.rglob("*") if p.is_file()}
    assert after == before and not (ws / "WORKER_CANCEL.json").exists()
    _ = json  # keep import used across variants

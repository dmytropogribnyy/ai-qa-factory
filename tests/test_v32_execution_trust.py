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


def test_untrusted_workspace_is_refused_with_exact_action(tmp_path):
    d = assess_execution_trust(str(tmp_path / "ws"))
    assert d.trusted is False and TRUST_MARKER in d.action and TRUSTED_ROOTS_ENV in d.action


def test_marker_makes_workspace_trusted(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / TRUST_MARKER).write_text("{}", encoding="utf-8")
    assert assess_execution_trust(str(ws)).trusted is True


def test_trusted_root_env_makes_workspace_trusted(tmp_path):
    ws = tmp_path / "root" / "proj"
    ws.mkdir(parents=True)
    d = assess_execution_trust(str(ws), env={TRUSTED_ROOTS_ENV: str(tmp_path / "root")})
    assert d.trusted is True


def test_approve_writes_the_trust_marker(tmp_path):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Fix a defect and add a regression test.", "p")
    WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).approve(
        "p", reviewer="op")
    assert (tmp_path / "p" / "40_ark_work" / TRUST_MARKER).is_file()
    assert assess_execution_trust(str(tmp_path / "p" / "40_ark_work")).trusted is True


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

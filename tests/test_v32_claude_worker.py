"""v3.2 Sections 9-10 - bounded Claude Code worker: real flags, controllable Popen, gated live."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from core.orchestration.claude_worker import (
    ClaudeCodeWorker,
    FixtureClaudeWorker,
    WorkOrder,
    build_worker_command,
)

_ORDER = WorkOrder(project_id="p", objective="Fix add() in calc.py to return a+b.",
                   acceptance="pytest passes", allowed_tools=["Edit", "Read"], max_budget_usd=0.25,
                   session_id="sess-abc")


def test_command_uses_only_real_flags_and_never_skips_permissions():
    cmd = build_worker_command(_ORDER)
    assert cmd[0] == "claude" and "-p" in cmd and "--output-format" in cmd
    assert "--permission-mode" in cmd and "acceptEdits" in cmd
    assert "--allowedTools" in cmd
    assert "--max-budget-usd" in cmd and "0.25" in cmd      # the REAL budget flag
    assert "--session-id" in cmd and "sess-abc" in cmd
    assert "--max-turns" not in cmd                          # invented flag removed
    assert "--dangerously-skip-permissions" not in cmd
    assert "--allow-dangerously-skip-permissions" not in cmd


def test_resume_uses_resume_flag():
    cmd = build_worker_command(_ORDER, resume_session="sess-abc")
    assert "--resume" in cmd and "sess-abc" in cmd


class _FakePopen:
    """A controllable fake process: writes an edit, optionally sleeps, then returns a JSON result."""

    def __init__(self, argv, *, cwd=None, sleep=0.0, rc=0, edit=None, out=None, **kw):
        self._sleep = sleep
        self.returncode = None
        self._rc = rc
        self.pid = 424242
        self._killed = False
        if edit and cwd:
            Path(cwd, edit[0]).write_text(edit[1], encoding="utf-8")
        self._out = out if out is not None else (
            '{"session_id":"sess-run","usage":{"output_tokens":12},"total_cost_usd":0.002}')

    def communicate(self, timeout=None):
        end = time.time() + self._sleep
        while time.time() < end and not self._killed:
            time.sleep(0.05)
        self.returncode = 143 if self._killed else self._rc
        return (self._out if not self._killed else ""), ""

    def poll(self):
        return self.returncode

    def kill(self):
        self._killed = True
        self.returncode = 143

    def terminate(self):
        self.kill()


def _worker(popen_factory, version="2.1.198 (Claude Code)"):
    def _run(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 0, stdout=version, stderr="")
    return ClaudeCodeWorker(which=lambda n: "/usr/bin/claude", run=_run, popen=popen_factory)


def test_worker_run_success_records_real_change(tmp_path):
    ws = tmp_path / "ws"

    def _popen(argv, **kw):
        return _FakePopen(argv, edit=("calc.py", "def add(a, b):\n    return a + b\n"), **kw)

    res = _worker(_popen).run(_ORDER, str(ws))
    assert res.ok and res.session_id == "sess-run" and res.tokens == 12 and res.cost_usd == 0.002
    assert "calc.py" in res.files_changed and res.stop_reason == "completed"
    assert (ws / "EXECUTION_SESSION.json").exists()
    assert (ws / "evidence" / "worker" / "stdout.txt").exists()


def test_worker_hard_timeout_kills_tree(tmp_path):
    ws = tmp_path / "ws"

    def _popen(argv, **kw):
        return _FakePopen(argv, sleep=30, **kw)   # would run far past the timeout

    order = WorkOrder(project_id="p", objective="x", timeout_s=1)
    t0 = time.time()
    res = _worker(_popen).run(order, str(ws))
    assert time.time() - t0 < 12                  # the hard timeout fired
    assert res.ok is False and "timeout" in res.stop_reason


def test_worker_genuine_cancellation(tmp_path):
    ws = tmp_path / "ws"
    cancel = threading.Event()

    def _popen(argv, **kw):
        return _FakePopen(argv, sleep=30, **kw)

    threading.Timer(0.5, cancel.set).start()
    order = WorkOrder(project_id="p", objective="x", timeout_s=30)
    res = _worker(_popen).run(order, str(ws), cancel=cancel)
    assert res.ok is False and "cancelled" in res.stop_reason


def test_worker_reports_needs_operator_when_cli_missing(tmp_path):
    res = ClaudeCodeWorker(which=lambda n: None).run(_ORDER, str(tmp_path / "ws"))
    assert res.ok is False and "unavailable" in res.stop_reason and res.blockers


def test_worker_fails_honestly_when_provider_returns_prose_not_json(tmp_path):
    # An un-granted permission prompt returns prose, not a JSON result: NEVER a false green.
    def _popen(argv, **kw):
        return _FakePopen(argv, out="I need approval to edit calc.py. Please approve the write.", **kw)

    res = _worker(_popen).run(_ORDER, str(tmp_path / "ws"))
    assert res.ok is False and "no valid JSON result" in res.stop_reason and res.blockers


def test_worker_fails_on_error_result(tmp_path):
    err = ('{"type":"result","subtype":"error_max_budget_usd","is_error":true,'
           '"session_id":"s","errors":["Reached maximum budget ($0.3)"]}')

    def _popen(argv, **kw):
        return _FakePopen(argv, out=err, **kw)

    res = _worker(_popen).run(_ORDER, str(tmp_path / "ws"))
    assert res.ok is False and "budget" in res.stop_reason.lower() and res.blockers


def test_worker_ignores_scaffold_dirs_in_files_changed(tmp_path):
    # The operator's global memory hook can write .remember/ into the cwd; it is never a deliverable.
    def _popen(argv, **kw):
        p = _FakePopen(argv, **kw)
        scaffold = Path(kw["cwd"]) / ".remember"
        scaffold.mkdir(parents=True, exist_ok=True)
        (scaffold / "log.txt").write_text("noise", encoding="utf-8")
        return p

    res = _worker(_popen).run(_ORDER, str(tmp_path / "ws"))
    assert not any(".remember" in f for f in res.files_changed)


def test_fixture_worker_is_labeled_and_not_live(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "calc.py").write_text("def add(a,b):\n    return a-b\n", encoding="utf-8")
    worker = FixtureClaudeWorker(edits={"calc.py": "def add(a, b):\n    return a + b\n"})
    assert worker.is_acceptance_fixture is True and worker.executor_id == "worker:fixture"
    res = worker.run(_ORDER, str(ws))
    assert res.ok and res.version == "fixture" and "calc.py" in res.files_changed
    session = __import__("json").loads((ws / "EXECUTION_SESSION.json").read_text(encoding="utf-8"))
    assert session["executor"] == "worker:fixture"   # never mistaken for the live provider


_LIVE = os.environ.get("AIQA_CLAUDE_LIVE") == "1" and shutil.which("claude") is not None


@pytest.mark.skipif(not _LIVE, reason="live Claude run is operator-gated (set AIQA_CLAUDE_LIVE=1 "
                                      "in a clean, NON-NESTED shell — inside a parent Claude Code "
                                      "session the operator's hooks force an interactive permission "
                                      "prompt and acceptEdits does not apply)")
def test_live_claude_worker_repairs_a_fixture(tmp_path):
    # Model/budget are operator-configurable so the run stays cheap: a one-line fix on haiku costs
    # ~$0.06. Opus needs a larger budget because first-turn cache creation alone exceeds $0.30.
    model = os.environ.get("AIQA_CLAUDE_MODEL", "claude-haiku-4-5-20251001")
    budget = float(os.environ.get("AIQA_CLAUDE_BUDGET", "0.60"))
    ws = tmp_path / "live"
    ws.mkdir()
    (ws / "calc.py").write_text("def add(a, b):\n    return a - b  # bug\n", encoding="utf-8")
    (ws / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    before = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_calc.py"], cwd=str(ws),
                            capture_output=True, text=True, timeout=120, check=False)
    assert before.returncode != 0, "the fixture must genuinely fail before the repair"
    order = WorkOrder(project_id="live", objective=(
        "The test in test_calc.py fails because add() in calc.py subtracts. Fix calc.py so add "
        "returns a+b. Edit only calc.py."), acceptance="pytest -q passes",
        allowed_tools=["Edit", "Read"], model=model, max_budget_usd=budget, timeout_s=240)
    res = ClaudeCodeWorker().run(order, str(ws))
    assert res.ok, res.stop_reason
    assert "calc.py" in res.files_changed and res.session_id
    after = subprocess.run([sys.executable, "-m", "pytest", "-q", "test_calc.py"], cwd=str(ws),
                           capture_output=True, text=True, timeout=120, check=False)
    assert after.returncode == 0, after.stdout + after.stderr
    # The session + evidence are persisted, and a fresh worker resumes from the persisted session id.
    assert (ws / "EXECUTION_SESSION.json").exists()
    assert (ws / "evidence" / "worker" / "stdout.txt").exists()
    prior = ClaudeCodeWorker._read_session_static(ws)
    resumed = ClaudeCodeWorker().run(order, str(ws),
                                     resume_session=str(prior.get("session_id") or ""))
    assert resumed.ok, resumed.stop_reason

"""v3.2 Sections 9-10 - bounded Claude Code worker: safe command, fixture + injected run, gated live."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from core.orchestration.claude_worker import (
    ClaudeCodeWorker,
    FixtureClaudeWorker,
    WorkOrder,
    build_worker_command,
)

_ORDER = WorkOrder(project_id="p", objective="Fix add() in calc.py to return a+b.",
                   acceptance="pytest passes", allowed_tools=["Edit", "Read"], max_turns=3)


def test_command_is_bounded_and_never_skips_permissions():
    cmd = build_worker_command(_ORDER)
    assert cmd[0] == "claude" and "-p" in cmd and "--output-format" in cmd
    assert "--permission-mode" in cmd and "acceptEdits" in cmd
    assert "--max-turns" in cmd and "--allowedTools" in cmd
    assert "--dangerously-skip-permissions" not in cmd
    assert "--allow-dangerously-skip-permissions" not in cmd


def test_fixture_worker_applies_edits_and_writes_atomic_session(tmp_path):
    ws = tmp_path / "ws"
    (ws).mkdir()
    (ws / "calc.py").write_text("def add(a,b):\n    return a-b\n", encoding="utf-8")
    worker = FixtureClaudeWorker(edits={"calc.py": "def add(a, b):\n    return a + b\n"})
    assert worker.is_acceptance_fixture is True
    res = worker.run(_ORDER, str(ws))
    assert res.ok and res.returncode == 0 and res.stop_reason == "completed"
    assert "calc.py" in res.files_changed
    session = json.loads((ws / "EXECUTION_SESSION.json").read_text(encoding="utf-8"))
    assert session["executor"] == "worker:fixture" and session["work_order_digest"].startswith("sha256:")
    assert session["authorized_tools"] == ["Edit", "Read"]
    assert (ws / "calc.py").read_text(encoding="utf-8").strip().endswith("return a + b")


def test_worker_detect_and_run_with_injected_subprocess(tmp_path):
    ws = tmp_path / "ws"
    calls = {}

    def fake_run(cmd, **kw):
        if "--version" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="2.1.198 (Claude Code)", stderr="")
        # Simulate the worker editing a file in the confined cwd + returning a JSON result.
        Path(kw["cwd"], "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
        calls["cmd"] = cmd
        out = json.dumps({"session_id": "sess-123", "usage": {"output_tokens": 42},
                          "total_cost_usd": 0.001})
        return subprocess.CompletedProcess(cmd, 0, stdout=out, stderr="")

    worker = ClaudeCodeWorker(which=lambda n: "/usr/bin/claude", run=fake_run)
    assert worker.detect() == {"available": True, "version": "2.1.198 (Claude Code)"}
    res = worker.run(_ORDER, str(ws))
    assert res.ok and res.session_id == "sess-123" and res.tokens == 42 and res.cost_usd == 0.001
    assert "calc.py" in res.files_changed
    assert "--permission-mode" in calls["cmd"] and "--dangerously-skip-permissions" not in calls["cmd"]
    # Evidence is written + redacted (no crash on redaction).
    assert (ws / "evidence" / "worker" / "stdout.txt").exists()


def test_worker_reports_needs_operator_when_cli_missing(tmp_path):
    worker = ClaudeCodeWorker(which=lambda n: None)
    res = worker.run(_ORDER, str(tmp_path / "ws"))
    assert res.ok is False and "unavailable" in res.stop_reason and res.blockers


_LIVE = os.environ.get("AIQA_CLAUDE_LIVE") == "1" and shutil.which("claude") is not None


@pytest.mark.skipif(not _LIVE, reason="live Claude run is operator-gated (set AIQA_CLAUDE_LIVE=1)")
def test_live_claude_worker_repairs_a_fixture(tmp_path):
    # Genuine bounded live provider execution (labeled). Repairs a real defect, then pytest verifies.
    ws = tmp_path / "live"
    ws.mkdir()
    (ws / "calc.py").write_text("def add(a, b):\n    return a - b  # bug\n", encoding="utf-8")
    (ws / "test_calc.py").write_text(
        "from calc import add\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    order = WorkOrder(project_id="live", objective="Fix the add() function in calc.py so add(2,3)==5.",
                      acceptance="pytest -q passes", allowed_tools=["Edit", "Read"], max_turns=4,
                      timeout_s=180)
    res = ClaudeCodeWorker().run(order, str(ws))
    assert res.ok, res.stop_reason
    after = subprocess.run([os.sys.executable, "-m", "pytest", "-q", "test_calc.py"],
                           cwd=str(ws), capture_output=True, text=True, timeout=120, check=False)
    assert after.returncode == 0, after.stdout + after.stderr

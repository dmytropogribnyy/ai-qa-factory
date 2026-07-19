"""v3.2 P0-A - canonical start-here docs must reflect the IMPLEMENTED product and cannot drift back
to "planning-only / no executor / v5.0.8". These assertions lock the critical status statements."""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_claude_md_reflects_implemented_client_work_execution():
    t = _read("CLAUDE.md")
    # The client-work lifecycle + bounded Claude worker are IMPLEMENTED (not planning-only).
    assert "IMPLEMENTED" in t and "ClaudeWorkerExecutor" in t and "v3.2" in t
    # It must NOT claim the client-work execution surface has no executor / is planning-only overall.
    low = t.lower()
    assert "no executor" not in low
    # "planning-only" may appear ONLY scoped to the ARK `main.py work` command.
    for line in t.splitlines():
        if "planning-only" in line.lower():
            assert "work" in line.lower() and ("ark" in line.lower() or "main.py work" in line.lower())


def test_work_execution_model_is_implemented_not_planned():
    t = _read("docs/WORK_EXECUTION_MODEL.md")
    assert "IMPLEMENTED" in t
    assert "No executor and no MCP calls exist yet" not in t


def test_env_example_is_v32_and_honest():
    t = _read(".env.example")
    assert "v5.0.8" not in t and "v3.2" in t
    # Gmail is honestly the approval-gated SEND provider; the template explicitly clarifies it is
    # NOT a read-only inbox (rather than silently claiming read-only capability).
    assert "gmail.send" in t and "not a read-only inbox" in t.lower()
    # The worker override is documented and warns against wrappers.
    assert "AIQA_CLAUDE_BIN" in t and ".cmd" in t.lower()

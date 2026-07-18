"""v3.0.0 Milestone 6 - operator scripts + guides exist and are portable (deterministic)."""
from __future__ import annotations

import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SCRIPTS = ["setup-local.ps1", "start-local.ps1", "stop-local.ps1", "doctor-local.ps1"]
_GUIDES = ["QUICKSTART_OPERATOR.md", "CLIENT_WORK_OPERATOR_GUIDE.md", "SCOUT_OPERATOR_GUIDE.md",
           "TOOL_READINESS_GUIDE.md", "TROUBLESHOOTING_OPERATOR.md"]
_MACHINE_PATH = re.compile(r"[A-Za-z]:\\+1QA")


def test_operator_scripts_exist_and_are_portable():
    for name in _SCRIPTS:
        p = _REPO / "scripts" / name
        assert p.exists(), name
        text = p.read_text(encoding="utf-8")
        assert not _MACHINE_PATH.search(text), f"{name} hardcodes a machine path"
    # Repo-relative scripts locate the root via $PSScriptRoot (stop-local is port-based only).
    for name in ("setup-local.ps1", "start-local.ps1", "doctor-local.ps1"):
        assert "$PSScriptRoot" in (_REPO / "scripts" / name).read_text(encoding="utf-8"), name


def test_operator_scripts_are_hardened():
    for name in _SCRIPTS:
        text = (_REPO / "scripts" / name).read_text(encoding="utf-8")
        assert "Set-StrictMode" in text, name           # strict mode catches typos/undefined vars
    for name in ("start-local.ps1", "stop-local.ps1"):
        text = (_REPO / "scripts" / name).read_text(encoding="utf-8")
        assert "ValidateRange(1, 65535)" in text, name  # the port argument is range-validated


def test_stop_local_is_ownership_safe_not_name_and_port():
    # v3.0.2 M7: stop-local must prove ownership via the record (PID + start time + command
    # identity + port) and must NOT kill a process by name + port alone.
    text = (_REPO / "scripts" / "stop-local.ps1").read_text(encoding="utf-8")
    assert "ownership-$Port.json" in text                    # reads the ownership record
    assert "StartTime" in text                               # validates process start time
    assert "command_marker" in text and "CommandLine" in text  # validates command identity
    assert "Get-NetTCPConnection" in text                    # ties the record to the real listener
    assert 'ProcessName -like "python' not in text           # never kills by process name
    assert "Refusing" in text                                # refuses when ownership is unproven


def test_setup_does_not_install_optional_gmail_or_start_scans():
    setup = (_REPO / "scripts" / "setup-local.ps1").read_text(encoding="utf-8")
    assert "requirements-gmail" not in setup            # optional Gmail deps are not installed
    start = (_REPO / "scripts" / "start-local.ps1").read_text(encoding="utf-8")
    assert "--seeds" not in start                       # start does not auto-launch a scan


def test_operator_guides_exist():
    for name in _GUIDES:
        assert (_REPO / "docs" / name).exists(), name

"""v3.0.2 M7 - Windows dashboard ownership-safety (hosted windows-smoke acceptance).

Starts the REAL local dashboard, verifies /health, stops it with the OWNED stop-local script and
verifies it stopped; then starts an UNRELATED Python listener and proves stop-local refuses to kill
it (no ownership record -> never killed by port/name alone). Windows-only; honestly skipped elsewhere.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    os.name != "nt", reason="dashboard stop ownership-safety is a Windows operator-script feature")

_REPO = Path(__file__).resolve().parents[1]


def _free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _health_ok(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _wait(pred, timeout=20.0, interval=0.3) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return True
        time.sleep(interval)
    return False


def _stop_local(port: int, output_dir: Path):
    return subprocess.run(  # noqa: S603
        ["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
         "-File", str(_REPO / "scripts" / "stop-local.ps1"),
         "-Port", str(port), "-OutputDir", str(output_dir)],
        cwd=str(_REPO), capture_output=True, text=True, timeout=60, check=False)


def _terminate(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_owned_dashboard_starts_stops_and_unrelated_python_is_refused(tmp_path):
    out = tmp_path / "outputs"
    port = _free_port()
    record = out / "scout" / "_dashboard" / f"ownership-{port}.json"

    dash = subprocess.Popen(  # noqa: S603
        [sys.executable, "main.py", "scout", "dashboard", "--port", str(port), "--output", str(out)],
        cwd=str(_REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    unrelated = None
    try:
        assert _wait(lambda: _health_ok(port)), "dashboard did not become healthy"
        # The dashboard wrote an ownership record identifying itself.
        assert _wait(record.exists), "ownership record was not written"
        rec = json.loads(record.read_text(encoding="utf-8"))
        # The record's PID is the ACTUAL serving process (which may differ from the venv python.exe
        # shim we launched) - the self-written record correctly identifies the port owner.
        assert isinstance(rec["pid"], int) and rec["pid"] > 0 and rec["port"] == port
        assert rec["command_marker"] == "main.py scout dashboard"

        # Stop the OWNED dashboard: ownership is proven, so it stops and the record is removed.
        res = _stop_local(port, out)
        assert res.returncode == 0, res.stderr
        assert _wait(lambda: not _health_ok(port)), "owned dashboard did not stop"
        assert _wait(lambda: dash.poll() is not None), "dashboard process still alive"
        assert not record.exists(), "ownership record was not removed"

        # An UNRELATED Python process on another port has NO ownership record.
        uport = _free_port()
        unrelated = subprocess.Popen(  # noqa: S603
            [sys.executable, "-m", "http.server", str(uport), "--bind", "127.0.0.1"],
            cwd=str(tmp_path), stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        assert _wait(lambda: _port_listening(uport)), "unrelated listener did not start"

        # stop-local must REFUSE (no ownership record) and must NOT kill it by port/name.
        res2 = _stop_local(uport, out)
        assert res2.returncode == 0
        assert "Refusing to stop by port/name alone" in (res2.stdout + res2.stderr)
        time.sleep(0.5)
        assert unrelated.poll() is None, "unrelated Python process was killed"
        assert _port_listening(uport), "unrelated listener was stopped"
    finally:
        _terminate(unrelated)
        _terminate(dash)


def _port_listening(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(1.0)
    try:
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()

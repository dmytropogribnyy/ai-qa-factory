"""v3.2 review-fix (item 1) - the worker CLI validates the project id BEFORE any filesystem op.

Every worker action (worker-start / worker-resume / worker-cancel / worker-status) must reject an
unsafe or nonexistent project id without creating a workspace, a WORKER_CANCEL.json marker, or any
other file anywhere - inside OR outside OUTPUT_DIR. Driven through the real CLI (subprocess).
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]

# Unsafe ids that MUST be rejected before any path construction, plus a well-formed-but-nonexistent
# id (rejected because the project does not exist).
_UNSAFE = [
    "../escape",            # parent traversal
    "../../escape",         # deeper traversal
    "/abs/evil",            # POSIX absolute
    "C:\\evil",             # Windows drive path (has : and \)
    "a/b",                  # forward slash separator
    "a\\b",                 # backslash separator
    "CON",                  # Windows reserved device name
    "LPT1",                 # Windows reserved device name
    "a\x01b",               # control character
    ".",                    # dot
    "..",                   # dot-dot
]
_NONEXISTENT_VALID = "ghost-project-42"        # valid id, but no such project exists


def _run(pid: str, action: str, out_dir: Path):
    env = dict(os.environ, OUTPUT_DIR=str(out_dir))
    return subprocess.run(
        [sys.executable, "main.py", "client-work", "--project-id", pid, action],
        cwd=str(_REPO), env=env, capture_output=True, text=True, timeout=60, check=False)


def _all_files(root: Path):
    return {p for p in root.rglob("*") if p.is_file()}


def _tree_after(tmp_path: Path, pid: str, action: str):
    # OUTPUT_DIR is a child of tmp_path; a traversal escape would land elsewhere under tmp_path.
    out_dir = tmp_path / "out"
    before = _all_files(tmp_path)
    proc = _run(pid, action, out_dir)
    after = _all_files(tmp_path)
    created = after - before
    return proc, created


@pytest.mark.parametrize("action", ["worker-cancel", "worker-start", "worker-resume", "worker-status"])
@pytest.mark.parametrize("pid", _UNSAFE)
def test_unsafe_project_id_is_rejected_and_creates_nothing(tmp_path, pid, action):
    proc, created = _tree_after(tmp_path, pid, action)
    assert proc.returncode != 0, (pid, action, proc.stdout, proc.stderr)
    # NOTHING is created anywhere under the temp root for a rejected request.
    assert created == set(), (pid, action, sorted(str(c) for c in created))
    # Belt and braces: no cancel marker, no escaped directory, anywhere.
    assert not list(tmp_path.rglob("WORKER_CANCEL.json"))
    assert not (tmp_path / "escape").exists() and not (tmp_path / "evil").exists()


@pytest.mark.parametrize("action", ["worker-cancel", "worker-start", "worker-resume", "worker-status"])
def test_nonexistent_valid_project_creates_nothing(tmp_path, action):
    proc, created = _tree_after(tmp_path, _NONEXISTENT_VALID, action)
    assert proc.returncode != 0, (action, proc.stdout, proc.stderr)
    # get_settings() may create the (empty) OUTPUT_DIR itself, but no project workspace/marker/file.
    assert not list(tmp_path.rglob("WORKER_CANCEL.json"))
    assert not (tmp_path / "out" / _NONEXISTENT_VALID).exists()
    assert not [c for c in created if c.name != ".gitkeep"]


def test_valid_existing_project_cancel_writes_only_the_marker(tmp_path):
    # A genuinely-existing project CAN be cancelled, and the marker lands INSIDE its confined
    # workspace (never elsewhere).
    from core.orchestration.client_work import ClientWorkService
    from core.orchestration.providers import FixedClock, SequentialIds
    out_dir = tmp_path / "out"
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(out_dir)).analyze(
        "Reproduce and fix a defect in a small Python module and add a regression test.", "realproj")
    proc = _run("realproj", "worker-cancel", out_dir)
    assert proc.returncode == 0, proc.stderr
    marker = out_dir / "realproj" / "40_ark_work" / "WORKER_CANCEL.json"
    assert marker.is_file()
    # The only cancel marker anywhere is the confined one.
    assert [str(p) for p in tmp_path.rglob("WORKER_CANCEL.json")] == [str(marker)]

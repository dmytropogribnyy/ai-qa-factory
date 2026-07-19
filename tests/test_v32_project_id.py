"""v3.2 Section 5.1 - the one public project-id contract is safe on every OS."""
from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath

import pytest

from core.orchestration.providers import IdProvider, generate_project_id, validate_project_id

_VALID = ["p", "alpha", "my-project", "a1.b2_c", "job-01", "x" * 64, "fix.py-work", "conference"]
_INVALID = [
    "", "..", ".", "../evil", "a/b", "c\\d", "..\\x", "/abs/path", "C:evil", "d:evil",
    "x" * 65, "bad id", "ctrl\x01char", "trail.", ".lead", "trail ", " lead",
    # Windows reserved device names (case-insensitive, with/without extension/space/dot):
    "CON", "con", "Con", "PRN", "AUX", "NUL", "CLOCK$", "COM1", "com9", "LPT1", "lpt9",
    "NUL.txt", "con.log", "AUX.tar.gz",
]


@pytest.mark.parametrize("pid", _VALID)
def test_valid_ids_accepted(pid):
    assert validate_project_id(pid) is True


@pytest.mark.parametrize("pid", _INVALID)
def test_invalid_ids_rejected(pid):
    assert validate_project_id(pid) is False


def test_no_accepted_id_escapes_the_output_root_cross_platform():
    root_posix = PurePosixPath("/srv/outputs")
    root_win = PureWindowsPath(r"C:\outputs")
    candidates = _VALID + ["a.b", "a-b-c", "z_9"]
    for pid in candidates:
        if not validate_project_id(pid):
            continue
        # The joined path must remain a direct child of the root on BOTH path flavors.
        p = root_posix / pid
        assert p.parent == root_posix and ".." not in p.parts
        w = root_win / pid
        assert w.parent == root_win and ".." not in w.parts


def test_generated_ids_are_always_valid_and_safe():
    ids = IdProvider()
    for seed in ("", "con", "nul", "Build a Playwright framework", "aux prn com1 lpt1", "x" * 500):
        pid = generate_project_id(seed, ids)
        assert validate_project_id(pid), pid

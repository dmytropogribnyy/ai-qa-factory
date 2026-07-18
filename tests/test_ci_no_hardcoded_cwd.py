"""Regression guard for GitHub Actions run 29614052117 (core-deterministic).

The v2.0.0 core CI job failed on Linux because a test launched a subprocess with
``cwd="d:\\1QA AI\\ai-qa-factory"`` -- a machine-specific absolute path that does
not exist off the author's Windows box, so ``chdir(cwd)`` raised
``FileNotFoundError`` for every ``TestCLIBlockedFlags`` case.

This test fails if any committed Python file hardcodes a *machine-specific*
absolute working directory (a Windows drive path like ``X:\\...`` or a personal
home path like ``/home/<user>/...`` / ``/Users/<user>/...``) as a ``cwd=``
argument. Portable, machine-independent cwd values (``str(_REPO_ROOT)``,
``tmp_path``, ``/tmp``, ``/scaffold`` fixtures) never match.
"""
from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SELF = Path(__file__).resolve()
_SKIP_DIRS = {".venv", "venv", "site-packages", "node_modules", ".git", "outputs", "build", "dist"}

# A ``cwd=`` keyword argument bound to a single- or double-quoted string literal.
_CWD_LITERAL = re.compile(r"""cwd\s*=\s*(['"])(?P<path>.*?)\1""")
# A machine-specific absolute path: Windows drive root, or a personal home dir.
_MACHINE_ABSOLUTE = re.compile(r"^([A-Za-z]:[\\/]|/home/[^/]|/Users/[^/])")


def _python_files() -> list[Path]:
    files = []
    for py in _REPO_ROOT.rglob("*.py"):
        if _SKIP_DIRS & set(py.parts):
            continue
        if py.resolve() == _SELF:
            continue
        files.append(py)
    return files


def test_no_hardcoded_machine_specific_cwd() -> None:
    offenders = []
    for py in _python_files():
        text = py.read_text(encoding="utf-8", errors="ignore")
        for match in _CWD_LITERAL.finditer(text):
            value = match.group("path")
            if _MACHINE_ABSOLUTE.match(value):
                line = text.count("\n", 0, match.start()) + 1
                offenders.append(f"{py.relative_to(_REPO_ROOT).as_posix()}:{line}: cwd={value!r}")
    assert not offenders, (
        "hardcoded machine-specific cwd found (breaks CI on other machines / OSes):\n"
        + "\n".join(offenders)
    )

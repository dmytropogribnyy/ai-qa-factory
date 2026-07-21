#!/usr/bin/env python
"""Fast, targeted test runner for AI QA Factory — run only what a change actually affects.

Modes:
  python tools/test.py                 # 'affected' (default): only tests impacted by your changes
  python tools/test.py affected [base] # tests affected vs base (default: origin/main, then HEAD~1)
  python tools/test.py scout           # the v3.3 Scout regression subset (tests/test_v33_*.py)
  python tools/test.py full            # the entire suite
  python tools/test.py testmon         # coverage-accurate 'only affected' (needs: pip install pytest-testmon)

Any extra args after the mode are forwarded to pytest, e.g.:
  python tools/test.py affected -x -q
  python tools/test.py scout -k verticals

'affected' is import-graph based (dependency-free): it runs every changed test file plus every
test file that imports a changed module. It is exact for direct imports; before merging to main,
run 'full' (or let CI do it) so cross-module / platform regressions are still caught.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PY = sys.executable
TESTS = REPO / "tests"


def _run(args: list[str]) -> int:
    print(f"[test] pytest {' '.join(args)}")
    return subprocess.call([PY, "-m", "pytest", *args], cwd=str(REPO))


def _git(*a: str) -> list[str]:
    try:
        out = subprocess.check_output(["git", *a], cwd=str(REPO), text=True,
                                      stderr=subprocess.DEVNULL)
        return [ln.strip() for ln in out.splitlines() if ln.strip()]
    except (subprocess.CalledProcessError, OSError):
        return []


def _changed_py(base: str) -> list[str]:
    """Changed .py = this branch's own changes since it diverged from `base` (merge-base, so being
    behind `base` doesn't over-report) UNION the current working-tree edits."""
    names: set[str] = set()
    mb = _git("merge-base", "HEAD", base)
    diff_from = mb[0] if mb else "HEAD~1"                 # fall back if base is unknown
    names.update(_git("diff", "--name-only", diff_from, "HEAD"))  # committed on this branch
    names.update(_git("diff", "--name-only", "HEAD"))            # unstaged edits
    names.update(_git("diff", "--name-only", "--cached"))        # staged edits
    names.update(_git("ls-files", "--others", "--exclude-standard"))  # new untracked files
    return sorted(n for n in names if n.endswith(".py"))


def _scout_files() -> list[str]:
    return sorted(f"tests/{p.name}" for p in TESTS.glob("test_v33_*.py"))


def _affected_tests(changed: list[str]) -> list[str]:
    tests: set[str] = set()
    modules: list[str] = []
    for f in changed:
        norm = f.replace("\\", "/")
        if norm.startswith("tests/") and (REPO / norm).exists():
            tests.add(norm)                              # a changed test runs directly
        else:
            modules.append(norm[:-3].replace("/", "."))  # e.g. core/scout/verticals.py -> core.scout.verticals
    if modules:
        for tf in TESTS.glob("test_*.py"):
            try:
                text = tf.read_text(encoding="utf-8")
            except OSError:
                continue
            if any(m in text for m in modules):          # imports a changed module
                tests.add(f"tests/{tf.name}")
    return sorted(t for t in tests if (REPO / t).exists())


def main(argv: list[str]) -> int:
    mode = argv[0] if argv else "affected"
    extra = argv[1:]

    if mode == "full":
        return _run(["tests/", "-q", *extra])
    if mode == "scout":
        files = _scout_files()
        return _run([*files, "-q", *extra]) if files else 0
    if mode == "testmon":
        return _run(["tests/", "-q", "--testmon", *extra])
    if mode == "affected":
        base = extra[0] if extra and not extra[0].startswith("-") else "origin/main"
        pytest_extra = extra[1:] if (extra and not extra[0].startswith("-")) else extra
        changed = _changed_py(base)
        if not changed:
            print("[test] no changed .py files vs", base, "— running the Scout regression subset.")
            return _run([*_scout_files(), "-q", *pytest_extra])
        affected = _affected_tests(changed)
        if not affected:
            print("[test] changes don't map to a test file — running the Scout regression subset.")
            return _run([*_scout_files(), "-q", *pytest_extra])
        print(f"[test] {len(changed)} changed file(s) -> {len(affected)} affected test file(s).")
        return _run([*affected, "-q", *pytest_extra])

    # Unknown mode => treat the whole argv as raw pytest args.
    return _run(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

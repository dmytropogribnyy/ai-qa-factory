"""A whitespace gate that can actually fail.

CI ran ``git diff --check``. On a clean checkout that compares the working tree against the index,
both of which are clean, so it inspected nothing and passed every time — a green check that could
not go red. The specification document reached main with 1644 CRLF lines under it.

This checks the change itself. On a pull request it reads the diff from the merge base, so only
lines the branch ADDS are judged: inheriting a decade of trailing spaces is not this branch's
problem, and adding one is. With no base to compare against it falls back to scanning tracked text
files, which is the right behaviour for a local run over a repository someone wants clean.

``--self-check`` proves the detector detects, using a temporary file outside the repository, so the
proof leaves nothing behind that the gate would then have to complain about.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import List, Optional, Tuple

# Binary-ish and generated content the rule does not apply to.
_SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".webm", ".mp4", ".zip",
                  ".pdf", ".xlsx", ".xls", ".woff", ".woff2", ".ttf", ".pyc", ".gz"}
_SKIP_PARTS = {".git", "outputs", "node_modules", "__pycache__", ".venv"}


def _git(*args: str) -> str:
    """Run git and decode its output as UTF-8, never as the console's codepage.

    ``text=True`` decodes with the locale encoding, so a diff containing Cyrillic — this repo's
    specification, for one — raised UnicodeDecodeError inside subprocess and left the gate with
    ``None`` to parse. A whitespace check that crashes is better than one that passes silently, but
    only just.
    """
    result = subprocess.run(["git", *args], capture_output=True, check=False)
    if result.returncode != 0:
        return ""
    return (result.stdout or b"").decode("utf-8", "replace")


def _merge_base(base_ref: str) -> str:
    return _git("merge-base", base_ref, "HEAD").strip()


def _added_lines(base: str) -> List[Tuple[str, int, str]]:
    """Every line this branch ADDS, with the file and line number a reader can go to."""
    diff = _git("diff", "--unified=0", f"{base}...HEAD")
    out: List[Tuple[str, int, str]] = []
    path, line_no = "", 0
    for raw in diff.split("\n"):
        if raw.startswith("+++ b/"):
            path = raw[6:]
        elif raw.startswith("@@"):
            try:
                line_no = int(raw.split("+", 1)[1].split(",", 1)[0].split(" ", 1)[0])
            except (IndexError, ValueError):
                line_no = 0
        elif raw.startswith("+") and not raw.startswith("+++"):
            out.append((path, line_no, raw[1:]))
            line_no += 1
    return out


def _tracked_text_files() -> List[Path]:
    files = []
    for name in _git("ls-files").split("\n"):
        name = name.strip()
        if not name:
            continue
        path = Path(name)
        if path.suffix.lower() in _SKIP_SUFFIXES or set(path.parts) & _SKIP_PARTS:
            continue
        files.append(path)
    return files


def _problems_in(text: str, path: str, *, first_line: int = 1) -> List[str]:
    """Trailing whitespace and stray carriage returns, named where they are."""
    problems = []
    for offset, line in enumerate(text.split("\n")):
        number = first_line + offset
        if line.endswith("\r"):
            problems.append(f"{path}:{number}: carriage return in a line-feed file")
            line = line[:-1]
        if line != line.rstrip():
            problems.append(f"{path}:{number}: trailing whitespace")
    return problems


def check_diff(base_ref: str) -> List[str]:
    base = _merge_base(base_ref)
    if not base:
        return []
    problems = []
    for path, number, line in _added_lines(base):
        if Path(path).suffix.lower() in _SKIP_SUFFIXES:
            continue
        problems.extend(_problems_in(line, path, first_line=number))
    return problems


def check_tree() -> List[str]:
    problems = []
    for path in _tracked_text_files():
        try:
            raw = path.read_bytes()
        except OSError:
            continue
        if b"\x00" in raw[:4096]:
            continue                      # binary content that git happens to track as a file
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        problems.extend(_problems_in(text, str(path).replace("\\", "/")))
    return problems


def self_check() -> int:
    """Prove the detector fails on bad input, outside the repository it is guarding."""
    with tempfile.TemporaryDirectory() as tmp:
        sample = Path(tmp) / "sample.md"
        sample.write_bytes(b"clean line\ntrailing space here \r\nanother\n")
        # Read the BYTES: read_text() would translate the carriage return away, and a self-check
        # that cannot see the thing it is checking for proves nothing.
        found = _problems_in(sample.read_bytes().decode("utf-8"), "sample.md")
    kinds = {p.split(": ", 1)[1] for p in found}
    if kinds != {"trailing whitespace", "carriage return in a line-feed file"}:
        print(f"[whitespace] SELF-CHECK FAILED: detector reported {sorted(kinds)}")
        return 1
    if _problems_in("a clean line\nand another\n", "clean.md"):
        print("[whitespace] SELF-CHECK FAILED: clean input was reported as a problem")
        return 1
    print("[whitespace] self-check OK: bad input is detected, clean input is not")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main",
                        help="branch to diff against; the whole tree is scanned without one")
    parser.add_argument("--tree", action="store_true", help="scan every tracked text file")
    parser.add_argument("--self-check", action="store_true",
                        help="prove the detector works, then exit")
    args = parser.parse_args(argv)

    if args.self_check:
        return self_check()

    if args.tree or not _merge_base(args.base):
        scope = "every tracked text file"
        problems = check_tree()
    else:
        scope = f"lines added since {args.base}"
        problems = check_diff(args.base)

    if problems:
        print(f"[whitespace] FAIL — {len(problems)} problem(s) in {scope}:")
        for problem in problems[:50]:
            print(f"  {problem}")
        if len(problems) > 50:
            print(f"  ... and {len(problems) - 50} more")
        return 1
    print(f"[whitespace] PASS — no trailing whitespace or stray carriage returns in {scope}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Fail if a JUnit report contains any skipped tests (v3.0.2 M5).

The browser-acceptance job must genuinely RUN its real Chromium/axe and `playwright test`
executions - never skip them. This asserts zero skips (and zero collection errors) so a
misprovisioned runtime cannot pass as a green-but-skipped job.

Usage: python tools/assert_no_skips.py <junit.xml> [<junit.xml> ...]
"""
from __future__ import annotations

import sys
from pathlib import Path

try:  # prefer a hardened parser; the JUnit files are self-produced in CI, but be safe by default
    from defusedxml.ElementTree import parse as _xml_parse
except ImportError:
    from xml.etree.ElementTree import parse as _xml_parse  # noqa: S405 - trusted CI-produced input


def _totals(path: Path) -> tuple[int, int, int, int]:
    root = _xml_parse(path).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    tests = skipped = errors = failures = 0
    for s in suites:
        tests += int(s.get("tests", 0))
        skipped += int(s.get("skipped", 0))
        errors += int(s.get("errors", 0))
        failures += int(s.get("failures", 0))
    return tests, skipped, errors, failures


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: assert_no_skips.py <junit.xml> [...]", file=sys.stderr)
        return 2
    bad = False
    for arg in argv:
        p = Path(arg)
        if not p.is_file():
            print(f"[FAIL] JUnit report not found: {p}", file=sys.stderr)
            bad = True
            continue
        tests, skipped, errors, failures = _totals(p)
        if tests == 0:
            print(f"[FAIL] {p}: no tests were collected", file=sys.stderr)
            bad = True
        elif skipped or errors:
            print(f"[FAIL] {p}: tests={tests} skipped={skipped} errors={errors} "
                  f"failures={failures} — zero skips/errors required", file=sys.stderr)
            bad = True
        else:
            print(f"[PASS] {p}: tests={tests} skipped=0 errors=0 failures={failures}")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

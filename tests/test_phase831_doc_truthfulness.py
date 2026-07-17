"""Phase 8.3.1 — guard against stale/brittle documentation claims.

Keeps obviously-drifting canonical test-count claims out of the README's generic quick-start /
run-instruction sections (exact totals belong in the versioned release notes and the current
handoff, which are allowed to name a specific number for a specific release).
"""
from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_README = _ROOT / "README.md"
# A hard-coded suite total like "3351 tests" or "2893 passed" is brittle and drifts.
_STALE = re.compile(r"\b\d{3,}\s+(?:tests?|passed)\b", re.IGNORECASE)
_CHANGELOG_ANCHOR = "## Changelog highlights"


def _readme_text() -> str:
    return _README.read_text(encoding="utf-8")


def test_readme_generic_sections_have_no_hardcoded_test_count():
    text = _readme_text()
    # Version-anchored changelog entries may cite a per-release number; everything before the
    # changelog (quick start, run instructions, docs) must not embed a brittle suite total.
    head = text.split(_CHANGELOG_ANCHOR, 1)[0]
    matches = _STALE.findall(head)
    assert not matches, f"stale hard-coded test counts in README generic sections: {matches}"


def test_known_stale_counts_are_gone():
    text = _readme_text()
    head = text.split(_CHANGELOG_ANCHOR, 1)[0]
    assert "3351 tests" not in head
    assert "2893 passed" not in head


def test_readme_still_documents_the_test_command():
    # Guard that the de-brittling did not delete the quick-start test instruction entirely.
    assert "pytest" in _readme_text()

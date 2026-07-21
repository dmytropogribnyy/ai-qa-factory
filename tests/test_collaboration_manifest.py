"""Direct Collaboration Driver v1 (Issue #14 P0) — trusted CI/test manifest for a CHECKPOINT GO."""
from __future__ import annotations

from core.collaboration.manifest import (
    build_trusted_manifest,
    load_gate_manifest,
    record_gate_manifest,
)

_SHA = "a" * 40


def test_absent_manifest_is_not_present_or_successful(tmp_path):
    m = build_trusted_manifest(str(tmp_path), ".", _SHA)
    assert m["present"] is False
    assert m["success"] is False


def test_recorded_successful_gate_is_present_and_successful(tmp_path):
    record_gate_manifest(str(tmp_path), _SHA, ci_conclusion="success", ci_run="123",
                         tests_passed=5147, tests_total=5152, tests_ok=True, audits_ok=True)
    m = build_trusted_manifest(str(tmp_path), ".", _SHA)
    assert m["present"] is True
    assert m["success"] is True
    assert "CI success" in m["summary"]


def test_failed_ci_gate_is_present_but_not_successful(tmp_path):
    record_gate_manifest(str(tmp_path), _SHA, ci_conclusion="failure", tests_ok=True, audits_ok=True)
    m = build_trusted_manifest(str(tmp_path), ".", _SHA)
    assert m["present"] is True
    assert m["success"] is False


def test_manifest_is_bound_to_the_exact_sha(tmp_path):
    record_gate_manifest(str(tmp_path), _SHA, ci_conclusion="success", tests_ok=True, audits_ok=True)
    assert load_gate_manifest(str(tmp_path), _SHA) is not None
    assert load_gate_manifest(str(tmp_path), "b" * 40) is None      # different SHA -> no manifest

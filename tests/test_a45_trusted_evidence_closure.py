"""A4.5 foundation closure — the trusted gate manifest must not be believable on its own word.

`manifest.py` opens by saying "the autonomous reviewer must not authorize a GO on the worker's
claims". Three paths defeated that, all proven by execution before this file was written:

1. the body's ``head_sha`` was never compared with the SHA being asked about, so renaming a file
   made a manifest for one commit satisfy a CHECKPOINT for another;
2. a file containing nothing but ``{"success": true}`` was accepted as a complete gate record;
3. ``success`` was returned verbatim, so a record could claim success while the evidence beside it
   in the same file said ``ci_conclusion=failure, tests_ok=False, audits_ok=False`` - the returned
   summary and the returned verdict contradicted each other.

The repair is defence at both boundaries the controller named: where the value is WRITTEN
(`record_gate_manifest` no longer takes a ``success`` override) and where it is READ
(`build_trusted_manifest` re-derives the verdict from the evidence and refuses a mismatched or
incomplete record).

What this does NOT claim: the store is not unforgeable. It lives under a gitignored, worker-writable
`outputs/` tree, and a local actor with write access there is the same OS principal as the worker.
Making it unforgeable needs a secret the worker cannot read - an owner/platform action, recorded as
a residual, not a code defect. What these tests pin is that a forged record must now be a
*deliberate, complete and self-consistent* forgery rather than one careless field.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from core.collaboration.manifest import (build_trusted_manifest, load_gate_manifest,
                                         record_gate_manifest)

_SHA = "a" * 40
_OTHER = "b" * 40


def _gate_dir(root) -> pathlib.Path:
    d = pathlib.Path(root) / "_review_relay" / "collab_gate"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _genuine(sha=_SHA, **over):
    from core.collaboration.manifest import SCHEMA
    body = {"schema": SCHEMA, "head_sha": sha, "ci_conclusion": "success", "ci_run": "1",
            "tests_passed": 10, "tests_total": 10, "tests_ok": True, "audits_ok": True,
            "notes": "", "success": True}
    body.update(over)
    return body


# --- the record must describe the SHA it is filed under ------------------------------------------

def test_a_manifest_whose_body_names_another_sha_is_refused(tmp_path):
    """Renaming a file must not re-point its evidence at a different commit."""
    (_gate_dir(tmp_path) / f"{_OTHER}.json").write_text(json.dumps(_genuine(sha=_SHA)),
                                                        encoding="utf-8")
    assert load_gate_manifest(str(tmp_path), _OTHER) is None
    out = build_trusted_manifest(str(tmp_path), ".", _OTHER)
    assert out["present"] is False and out["success"] is False
    assert "sha" in out["summary"].lower()


def test_a_manifest_with_no_body_sha_at_all_is_refused(tmp_path):
    (_gate_dir(tmp_path) / f"{_SHA}.json").write_text(
        json.dumps({k: v for k, v in _genuine().items() if k != "head_sha"}), encoding="utf-8")
    assert build_trusted_manifest(str(tmp_path), ".", _SHA)["success"] is False


# --- the record must carry the evidence it claims to summarise -----------------------------------

def test_a_bare_success_flag_is_not_a_gate_record(tmp_path):
    """`{"success": true}` was accepted. A verdict with no evidence is not evidence."""
    (_gate_dir(tmp_path) / f"{_SHA}.json").write_text(json.dumps({"head_sha": _SHA,
                                                                 "success": True}),
                                                      encoding="utf-8")
    out = build_trusted_manifest(str(tmp_path), ".", _SHA)
    assert out["success"] is False
    assert "incomplete" in out["summary"].lower() or "missing" in out["summary"].lower()


@pytest.mark.parametrize("missing", ["ci_conclusion", "tests_ok", "audits_ok", "tests_passed"])
def test_a_record_missing_any_evidence_field_is_not_successful(tmp_path, missing):
    body = _genuine()
    del body[missing]
    (_gate_dir(tmp_path) / f"{_SHA}.json").write_text(json.dumps(body), encoding="utf-8")
    assert build_trusted_manifest(str(tmp_path), ".", _SHA)["success"] is False


# --- the verdict is re-derived, never believed ---------------------------------------------------

@pytest.mark.parametrize("evidence", [
    {"ci_conclusion": "failure"},
    {"ci_conclusion": ""},
    {"tests_ok": False},
    {"audits_ok": False},
    {"tests_passed": 0},
])
def test_a_success_flag_contradicting_its_own_evidence_is_refused(tmp_path, evidence):
    """The worst of the three: the summary said "CI failure ... ok=False" beside `success: True`."""
    (_gate_dir(tmp_path) / f"{_SHA}.json").write_text(json.dumps(_genuine(success=True, **evidence)),
                                                      encoding="utf-8")
    out = build_trusted_manifest(str(tmp_path), ".", _SHA)
    assert out["success"] is False, f"evidence {evidence} must not yield success"
    assert "contradict" in out["summary"].lower() or "not successful" in out["summary"].lower()


def test_a_genuine_record_still_passes(tmp_path):
    """Control: the repair must not make a real producer-written manifest unusable."""
    record_gate_manifest(str(tmp_path), _SHA, ci_conclusion="success", ci_run="7",
                         tests_passed=6503, tests_total=6508, tests_ok=True, audits_ok=True,
                         notes="ci=success; tree=abc123; tests rc=0")
    out = build_trusted_manifest(str(tmp_path), ".", _SHA)
    assert out["present"] is True and out["success"] is True
    assert "6503/6508" in out["summary"]


def test_a_record_that_is_honestly_unsuccessful_stays_present_but_not_successful(tmp_path):
    """A red gate is still evidence - it must be readable, and it must not be success."""
    record_gate_manifest(str(tmp_path), _SHA, ci_conclusion="", ci_run="",
                         tests_passed=10, tests_total=10, tests_ok=True, audits_ok=True,
                         notes="no machine-readable required-check set")
    out = build_trusted_manifest(str(tmp_path), ".", _SHA)
    assert out["present"] is True and out["success"] is False
    assert "no machine-readable required-check set" in out["gate"]["notes"]


# --- the write boundary no longer takes a verdict -------------------------------------------------

def test_record_gate_manifest_accepts_no_success_override():
    """A caller-supplied verdict is exactly the trust hole the producer exists to close."""
    import inspect
    params = set(inspect.signature(record_gate_manifest).parameters)
    assert "success" not in params, (
        "record_gate_manifest must derive the verdict from the evidence, not accept one")


def test_the_written_verdict_is_derived_from_the_written_evidence(tmp_path):
    written = record_gate_manifest(str(tmp_path), _SHA, ci_conclusion="failure",
                                   tests_passed=10, tests_total=10, tests_ok=True, audits_ok=True)
    assert written["success"] is False
    assert build_trusted_manifest(str(tmp_path), ".", _SHA)["success"] is False


# --- provenance is recorded, and its absence is not fatal ----------------------------------------

def test_a_recorded_manifest_carries_when_and_by_what_it_was_produced(tmp_path):
    """Without this, a hand-written record is indistinguishable from a produced one in the file."""
    written = record_gate_manifest(str(tmp_path), _SHA, ci_conclusion="success", tests_passed=1,
                                   tests_total=1, tests_ok=True, audits_ok=True)
    assert written["recorded_at"], "a gate record with no timestamp cannot be aged out"
    assert written["schema"] == "collab-gate-manifest/v2"
    reloaded = load_gate_manifest(str(tmp_path), _SHA)
    assert reloaded["recorded_at"] == written["recorded_at"]


def test_a_v1_record_without_provenance_is_still_readable_but_not_successful(tmp_path):
    """Records written before v2 carry no provenance; they must not silently keep authorising GO."""
    body = _genuine()
    body.pop("schema", None)
    (_gate_dir(tmp_path) / f"{_SHA}.json").write_text(json.dumps(body), encoding="utf-8")
    out = build_trusted_manifest(str(tmp_path), ".", _SHA)
    assert out["present"] is True
    assert out["success"] is False
    assert "schema" in out["summary"].lower() or "provenance" in out["summary"].lower()

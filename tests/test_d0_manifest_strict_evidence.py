"""D0 — the trusted gate manifest accepts only native, well-typed evidence (Issue #74).

Confirmed by execution on c23e218: the verdict was derived with ``bool(...)`` and a lenient count
parser, so evidence that SAYS no was read as yes. ``tests_ok="false"`` is truthy; ``1.75`` became
``1``; ``passed=11`` of ``total=10`` and ``total=-1`` were never compared. Each of those records
authorised a CHECKPOINT GO at the read boundary, and the writer coerced the same inputs into a
record that did too.

The rule pinned here, at BOTH public boundaries (``record_gate_manifest`` writes,
``build_trusted_manifest`` reads):

- ``tests_ok`` / ``audits_ok`` / stored ``success`` are native JSON booleans or they are not
  approval - never their truthiness;
- ``tests_passed`` / ``tests_total`` are native non-negative JSON integers (``bool`` excluded) with
  ``passed <= total``; zero passed never authorises a GO;
- a malformed record is refused, not raised, and its summary still says what was wrong;
- the writer refuses invalid evidence either by raising ``ValueError`` before any record exists or
  by recording an explicit refused result. Persisting ``success: true`` is never acceptable.
"""
from __future__ import annotations

import json
import pathlib

import pytest

from core.collaboration.manifest import (SCHEMA, build_trusted_manifest, load_gate_manifest,
                                         record_gate_manifest)

_SHA = "a" * 40
_OTHER = "b" * 40

_NOT_BOOLEANS = ["false", "true", "", 0, 1, [], [True], {}, {"ok": True}, None]

_BAD_COUNTS = [
    pytest.param("10", 10, id="passed-str"),
    pytest.param(10, "10", id="total-str"),
    pytest.param("", 10, id="passed-empty-str"),
    pytest.param(None, 10, id="passed-null"),
    pytest.param(10, None, id="total-null"),
    pytest.param(1.75, 10, id="passed-fraction"),
    pytest.param(10, 10.5, id="total-fraction"),
    pytest.param(10.0, 10, id="passed-float"),
    pytest.param(-1, 10, id="passed-negative"),
    pytest.param(10, -1, id="total-negative"),
    pytest.param(float("nan"), 10, id="passed-nan"),
    pytest.param(10, float("nan"), id="total-nan"),
    pytest.param(float("inf"), 10, id="passed-inf"),
    pytest.param(10, float("inf"), id="total-inf"),
    pytest.param(True, 10, id="passed-bool"),
    pytest.param(10, True, id="total-bool"),
    pytest.param([10], 10, id="passed-list"),
    pytest.param(10, {"n": 10}, id="total-object"),
    pytest.param(11, 10, id="passed-exceeds-total"),
]


def _gate_dir(root) -> pathlib.Path:
    return pathlib.Path(root) / "_review_relay" / "collab_gate"


def _write_raw(root, sha=_SHA, **over) -> None:
    """A persisted record as the READ boundary sees it. Python's json.dumps emits the NONSTANDARD
    NaN/Infinity literals (standard JSON forbids them) and json.loads accepts them back, so a
    record on disk can carry them."""
    body = {"schema": SCHEMA, "head_sha": _SHA, "ci_conclusion": "success", "ci_run": "1",
            "tests_passed": 10, "tests_total": 10, "tests_ok": True, "audits_ok": True,
            "notes": "", "success": True}
    body.update(over)
    d = _gate_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sha}.json").write_text(json.dumps(body), encoding="utf-8")


def _read(root, sha=_SHA):
    return build_trusted_manifest(str(root), ".", sha)       # must never raise


def _assert_refused_with_diagnosis(out, *names):
    assert out["success"] is False
    assert out["present"] is True, "a SHA-bound but malformed record is present, not absent"
    summary = out["summary"]
    assert isinstance(summary, str) and "CI success" in summary, (
        "the refusal must keep the evidence line it refused")
    assert any(n in summary for n in names), f"summary must name what was wrong {names}: {summary}"


def _record(root, **over):
    kw = {"ci_conclusion": "success", "ci_run": "1", "tests_passed": 10, "tests_total": 10,
          "tests_ok": True, "audits_ok": True}
    kw.update(over)
    return record_gate_manifest(str(root), _SHA, **kw)


def _assert_writer_refuses(root, **over):
    """Two valid refusal contracts; anything else (success persisted, TypeError...) fails."""
    path = _gate_dir(root) / f"{_SHA}.json"
    try:
        written = _record(root, **over)
    except ValueError:
        assert not path.exists(), "a refused write must not leave a gate record behind"
        if _gate_dir(root).exists():
            assert list(_gate_dir(root).iterdir()) == []
        return
    assert written.get("success") is False, f"writer accepted {over} as successful evidence"
    if path.exists():
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored.get("success") is not True, f"success persisted for {over}"
    assert _read(root)["success"] is False


# --- controls: valid native evidence still authorises -------------------------------------------

@pytest.mark.parametrize("passed,total", [(10, 10), (8, 10), (1, 1)])
def test_valid_native_record_is_read_as_successful(tmp_path, passed, total):
    """Skips exist: 8 of 10 with tests_ok=True is a legitimate green gate."""
    _write_raw(tmp_path, tests_passed=passed, tests_total=total)
    out = _read(tmp_path)
    assert out["present"] is True and out["success"] is True
    assert f"{passed}/{total}" in out["summary"]


@pytest.mark.parametrize("passed,total", [(10, 10), (8, 10)])
def test_valid_native_evidence_is_written_and_read_back_as_successful(tmp_path, passed, total):
    written = _record(tmp_path, tests_passed=passed, tests_total=total)
    assert written["success"] is True and written["schema"] == SCHEMA
    stored = json.loads((_gate_dir(tmp_path) / f"{_SHA}.json").read_text(encoding="utf-8"))
    assert type(stored["tests_passed"]) is int and type(stored["tests_total"]) is int
    assert stored["tests_ok"] is True and stored["audits_ok"] is True and stored["success"] is True
    assert _read(tmp_path)["success"] is True


# --- native false refuses ------------------------------------------------------------------------

@pytest.mark.parametrize("flag", ["tests_ok", "audits_ok"])
def test_native_false_flag_refuses_at_both_boundaries(tmp_path, flag):
    _write_raw(tmp_path, **{flag: False, "success": False})
    assert _read(tmp_path)["success"] is False
    other = tmp_path / "w"
    written = _record(other, **{flag: False})
    assert written["success"] is False
    assert _read(other)["success"] is False


# --- flags are booleans, not truthiness ----------------------------------------------------------

@pytest.mark.parametrize("value", _NOT_BOOLEANS, ids=repr)
@pytest.mark.parametrize("flag", ["tests_ok", "audits_ok"])
def test_non_boolean_flag_in_a_record_is_refused(tmp_path, flag, value):
    _write_raw(tmp_path, **{flag: value})
    _assert_refused_with_diagnosis(_read(tmp_path), flag)


@pytest.mark.parametrize("value", _NOT_BOOLEANS, ids=repr)
def test_non_boolean_stored_success_is_refused(tmp_path, value):
    """Evidence is genuine here; only the stored verdict is not a boolean."""
    _write_raw(tmp_path, success=value)
    _assert_refused_with_diagnosis(_read(tmp_path), "success=", "`success`", "stored verdict")


@pytest.mark.parametrize("value", _NOT_BOOLEANS, ids=repr)
@pytest.mark.parametrize("flag", ["tests_ok", "audits_ok"])
def test_writer_never_turns_a_non_boolean_flag_into_success(tmp_path, flag, value):
    _assert_writer_refuses(tmp_path, **{flag: value})


# --- counts are native non-negative integers, passed <= total ------------------------------------

@pytest.mark.parametrize("passed,total", _BAD_COUNTS)
def test_invalid_counts_in_a_record_are_refused(tmp_path, passed, total):
    _write_raw(tmp_path, tests_passed=passed, tests_total=total)
    _assert_refused_with_diagnosis(_read(tmp_path), "tests_passed", "tests_total")


@pytest.mark.parametrize("passed,total", _BAD_COUNTS)
def test_writer_never_turns_invalid_counts_into_success(tmp_path, passed, total):
    _assert_writer_refuses(tmp_path, tests_passed=passed, tests_total=total)


@pytest.mark.parametrize("passed,total", [(0, 0), (0, 10)])
@pytest.mark.parametrize("claimed", [True, False])
def test_zero_passed_never_authorises_a_go(tmp_path, passed, total, claimed):
    _write_raw(tmp_path, tests_passed=passed, tests_total=total, success=claimed)
    assert _read(tmp_path)["success"] is False
    other = tmp_path / "w"
    assert _record(other, tests_passed=passed, tests_total=total)["success"] is False
    assert _read(other)["success"] is False


# --- existing binding and provenance rules still hold for a strictly valid record ----------------

def test_strict_record_is_still_bound_to_its_sha_and_schema(tmp_path):
    _write_raw(tmp_path, sha=_OTHER, tests_passed=8, tests_total=10)    # body names _SHA
    assert load_gate_manifest(str(tmp_path), _OTHER) is None
    assert _read(tmp_path, _OTHER)["success"] is False

    v1 = tmp_path / "v1"
    _write_raw(v1, tests_passed=8, tests_total=10, schema=None)
    out = _read(v1)
    assert out["present"] is True and out["success"] is False

    with pytest.raises(ValueError):
        record_gate_manifest(str(tmp_path / "short"), "abc123", ci_conclusion="success",
                             tests_passed=10, tests_total=10, tests_ok=True, audits_ok=True)

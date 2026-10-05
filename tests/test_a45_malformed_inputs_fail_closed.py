"""A4.5 tails — syntactically valid JSON of the wrong SHAPE must fail closed, not crash.

Three loose ends from the same review. Each was reproduced by execution before being fixed, and in
two cases the observed behaviour was a crash at a trust boundary rather than the refusal the
surrounding code promises:

1. ``build_trusted_manifest`` derives the verdict with ``int(gate.get("tests_passed") or 0)``. A
   record whose ``tests_passed`` is a string or a list raises straight out of the trusted READ
   boundary — the one place whose entire job is to decide whether evidence may be believed. A
   manifest that cannot be understood is not a manifest; it must be refused, and refusing is not
   the same as raising.
2. ``campaign_evidence_counts`` read ``{"evidence": [...]}``. The production pipeline writes
   ``{finding_id: {...}}`` (``engine._persist_finding``) and ``build_evidence_index`` writes
   ``{evidence_id: {...}}``. The reader matched neither, so every real index was counted as
   *unreadable* and the client-safe count was structurally always zero: a canonical count that
   never read the canonical file.
3. ``_read_state`` treated "parsed successfully" as "is a mapping". ``null``, ``[]``, ``"done"``
   and ``42`` are all valid JSON, so the caller's ``rs.get(...)`` raised ``AttributeError`` and took
   the whole project index down — the screen that exists to surface trouble.
"""
from __future__ import annotations

import json

import pytest

from core.collaboration.manifest import SCHEMA, build_trusted_manifest

_SHA = "a" * 40


def _gate(tmp_path, **over):
    d = tmp_path / "_review_relay" / "collab_gate"
    d.mkdir(parents=True, exist_ok=True)
    body = {"schema": SCHEMA, "head_sha": _SHA, "ci_conclusion": "success", "ci_run": "1",
            "tests_passed": 10, "tests_total": 10, "tests_ok": True, "audits_ok": True,
            "notes": "", "success": True}
    body.update(over)
    (d / f"{_SHA}.json").write_text(json.dumps(body), encoding="utf-8")


# --- 1. the trusted read boundary refuses, it does not raise --------------------------------------

@pytest.mark.parametrize("value", [{}, [], "lots", "", None, {"n": 1}, [1, 2], True])
def test_a_malformed_tests_count_is_refused_not_raised(tmp_path, value):
    _gate(tmp_path, tests_passed=value)
    out = build_trusted_manifest(str(tmp_path), ".", _SHA)     # must not raise
    assert out["success"] is False, f"tests_passed={value!r} must not authorise a GO"


@pytest.mark.parametrize("value", [{}, [], "many", None])
def test_a_malformed_tests_total_is_refused_not_raised(tmp_path, value):
    _gate(tmp_path, tests_total=value)
    out = build_trusted_manifest(str(tmp_path), ".", _SHA)
    assert out["present"] is True
    assert isinstance(out["summary"], str), "the summary must still render for a malformed record"


def test_a_gate_record_that_is_not_an_object_is_refused(tmp_path):
    d = tmp_path / "_review_relay" / "collab_gate"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{_SHA}.json").write_text("[1, 2, 3]", encoding="utf-8")
    out = build_trusted_manifest(str(tmp_path), ".", _SHA)
    assert out["present"] is False and out["success"] is False


def test_a_well_formed_record_still_succeeds(tmp_path):
    """Control: hardening the parser must not refuse a real manifest."""
    _gate(tmp_path)
    assert build_trusted_manifest(str(tmp_path), ".", _SHA)["success"] is True


# --- 2. the canonical count must read what production actually writes ------------------------------

def _direct_run(tmp_path, cid="camp-1"):
    (tmp_path / "scout" / cid).mkdir(parents=True, exist_ok=True)
    (tmp_path / "scout" / cid / "state.json").write_text(
        json.dumps({"run_id": cid, "status": "COMPLETED"}), encoding="utf-8")
    prospect = tmp_path / "scout" / cid / "prospects" / "p1"
    prospect.mkdir(parents=True, exist_ok=True)
    return prospect


def test_the_count_reads_the_shape_the_engine_actually_persists(tmp_path):
    """`engine._persist_finding` writes `{finding_id: {...}}`, not `{"evidence": [...]}`."""
    from core.scout.evidence_counts import campaign_evidence_counts
    prospect = _direct_run(tmp_path)
    (prospect / "EVIDENCE_INDEX_f1.json").write_text(json.dumps({
        "f1": {"evidence_id": "e1", "storage_ref": "ref", "hash": "h",
               "client_safe": True, "sanitization_status": "sanitized",
               "verification_status": "VERIFIED"}}), encoding="utf-8")
    counts = campaign_evidence_counts(str(tmp_path), "camp-1")
    assert counts["unreadable_indexes"] == 0, "the real production shape must not read as unreadable"
    assert counts["client_safe"] == 1


def test_the_count_reads_the_build_evidence_index_shape_too(tmp_path):
    """`build_evidence_index` writes `{evidence_id: {...}}` — a second real shape."""
    from core.scout.evidence_counts import campaign_evidence_counts
    prospect = _direct_run(tmp_path)
    (prospect / "EVIDENCE_INDEX_f2.json").write_text(json.dumps({
        "e9": {"finding_id": "f2", "type": "screenshot_original", "storage_ref": "r",
               "hash": "h", "sanitization_status": "sanitized", "client_safe": True,
               "verification_status": "VERIFIED", "retention_deadline": ""}}), encoding="utf-8")
    counts = campaign_evidence_counts(str(tmp_path), "camp-1")
    assert counts["unreadable_indexes"] == 0
    assert counts["client_safe"] == 1


def test_a_record_asserting_client_safe_without_provenance_is_not_counted_as_proven(tmp_path):
    """The engine shape historically carried only the flag, with no sanitisation/verification.

    Such a record cannot prove the claim from its own contents, and before A4.5 the writer could set
    it on REJECTED evidence. It is reported separately rather than counted as proven or silently
    dropped — the operator needs to see that the provenance is missing.
    """
    from core.scout.evidence_counts import campaign_evidence_counts
    prospect = _direct_run(tmp_path)
    (prospect / "EVIDENCE_INDEX_f3.json").write_text(json.dumps({
        "f3": {"evidence_id": "e3", "storage_ref": "r", "hash": "h", "client_safe": True}}),
        encoding="utf-8")
    counts = campaign_evidence_counts(str(tmp_path), "camp-1")
    assert counts["client_safe"] == 0, "an unprovable claim is not a proven one"
    assert counts["client_safe_unverifiable"] == 1
    assert counts["unreadable_indexes"] == 0, "it is readable; it just proves nothing"


def test_a_rejected_item_is_never_counted_however_the_flag_was_written(tmp_path):
    from core.scout.evidence_counts import campaign_evidence_counts
    prospect = _direct_run(tmp_path)
    (prospect / "EVIDENCE_INDEX_f4.json").write_text(json.dumps({
        "f4": {"evidence_id": "e4", "client_safe": True, "sanitization_status": "rejected",
               "verification_status": "VERIFIED"}}), encoding="utf-8")
    assert campaign_evidence_counts(str(tmp_path), "camp-1")["client_safe"] == 0


def test_the_engine_persists_the_provenance_the_count_needs(tmp_path):
    """Structural: the writer must emit what the reader requires, or the gap reopens."""
    import inspect

    from core.scout.pipeline import engine
    src = inspect.getsource(engine)
    src = src[src.index("EVIDENCE_INDEX_"):src.index("EVIDENCE_INDEX_") + 900]
    assert "sanitization_status" in src and "verification_status" in src, (
        "EVIDENCE_INDEX records must carry the provenance that makes `client_safe` checkable")


@pytest.mark.parametrize("body", ["null", "[1,2]", '"done"', "42", "{bad"])
def test_a_malformed_evidence_index_is_reported_not_crashed(tmp_path, body):
    from core.scout.evidence_counts import campaign_evidence_counts
    prospect = _direct_run(tmp_path)
    (prospect / "EVIDENCE_INDEX_f5.json").write_text(body, encoding="utf-8")
    counts = campaign_evidence_counts(str(tmp_path), "camp-1")   # must not raise
    assert counts["unreadable_indexes"] == 1
    assert counts["client_safe"] == 0


# --- 3. valid JSON of the wrong shape is UNKNOWN, not a crash --------------------------------------

@pytest.mark.parametrize("body", ["null", "[1,2]", '"done"', "42", "true"])
def test_a_non_object_work_run_state_yields_unknown_rather_than_crashing(tmp_path, body):
    from core.orchestration.project_index import ProjectIndex
    ark = tmp_path / "p1" / "40_ark_work"
    ark.mkdir(parents=True)
    (ark / "WORK_PACKET.json").write_text(json.dumps({"project_id": "p1"}), encoding="utf-8")
    (ark / "WORK_RUN_STATE.json").write_text(body, encoding="utf-8")

    entries = ProjectIndex(str(tmp_path))._client_projects()      # must not raise
    assert entries, "the project must still be listed"
    assert entries[0].lifecycle_state == "UNKNOWN"
    assert entries[0].blockers, "the operator must see that the state could not be read"


@pytest.mark.parametrize("body", ["null", "[1,2]", '"x"', "7"])
def test_a_non_object_work_packet_does_not_crash_the_index(tmp_path, body):
    """The sibling file read by the same loop, with the same `.get` assumption."""
    from core.orchestration.project_index import ProjectIndex
    ark = tmp_path / "p2" / "40_ark_work"
    ark.mkdir(parents=True)
    (ark / "WORK_PACKET.json").write_text(body, encoding="utf-8")
    (ark / "WORK_RUN_STATE.json").write_text(json.dumps({"status": "EXECUTING"}), encoding="utf-8")
    ProjectIndex(str(tmp_path))._client_projects()                # must not raise


@pytest.mark.parametrize("body", ["null", "[1,2]", '"x"'])
def test_a_non_object_scout_state_does_not_crash_the_index(tmp_path, body):
    from core.orchestration.project_index import ProjectIndex
    run = tmp_path / "scout" / "camp-9"
    run.mkdir(parents=True)
    (run / "state.json").write_text(body, encoding="utf-8")
    (run / "report").mkdir()
    ProjectIndex(str(tmp_path))._scout_campaigns(include_diagnostics=True)   # must not raise

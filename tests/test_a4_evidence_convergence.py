"""A4 — minimum evidence/finding convergence (Issue #74, Macro A).

A1 re-proved that the "ONE evidence model" invariant is violated: three ``EvidenceItem`` dataclasses
and two unbridged finding types. Recon for A4 changed the shape of the work:

* ``core/schemas/execution_summary.py:EvidenceItem`` has **no** product consumer — deprecate, not adapt.
* ``core/schemas/evidence.py:EvidenceRecord`` already sits on the delivery path with fail-closed
  client-safety defaults. It is the canonical record; it is *extended* (``content_hash``,
  ``verification_status``), never replaced, and no fourth model is introduced.
* The live shapes (client-work ``work_execution.EvidenceItem``, Scout pipeline ``EvidenceItem``, and
  ``BrowserExecutionEvidence``, which only a structural scan found) get adapters **onto** the
  canonical record; ``ScoutFinding`` gets an adapter onto ``Finding`` in the
  existing adapter home ``core/risk/finding_adapters.py``.

Every adapter is fail-closed: nothing becomes client-visible unless the source proves it, nothing is
invented (no fabricated hash, timestamp or recommendation), and the origin is preserved in
``notes``/``tags`` so the conversion is auditable rather than lossy.
"""
from __future__ import annotations

import pathlib
import re

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[1]


# --- the canonical record is extended, compatibly ---------------------------------------------------

def test_the_canonical_record_carries_integrity_and_verification_fail_closed():
    from core.schemas.evidence import EvidenceRecord
    rec = EvidenceRecord(id="e1", evidence_type="command_log", path="a.log")
    assert rec.content_hash == "", "no hash may be invented for evidence that was never hashed"
    assert rec.verification_status == "UNVERIFIED"
    # the Phase 4B safety defaults are untouched by the extension
    assert rec.client_visible is False and rec.internal_only is True
    assert rec.requires_redaction is True and rec.redacted is False


def test_a_persisted_record_from_before_the_extension_still_loads():
    """`from_dict` must default the new fields, so existing evidence collections keep loading."""
    from core.schemas.evidence import EvidenceRecord
    legacy = {"id": "e0", "evidence_type": "validation_report", "path": "v.json", "title": "v",
              "description": "", "source_phase": "validation", "client_visible": False,
              "internal_only": True, "requires_redaction": True, "redacted": False,
              "created_at": "2026-01-01T00:00:00+00:00", "notes": []}
    rec = EvidenceRecord.from_dict(legacy)
    assert rec.content_hash == "" and rec.verification_status == "UNVERIFIED"
    assert rec.to_dict()["content_hash"] == ""


# --- client-work evidence -> canonical record -------------------------------------------------------

def test_work_execution_evidence_adapts_onto_the_canonical_record_without_inventing_anything():
    from core.schemas.evidence import EvidenceRecord
    from core.schemas.evidence_adapters import evidence_record_from_work_execution
    from core.schemas.work_execution import EvidenceItem

    item = EvidenceItem(evidence_id="wx-1", kind="test_output", relative_path="out/pytest.txt",
                        description="pytest run", created_at="2026-09-18T10:00:00+00:00")
    rec = evidence_record_from_work_execution(item, source_phase="execution")

    assert isinstance(rec, EvidenceRecord)
    assert (rec.id, rec.evidence_type, rec.path, rec.description, rec.created_at) == (
        "wx-1", "test_output", "out/pytest.txt", "pytest run", "2026-09-18T10:00:00+00:00")
    assert rec.source_phase == "execution"
    # fail closed: the source has no client-safety or integrity information, so none is granted
    assert rec.client_visible is False and rec.internal_only is True
    assert rec.requires_redaction is True and rec.redacted is False
    assert rec.content_hash == "" and rec.verification_status == "UNVERIFIED"
    assert any("work_execution" in n for n in rec.notes), "the origin must be auditable"


def test_work_execution_adapter_keeps_a_missing_timestamp_missing():
    from core.schemas.evidence_adapters import evidence_record_from_work_execution
    from core.schemas.work_execution import EvidenceItem
    rec = evidence_record_from_work_execution(EvidenceItem(evidence_id="wx-2"))
    assert rec.created_at == "", "an adapter must not stamp 'now' onto evidence captured at an unknown time"


# --- Scout pipeline evidence -> canonical record ----------------------------------------------------

def _scout_item(**over):
    from core.scout.pipeline.evidence import EvidenceItem
    base = dict(evidence_id="sc-1", finding_id="f-1", campaign_id="c-1", session_id="s-1",
                page_url="https://example.test/", evidence_type="screenshot_annotated",
                captured_at="2026-09-18T11:00:00+00:00", tool="playwright", tool_version="1.2",
                sanitization_status="sanitized", verification_status="VERIFIED", client_safe=True,
                content_hash="sha256:abc", storage_ref="evidence/c-1/sc-1.png")
    base.update(over)
    return EvidenceItem(**base)


def test_scout_evidence_carries_integrity_and_verification_onto_the_canonical_record():
    from core.schemas.evidence_adapters import evidence_record_from_scout_pipeline
    rec = evidence_record_from_scout_pipeline(_scout_item())
    assert rec.id == "sc-1" and rec.path == "evidence/c-1/sc-1.png"
    assert rec.evidence_type == "screenshot_annotated"
    assert rec.content_hash == "sha256:abc"
    assert rec.verification_status == "VERIFIED"
    assert rec.created_at == "2026-09-18T11:00:00+00:00"
    assert rec.source_phase == "scout"
    joined = " ".join(rec.notes)
    for provenance in ("f-1", "c-1", "s-1", "playwright"):
        assert provenance in joined, f"provenance {provenance!r} must survive the adaptation"


@pytest.mark.parametrize("client_safe, sanitization, expect_visible", [
    (True, "sanitized", True),
    (True, "unsanitized", False),    # a bare client_safe flag is not enough
    (False, "sanitized", False),     # sanitized but not cleared for the client
    (False, "unsanitized", False),
    (True, "rejected", False),
])
def test_scout_evidence_is_client_visible_only_when_the_source_proves_both_conditions(
        client_safe, sanitization, expect_visible):
    """Client visibility is never inferred from one caller-supplied boolean."""
    from core.schemas.evidence_adapters import evidence_record_from_scout_pipeline
    rec = evidence_record_from_scout_pipeline(
        _scout_item(client_safe=client_safe, sanitization_status=sanitization))
    assert rec.client_visible is expect_visible
    assert rec.internal_only is (not expect_visible)
    assert rec.redacted is (sanitization == "sanitized")
    assert rec.requires_redaction is (sanitization != "sanitized")


# --- every type an adapter can emit is in the canonical vocabulary ----------------------------------

def test_every_adaptable_evidence_type_is_declared_in_the_canonical_vocabulary():
    """Adapters must not smuggle undeclared types into the canonical record.

    `EVIDENCE_TYPES` on the canonical module was declared and never enforced; converging onto it
    without extending its vocabulary would make the vocabulary a lie about what the record holds.
    """
    from core.schemas.browser_execution import EVIDENCE_TYPES as BROWSER_TYPES
    from core.schemas.evidence import EVIDENCE_TYPES
    from core.schemas.evidence_adapters import WORK_EXECUTION_KINDS
    from core.scout.pipeline.evidence import EVIDENCE_TYPES as SCOUT_TYPES
    missing = sorted((set(WORK_EXECUTION_KINDS) | set(SCOUT_TYPES) | set(BROWSER_TYPES))
                     - set(EVIDENCE_TYPES))
    assert not missing, f"adaptable evidence types absent from the canonical vocabulary: {missing}"


def test_an_undeclared_work_execution_kind_is_kept_but_flagged_not_silently_relabelled():
    from core.schemas.evidence_adapters import evidence_record_from_work_execution
    from core.schemas.work_execution import EvidenceItem
    rec = evidence_record_from_work_execution(EvidenceItem(evidence_id="wx-3", kind="hologram"))
    assert rec.evidence_type == "hologram", "the adapter must not guess a different type"
    assert any("undeclared" in n for n in rec.notes), "an undeclared type must be flagged in notes"
    assert rec.client_visible is False


# --- browser-execution evidence -> canonical record --------------------------------------------------
#
# Found by a name-agnostic scan AFTER the first three adapters were written: `BrowserExecutionEvidence`
# is a strict field-subset of `EvidenceRecord` with the same safety-field names, produced live by
# `core/browser_execution_runner.py`. The suffix-based shape scan could not see it.

def test_browser_execution_evidence_adapts_losslessly_and_keeps_its_safety_flags():
    from core.schemas.browser_execution import BrowserExecutionEvidence
    from core.schemas.evidence_adapters import evidence_record_from_browser_execution
    src = BrowserExecutionEvidence(id="be-1", evidence_type="playwright_report", path="report.html",
                                   title="Playwright report", description="run 1",
                                   internal_only=True, client_visible=False,
                                   requires_redaction=True, redacted=False, notes=["captured"])
    rec = evidence_record_from_browser_execution(src)
    assert (rec.id, rec.evidence_type, rec.path, rec.title, rec.description) == (
        "be-1", "playwright_report", "report.html", "Playwright report", "run 1")
    assert rec.source_phase == "browser_execution"
    assert (rec.internal_only, rec.client_visible, rec.requires_redaction, rec.redacted) == (
        True, False, True, False)
    assert rec.created_at == "", "the source carries no capture time; none may be invented"
    assert rec.content_hash == "" and rec.verification_status == "UNVERIFIED"
    assert "captured" in rec.notes and any("browser_execution" in n for n in rec.notes)


def test_browser_execution_adapter_carries_an_explicitly_cleared_record_but_never_widens_one():
    """The source already owns the safety decision; the adapter copies it and never relaxes it."""
    from core.schemas.browser_execution import BrowserExecutionEvidence
    from core.schemas.evidence_adapters import evidence_record_from_browser_execution
    cleared = evidence_record_from_browser_execution(BrowserExecutionEvidence(
        id="be-2", evidence_type="screenshot", path="s.png", internal_only=False,
        client_visible=True, requires_redaction=False, redacted=True))
    assert cleared.client_visible is True and cleared.redacted is True
    # a contradictory source (visible but never redacted) must NOT come out client-visible
    contradictory = evidence_record_from_browser_execution(BrowserExecutionEvidence(
        id="be-3", evidence_type="screenshot", path="s.png", internal_only=False,
        client_visible=True, requires_redaction=True, redacted=False))
    assert contradictory.client_visible is False
    assert contradictory.internal_only is True
    assert any("contradictory" in n for n in contradictory.notes)


# --- ScoutFinding -> Finding, in the existing adapter home -----------------------------------------

def _scout_finding(**over):
    from core.scout.findings import ScoutFinding
    base = dict(finding_id="SF-1", run_id="r-1", url="https://example.test/checkout",
                check_family="forms", category="functional", title="Submit button unreachable",
                severity="high", confidence="high",
                expected="Submit enabled after valid input", actual="Submit stays disabled",
                business_impact="Checkout cannot complete", evidence_refs=["ev/1.png", "ev/2.json"],
                sanitized=True, verification_state="VERIFIED")
    base.update(over)
    return ScoutFinding(**base)


def test_scout_finding_adapts_onto_the_canonical_finding_preserving_its_origin():
    from core.risk.finding_adapters import finding_from_scout
    from core.schemas.finding import Confidence, Finding, FindingCategory, FindingStatus, Severity
    f = finding_from_scout(_scout_finding())
    assert isinstance(f, Finding)
    assert f.id == "SF-1" and f.title == "Submit button unreachable"
    assert f.severity is Severity.HIGH and f.confidence is Confidence.HIGH
    assert f.category is FindingCategory.FUNCTIONAL
    assert f.status is FindingStatus.OPEN, "a VERIFIED Scout finding is a real open finding"
    assert f.source_module == "scout" and f.affected_area == "https://example.test/checkout"
    assert f.client_impact == "Checkout cannot complete"
    assert "Submit enabled after valid input" in f.description and "Submit stays disabled" in f.description
    assert f.recommendation == "", "Scout has no recommendation; the adapter must not invent one"
    assert "scout:check_family=forms" in f.tags and "scout:verification=VERIFIED" in f.tags


@pytest.mark.parametrize("state, expected_status", [
    ("UNVERIFIED", "needs_review"),
    ("REPRODUCED", "needs_review"),
    ("EVIDENCE_CAPTURED", "needs_review"),
    ("SANITIZED", "needs_review"),
    ("VERIFIED", "open"),
    ("REJECTED", "false_positive"),
])
def test_only_a_verified_scout_finding_becomes_an_open_finding(state, expected_status):
    """Anything short of VERIFIED lands in NEEDS_REVIEW — never presented as established."""
    from core.risk.finding_adapters import finding_from_scout
    f = finding_from_scout(_scout_finding(verification_state=state))
    assert f.status.value == expected_status


def test_evidence_refs_reach_the_canonical_finding_only_when_the_source_is_client_safe():
    """`Finding.evidence` flows to client delivery; operator-only refs must not ride along."""
    from core.risk.finding_adapters import finding_from_scout
    safe = finding_from_scout(_scout_finding(sanitized=True, verification_state="VERIFIED"))
    assert "ev/1.png" in safe.evidence and "ev/2.json" in safe.evidence

    unsanitized = finding_from_scout(_scout_finding(sanitized=False, verification_state="VERIFIED"))
    assert unsanitized.evidence == ""
    assert "scout:evidence_withheld=not_client_safe" in unsanitized.tags

    unverified = finding_from_scout(_scout_finding(sanitized=True, verification_state="REPRODUCED"))
    assert unverified.evidence == ""


@pytest.mark.parametrize("scout_category, canonical", [
    ("functional", "functional"), ("accessibility", "accessibility"),
    ("performance", "performance"), ("reliability", "reliability"),
    ("mobile", "ux"), ("business_flow", "functional"),
    ("seo", "unknown"), ("structured_data", "unknown"), ("coverage", "unknown"),
])
def test_scout_categories_map_onto_the_canonical_vocabulary_and_keep_the_original(
        scout_category, canonical):
    """No category is silently upgraded; the Scout label always survives as a tag."""
    from core.risk.finding_adapters import finding_from_scout
    f = finding_from_scout(_scout_finding(category=scout_category))
    assert f.category.value == canonical
    assert f"scout:category={scout_category}" in f.tags


# --- the dead shape is deprecated, and stays dead ---------------------------------------------------

def _product_sources():
    for root in ("core", "integrations", "tools"):
        for p in (_REPO / root).rglob("*.py"):
            if "__pycache__" not in p.parts:
                yield p
    yield _REPO / "main.py"


def test_no_product_code_uses_the_deprecated_execution_summary_evidence_shape():
    """`core/schemas/execution_summary.py` is exported but consumed by nothing; keep it that way.

    The re-export in `core/schemas/__init__.py` is the one permitted reference (removing a public
    name is a separate decision). Any other product-side use would be a fourth live shape.
    """
    offenders = []
    for path in _product_sources():
        text = path.read_text(encoding="utf-8", errors="replace")
        rel = path.relative_to(_REPO).as_posix()
        if rel in ("core/schemas/execution_summary.py", "core/schemas/__init__.py"):
            continue
        # Module references only. `evidence_type="execution_summary"` in browser_execution is a
        # string literal in a vocabulary, not a use of this shape.
        if re.search(r"core\.schemas\.execution_summary|\bExecutionSummary\b", text) or \
                re.search(r"from core\.schemas import [^\n]*\bEvidenceItem\b", text):
            offenders.append(rel)
    assert not offenders, "deprecated evidence shape used by product code: " + repr(offenders)


def test_the_deprecated_module_says_so():
    from core.schemas import execution_summary
    assert "deprecated" in (execution_summary.__doc__ or "").lower()
    assert "EvidenceRecord" in (execution_summary.__doc__ or "")


# --- ONE evidence model: every evidence-shaped class is classified ----------------------------------

_EVIDENCE_CLASS = re.compile(r"^class (\w*Evidence\w*(?:Item|Record))\b", re.M)
_PATH_FIELDS = {"path", "file_path", "relative_path", "storage_ref"}


def _evidence_shapes(root: pathlib.Path):
    """Every evidence-shaped class in core/: by NAME and, independently, by STRUCTURE.

    The name scan alone missed `BrowserExecutionEvidence` — a per-item evidence record whose name
    carries neither suffix. A class with an `evidence_type` field and a path-like field is an
    evidence record whatever it is called, so both detectors run and their union is what must be
    classified.
    """
    import ast
    found = set()
    for p in (root / "core").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        rel = p.relative_to(root).as_posix()
        for m in _EVIDENCE_CLASS.finditer(text):
            found.add(f"{rel}:{m.group(1)}")
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            names = {s.target.id for s in node.body
                     if isinstance(s, ast.AnnAssign) and isinstance(s.target, ast.Name)}
            if "evidence_type" in names and names & _PATH_FIELDS:
                found.add(f"{rel}:{node.name}")
    return found


def test_every_evidence_shaped_class_is_classified_against_the_canonical_model():
    """Adding an evidence-shaped dataclass without saying how it relates to the canonical one fails."""
    from core.schemas.evidence_adapters import EVIDENCE_SHAPE_REGISTRY
    live = _evidence_shapes(_REPO)
    unclassified = sorted(live - set(EVIDENCE_SHAPE_REGISTRY))
    dead_entries = sorted(set(EVIDENCE_SHAPE_REGISTRY) - live)
    assert not unclassified, "evidence-shaped classes not classified in EVIDENCE_SHAPE_REGISTRY: " \
        + repr(unclassified)
    assert not dead_entries, "registry entries no longer present in core/: " + repr(dead_entries)
    roles = set(EVIDENCE_SHAPE_REGISTRY.values())
    assert roles <= {"canonical", "adapted", "deprecated", "aggregate"}
    assert list(EVIDENCE_SHAPE_REGISTRY.values()).count("canonical") == 1, \
        "exactly one canonical evidence record"


def test_the_shape_scan_reports_an_unclassified_class(tmp_path):
    """Control: the scan must actually find a new shape, or the registry test proves nothing."""
    (tmp_path / "core" / "x").mkdir(parents=True)
    (tmp_path / "core" / "x" / "new.py").write_bytes(b"class FourthEvidenceItem:\n    pass\n")
    assert "core/x/new.py:FourthEvidenceItem" in _evidence_shapes(tmp_path)


def test_the_shape_scan_finds_an_evidence_record_by_structure_when_the_name_hides_it(tmp_path):
    """Control for the structural detector: no suffix, but evidence_type + a path field."""
    (tmp_path / "core" / "y").mkdir(parents=True)
    (tmp_path / "core" / "y" / "blob.py").write_bytes(
        b"from dataclasses import dataclass\n@dataclass\nclass CapturedBlob:\n"
        b"    evidence_type: str = ''\n    storage_ref: str = ''\n")
    (tmp_path / "core" / "y" / "artifact.py").write_bytes(
        b"from dataclasses import dataclass\n@dataclass\nclass ProducedThing:\n"
        b"    kind: str = ''\n    relative_path: str = ''\n")
    shapes = _evidence_shapes(tmp_path)
    assert "core/y/blob.py:CapturedBlob" in shapes
    assert "core/y/artifact.py:ProducedThing" not in shapes, \
        "a produced artifact with only `kind` is not an evidence record and must not be flagged"

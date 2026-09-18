"""A4 — adapters from the live evidence shapes onto the canonical ``EvidenceRecord``.

The "ONE evidence model" invariant was found violated (A1): three ``EvidenceItem`` dataclasses and
no bridge between them. This module is the bridge, and it deliberately adds **no** fourth shape:
the canonical record is ``core.schemas.evidence.EvidenceRecord`` — it already sits on the delivery
path (``evidence_manager``, ``work_delivery``) with fail-closed client-safety defaults — and the live
producer shapes adapt *onto* it. There are three of those, not two: the client-work and Scout
pipeline ``EvidenceItem`` classes A1 counted, plus ``BrowserExecutionEvidence``, which a name-based
scan cannot see and a structural one found after the first two adapters were written.

Every adapter follows three rules:

* **Fail closed.** ``client_visible`` is granted only when EVERY safety condition the source exposes
  agrees - clearance, sanitisation, verification, not marked internal-only; a single caller-supplied
  boolean is never enough and a contradiction between flags is resolved to internal-only. Everything
  else keeps the canonical defaults (``internal_only=True``, ``requires_redaction=True``).
* **Invent nothing.** No hash, timestamp or status is fabricated for a source that does not carry
  one; an absent value stays absent (``""`` / ``UNVERIFIED``).
* **Preserve the origin.** The source shape and its identifiers go into ``notes`` so a converted
  record is auditable rather than lossy.

``EVIDENCE_SHAPE_REGISTRY`` names every evidence-shaped class in ``core/`` and its relation to the
canonical record; a guard test fails when a new one appears unclassified.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.schemas.evidence import EVIDENCE_TYPES, EvidenceRecord

# The documented vocabulary of `core/schemas/work_execution.py:EvidenceItem.kind`. Kept here (not
# inferred from a comment) so the canonical vocabulary can be checked against it.
WORK_EXECUTION_KINDS = ("artifact", "screenshot", "trace", "log", "test_output", "diff", "report")

# How every evidence-shaped class in core/ relates to the canonical record. Roles:
#   canonical  - THE product evidence record; extend it, never replace it
#   adapted    - a live producer shape with an adapter in this module (or a documented path) onto it
#   deprecated - no product consumer; kept only as an exported name, must not gain one
#   aggregate  - a report/coverage/media summary, not a per-item evidence record
EVIDENCE_SHAPE_REGISTRY: Dict[str, str] = {
    "core/schemas/evidence.py:EvidenceRecord": "canonical",
    "core/schemas/work_execution.py:EvidenceItem": "adapted",
    "core/scout/pipeline/evidence.py:EvidenceItem": "adapted",
    "core/schemas/browser_execution.py:BrowserExecutionEvidence": "adapted",
    "core/schemas/execution_summary.py:EvidenceItem": "deprecated",
    "core/schemas/qa_report.py:QAEvidenceItem": "aggregate",
    "core/schemas/media_evidence.py:MediaEvidenceItem": "aggregate",
    "core/schemas/evidence_intelligence.py:EvidenceCoverageItem": "aggregate",
}


def evidence_record_from_work_execution(item: Any, *, source_phase: str = "execution") -> EvidenceRecord:
    """``core.schemas.work_execution.EvidenceItem`` -> canonical record.

    The client-work shape carries no integrity or client-safety information, so none is granted:
    the record is internal-only and unverified until something that can prove otherwise says so.
    """
    kind = str(getattr(item, "kind", "") or "")
    notes: List[str] = [f"adapted_from=core.schemas.work_execution.EvidenceItem id={getattr(item, 'evidence_id', '')}"]
    if kind not in EVIDENCE_TYPES:
        # Kept, not relabelled: guessing a different type would be a silent claim about the
        # evidence. The flag makes it visible to whoever reads the record.
        notes.append(f"evidence_type undeclared in canonical vocabulary: {kind!r}")
    return EvidenceRecord(
        id=str(getattr(item, "evidence_id", "") or ""),
        evidence_type=kind,
        path=str(getattr(item, "relative_path", "") or ""),
        title=str(getattr(item, "description", "") or "")[:120],
        description=str(getattr(item, "description", "") or ""),
        source_phase=source_phase,
        # created_at is passed through verbatim — an unknown capture time stays unknown.
        created_at=str(getattr(item, "created_at", "") or ""),
        notes=notes,
    )


def evidence_record_from_browser_execution(item: Any) -> EvidenceRecord:
    """``core.schemas.browser_execution.BrowserExecutionEvidence`` -> canonical record.

    A strict field-subset of the canonical record with the same safety-field names, so the copy is
    lossless. The source already owns its client-safety decision and the adapter carries it across;
    what it will not do is *widen* it: a record marked ``client_visible`` that was never redacted is
    internally contradictory, and fails closed to internal-only with the contradiction noted.
    """
    visible = bool(getattr(item, "client_visible", False))
    internal_only = bool(getattr(item, "internal_only", True))
    redacted = bool(getattr(item, "redacted", False))
    requires_redaction = bool(getattr(item, "requires_redaction", True))
    notes: List[str] = list(getattr(item, "notes", None) or [])
    notes.append(f"adapted_from=core.schemas.browser_execution.BrowserExecutionEvidence "
                 f"id={getattr(item, 'id', '')}")
    # Visibility requires EVERY safety flag the source exposes to agree: cleared, not marked
    # internal-only, redaction completed and no longer required. Any contradiction fails closed.
    # (The first version checked redaction and forgot `internal_only`, so a record the source
    # itself marked internal could come out client-visible.)
    if visible and (internal_only or requires_redaction or not redacted):
        notes.append("contradictory source safety flags (client_visible while internal_only or "
                     "without completed redaction); kept internal-only")
        visible = False
    return EvidenceRecord(
        id=str(getattr(item, "id", "") or ""),
        evidence_type=str(getattr(item, "evidence_type", "") or ""),
        path=str(getattr(item, "path", "") or ""),
        title=str(getattr(item, "title", "") or ""),
        description=str(getattr(item, "description", "") or ""),
        source_phase="browser_execution",
        client_visible=visible,
        internal_only=not visible,
        requires_redaction=requires_redaction,
        redacted=redacted,
        created_at="",
        notes=notes,
    )


def evidence_record_from_scout_pipeline(item: Any) -> EvidenceRecord:
    """``core.scout.pipeline.evidence.EvidenceItem`` -> canonical record.

    The Scout shape is the richest source: it carries a content hash, a verification status, a
    sanitisation status and a client-safety flag. Integrity and verification are carried across
    verbatim. Client visibility requires BOTH ``client_safe`` and ``sanitization_status ==
    "sanitized"`` — the flag alone is exactly the caller-supplied boolean this module refuses to
    trust.
    """
    sanitization = str(getattr(item, "sanitization_status", "") or "")
    sanitized = sanitization == "sanitized"
    verification = str(getattr(item, "verification_status", "") or "UNVERIFIED")
    # The same contract `ScoutFinding.is_client_safe` enforces: independently VERIFIED and
    # sanitised, and cleared. The source dataclass permits `client_safe=True` on an UNVERIFIED item,
    # so trusting the flag plus sanitisation alone emitted a client-visible record that itself said
    # it was unverified. (The finding adapter had this right; this one did not - one predicate, two
    # adapters.)
    visible = bool(getattr(item, "client_safe", False)) and sanitized and verification == "VERIFIED"
    provenance = {k: getattr(item, k, "") for k in
                  ("finding_id", "company_id", "campaign_id", "session_id", "page_url", "tool",
                   "tool_version", "viewport", "locale", "browser", "retention_deadline")}
    notes: List[str] = ["adapted_from=core.scout.pipeline.evidence.EvidenceItem"]
    notes.append("provenance: " + " ".join(f"{k}={v}" for k, v in provenance.items() if v))
    notes.append(f"sanitization_status={sanitization or 'unknown'}")
    notes.extend(str(n) for n in (getattr(item, "notes", None) or []))
    return EvidenceRecord(
        id=str(getattr(item, "evidence_id", "") or ""),
        evidence_type=str(getattr(item, "evidence_type", "") or ""),
        path=str(getattr(item, "storage_ref", "") or ""),
        title=str(getattr(item, "evidence_type", "") or ""),
        description=str(getattr(item, "page_url", "") or ""),
        source_phase="scout",
        client_visible=visible,
        internal_only=not visible,
        requires_redaction=not sanitized,
        redacted=sanitized,
        created_at=str(getattr(item, "captured_at", "") or ""),
        notes=notes,
        content_hash=str(getattr(item, "content_hash", "") or ""),
        verification_status=verification,
    )

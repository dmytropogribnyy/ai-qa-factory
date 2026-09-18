"""Trusted CI/test manifest for one exact SHA (Issue #14 P0 — independent evidence for a CHECKPOINT GO).

The autonomous reviewer must not authorize a GO on the worker's claims. A *trusted manifest* is a
bounded, local, machine-written record of the approved gate's result for one exact head SHA — CI
conclusion, deterministic test totals, and audit outcomes — produced by the trusted local workflow (the
launcher/operator), never by the remote model. It is persisted under the same ``_review_relay`` base and
its CONTENTS are fed into the evidence pack; a CHECKPOINT can only GO when this manifest is present and
explicitly successful for the exact SHA.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")

SCHEMA = "collab-gate-manifest/v2"

# The evidence a verdict is derived FROM. A record missing any of them is incomplete: it carries a
# conclusion without the facts that conclusion is supposed to summarise, and the reader cannot
# re-derive it. v1 records (no `schema`) predate the derivation and are readable but never
# successful - they were written when a caller could supply the verdict directly.
_EVIDENCE_FIELDS = ("ci_conclusion", "tests_passed", "tests_total", "tests_ok", "audits_ok")


def _derive_success(gate: Dict[str, Any]) -> bool:
    """The ONE place a gate verdict is computed, used when writing and again when reading."""
    return (str(gate.get("ci_conclusion", "")).lower() == "success"
            and bool(gate.get("tests_ok"))
            and bool(gate.get("audits_ok"))
            and int(gate.get("tests_passed") or 0) > 0)


def _gate_dir(output_root: str) -> Path:
    path = Path(output_root) / "_review_relay" / "collab_gate"
    path.mkdir(parents=True, exist_ok=True)
    return path


def record_gate_manifest(output_root: str, head_sha: str, *, ci_conclusion: str = "",
                         ci_run: str = "", tests_passed: int = 0, tests_total: int = 0,
                         tests_ok: bool = False, audits_ok: bool = False,
                         notes: str = "") -> Dict[str, Any]:
    """Trusted local workflow writes the approved gate's result for an exact SHA (never the model).

    There is deliberately no ``success`` parameter. It used to exist and to override the derivation,
    which made the "trusted" verdict a value the caller could simply state - the precise trust hole
    the producer above it exists to close. The verdict is derived here from the evidence, and
    derived again when the record is read.
    """
    sha = str(head_sha or "").strip().lower()
    if not _FULL_SHA.fullmatch(sha):
        raise ValueError("gate manifest requires an exact full 40-char head SHA")
    manifest = {"schema": SCHEMA,
                "head_sha": sha, "ci_conclusion": str(ci_conclusion), "ci_run": str(ci_run),
                "tests_passed": int(tests_passed), "tests_total": int(tests_total),
                "tests_ok": bool(tests_ok), "audits_ok": bool(audits_ok),
                "notes": str(notes)[:2000],
                "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    manifest["success"] = _derive_success(manifest)
    (_gate_dir(output_root) / f"{sha}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return manifest


def load_gate_manifest(output_root: str, head_sha: str) -> Optional[Dict[str, Any]]:
    """The record filed under ``sha``, and only if its BODY also describes ``sha``.

    The filename was the sole binding, so copying `X.json` to `Y.json` re-pointed X's evidence at
    commit Y. A record that does not name the commit it is filed under is not evidence about it.
    """
    sha = str(head_sha or "").strip().lower()
    if not _FULL_SHA.fullmatch(sha):
        return None
    path = _gate_dir(output_root) / f"{sha}.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    if str(data.get("head_sha", "")).strip().lower() != sha:
        return None
    return data


def build_trusted_manifest(output_root: str, repo_root: str, head_sha: str) -> Dict[str, Any]:
    """Assemble the trusted-evidence view the reviewer needs. ``present``/``success`` gate a CHECKPOINT GO.

    The stored ``success`` is never believed. It is re-derived from the evidence in the same record,
    and a record whose stored verdict disagrees with its own evidence is refused rather than
    reconciled - the disagreement is the signal. This is the READ boundary of the same rule
    `record_gate_manifest` applies at the WRITE boundary.
    """
    gate = load_gate_manifest(output_root, head_sha)
    if not gate:
        return {"present": False, "success": False,
                "summary": ("no trusted CI/test gate manifest recorded for this exact SHA, or the "
                            "record found does not name that SHA")}

    conclusion = str(gate.get("ci_conclusion") or "") or "unavailable"
    summary = (f"CI {conclusion} (run {gate.get('ci_run') or '-'}); tests "
               f"{gate.get('tests_passed', 0)}/{gate.get('tests_total', 0)} "
               f"ok={gate.get('tests_ok')}; audits ok={gate.get('audits_ok')}")

    missing = [f for f in _EVIDENCE_FIELDS if f not in gate]
    if missing:
        return {"present": True, "success": False, "gate": gate,
                "summary": f"{summary}; record is INCOMPLETE - missing evidence {missing}, so its "
                           "verdict cannot be re-derived"}

    derived = _derive_success(gate)
    if bool(gate.get("success")) != derived:
        return {"present": True, "success": False, "gate": gate,
                "summary": f"{summary}; stored verdict success={gate.get('success')} CONTRADICTS its "
                           f"own evidence (derived {derived}) - refusing the record"}

    if str(gate.get("schema") or "") != SCHEMA:
        return {"present": True, "success": False, "gate": gate,
                "summary": f"{summary}; record carries no `schema` provenance (pre-v2), written when "
                           "a caller could supply the verdict directly - re-run the gate producer"}

    return {"present": True, "success": derived,
            "summary": summary + ("" if derived else "; gate not successful"), "gate": gate}

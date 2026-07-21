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
from pathlib import Path
from typing import Any, Dict, Optional

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def _gate_dir(output_root: str) -> Path:
    path = Path(output_root) / "_review_relay" / "collab_gate"
    path.mkdir(parents=True, exist_ok=True)
    return path


def record_gate_manifest(output_root: str, head_sha: str, *, ci_conclusion: str = "",
                         ci_run: str = "", tests_passed: int = 0, tests_total: int = 0,
                         tests_ok: bool = False, audits_ok: bool = False,
                         notes: str = "", success: Optional[bool] = None) -> Dict[str, Any]:
    """Trusted local workflow writes the approved gate's result for an exact SHA (never the model)."""
    sha = str(head_sha or "").strip().lower()
    if not _FULL_SHA.fullmatch(sha):
        raise ValueError("gate manifest requires an exact full 40-char head SHA")
    ok = (str(ci_conclusion).lower() == "success" and bool(tests_ok) and bool(audits_ok)
          if success is None else bool(success))
    manifest = {"head_sha": sha, "ci_conclusion": str(ci_conclusion), "ci_run": str(ci_run),
                "tests_passed": int(tests_passed), "tests_total": int(tests_total),
                "tests_ok": bool(tests_ok), "audits_ok": bool(audits_ok),
                "notes": str(notes)[:2000], "success": ok}
    (_gate_dir(output_root) / f"{sha}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return manifest


def load_gate_manifest(output_root: str, head_sha: str) -> Optional[Dict[str, Any]]:
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
    return data if isinstance(data, dict) else None


def build_trusted_manifest(output_root: str, repo_root: str, head_sha: str) -> Dict[str, Any]:
    """Assemble the trusted-evidence view the reviewer needs. ``present``/``success`` gate a CHECKPOINT GO."""
    gate = load_gate_manifest(output_root, head_sha)
    if not gate:
        return {"present": False, "success": False,
                "summary": "no trusted CI/test gate manifest recorded for this exact SHA"}
    summary = (f"CI {gate.get('ci_conclusion','?')} (run {gate.get('ci_run','?')}); tests "
               f"{gate.get('tests_passed',0)}/{gate.get('tests_total',0)} "
               f"ok={gate.get('tests_ok')}; audits ok={gate.get('audits_ok')}")
    return {"present": True, "success": bool(gate.get("success")), "summary": summary, "gate": gate}

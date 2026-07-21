"""Canonical run classification + campaign enumeration (Slice 2).

ONE shared read-model over the EXISTING persisted campaign source — ``scout/_runcontrol/`` (the same
source Observer/CampaignService use) — so the Dashboard and Observer report the SAME production
campaign counts. It creates NO new business-state database; it only reads and classifies.

A *production* campaign is a real orchestrated campaign recorded in ``scout/_runcontrol/<id>.json``.
Diagnostic, acceptance, safe-live-acceptance, skip-proof, replay, headed-replay, per-target (promo),
demo and reserved bookkeeping artifacts are classified OUT of the default production views (still
available via an explicit "Show diagnostics"). Classification is by the run/campaign id — the exact
diagnostic naming used across the codebase — so a real ``campaign-<slug>-<stamp>-<hex>`` id is
production while ``smoke-a`` / ``v33-live-acceptance`` / ``*-promo-*`` are not.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

# Substrings that mark a run/campaign id as a diagnostic/acceptance/replay/per-target/demo artifact.
_DIAGNOSTIC_MARKERS = (
    "smoke", "acceptance", "skip-proof", "-promo-", "promo-", "demo",
    "replay", "headed-replay", "fixture",
)


def is_diagnostic_run(run_id: str) -> bool:
    """True if a scout run/campaign id is NOT a production client campaign.

    Reserved bookkeeping dirs (``_registry``, ``_runcontrol``, ``_bundles``, ``_campaigns``,
    ``_dashboard``, ``_locks``, any ``_``-prefixed) and the known diagnostic naming patterns are
    diagnostic; anything else (a real ``campaign-<slug>-<stamp>-<hex>`` id) is production."""
    n = (run_id or "").strip().lower()
    if not n or n.startswith("_"):
        return True
    return any(marker in n for marker in _DIAGNOSTIC_MARKERS)


def _runcontrol_ids(output_dir: str) -> List[str]:
    """Canonical campaign ids = the stems of ``scout/_runcontrol/*.json`` (identical to Observer)."""
    rc = Path(output_dir) / "scout" / "_runcontrol"
    if not rc.is_dir():
        return []
    return sorted(p.stem for p in rc.glob("*.json"))


def canonical_campaigns(output_dir: str, *, include_diagnostics: bool = False) -> List[Dict[str, Any]]:
    """Enumerate campaigns from the canonical ``_runcontrol`` source, each tagged production/diagnostic.

    By default only production campaigns are returned (diagnostics excluded); pass
    ``include_diagnostics=True`` to get every canonical campaign with its ``diagnostic`` flag."""
    rows: List[Dict[str, Any]] = []
    for cid in _runcontrol_ids(output_dir):
        diagnostic = is_diagnostic_run(cid)
        if diagnostic and not include_diagnostics:
            continue
        rows.append({"campaign_id": cid, "diagnostic": diagnostic})
    return rows


def campaign_counts(output_dir: str) -> Dict[str, int]:
    """Production vs diagnostic canonical campaign counts (the truthful, Observer-matching split)."""
    ids = _runcontrol_ids(output_dir)
    diagnostic = sum(1 for cid in ids if is_diagnostic_run(cid))
    return {"production": len(ids) - diagnostic, "diagnostic": diagnostic, "total": len(ids)}

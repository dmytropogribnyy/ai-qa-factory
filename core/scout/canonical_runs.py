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

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# A REAL production campaign id is minted as ``campaign-<business-slug>-<YYYYMMDDThhmmssZ>-<hex6>``
# (see core.scout.discovery.config.fresh_campaign_id). Any id of this exact shape is production —
# regardless of what words the business slug contains (e.g. "smokehouse", "product-demo",
# "acceptance-consulting", "fixture-manufacturer"). This structural origin signal is what prevents a
# real campaign from vanishing from production just because its name matched a naming heuristic.
_PRODUCTION_ID_RE = re.compile(r"^campaign-.+-\d{8}t\d{6}z-[0-9a-f]{6}$")

# Legacy diagnostic runs (created by demos / acceptance / replay scripts, predating run-control) are
# matched by EXACT ANCHORED patterns only — never an arbitrary substring — so a business slug that
# merely contains one of these words is not misclassified.
_DIAG_PREFIXES = ("smoke-", "replay-", "headed-replay-", "v33-", "acceptance-")
_DIAG_SUFFIXES = (
    re.compile(r"-demo$"),
    re.compile(r"-promo-\d+$"),
    re.compile(r"-acceptance$"),
    re.compile(r"-skip-proof$"),
)
_DIAG_EXACT = frozenset({"smoke", "demo", "replay", "fixture", "acceptance", "radar-demo",
                         "scout-demo"})

# Explicit persisted run-kind values (authoritative when available). Production kinds win; the rest
# force diagnostic without touching the id at all.
_KIND_PRODUCTION = frozenset({"production", "campaign", "client", "real", "prod"})
_KIND_DIAGNOSTIC = frozenset({"smoke", "acceptance", "safe-live-acceptance", "demo", "replay",
                              "headed-replay", "skip-proof", "fixture", "diagnostic", "acceptance-proof"})


def is_diagnostic_run(run_id: str, *, run_kind: Optional[str] = None) -> bool:
    """True if a scout run/campaign id is NOT a production client campaign.

    Classification order (most authoritative first):
      1. An EXPLICIT persisted run-kind marker (``run_kind``), when available, decides outright.
      2. Reserved bookkeeping ids (``_``-prefixed / empty) are diagnostic.
      3. A real ``campaign-<slug>-<stamp>-<hex>`` structured id is PRODUCTION — regardless of the
         words in its business slug (this is the fix for classifier false positives).
      4. Otherwise, legacy diagnostic runs are matched by exact anchored prefixes/suffixes/whole-id
         names only — never an arbitrary substring.
      5. Anything else defaults to production (never hide real work on a mere name guess)."""
    if run_kind:
        rk = str(run_kind).strip().lower()
        if rk in _KIND_PRODUCTION:
            return False
        if rk in _KIND_DIAGNOSTIC:
            return True
    n = (run_id or "").strip().lower()
    if not n or n.startswith("_"):
        return True
    if _PRODUCTION_ID_RE.match(n):
        return False
    if n in _DIAG_EXACT:
        return True
    if any(n.startswith(p) for p in _DIAG_PREFIXES):
        return True
    if any(rx.search(n) for rx in _DIAG_SUFFIXES):
        return True
    return False


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

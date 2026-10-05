"""ONE canonical evidence count for a campaign (Issue #74, A4.5).

Two surfaces counted "evidence" for the same campaign from different places and disagreed:

* the Dashboard's **Evidence** column counted ``scout/<cid>/report/*.json`` — the discovery
  *planning* artifacts (``DISCOVERY_PLAN.json``, ``PROMOTED_TARGETS.json``, …). A completed
  discovery campaign therefore showed a constant 13 that does not move whether or not a single
  screenshot was captured, and is not evidence at all;
* the Observer's evidence manifest counted the real per-prospect artifacts across the campaign's
  promoted runs.

Neither number was labelled, so the operator could not tell which one to believe. Per the
controller's decision the evidence count comes from the canonical persisted evidence, and
client-safe is reported as its own field rather than folded into the total — "how much evidence
exists" and "how much may be shown to a client" are different questions and were never the same
number.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

# The artifact kinds the canonical evidence surface publishes. Kept here so the Dashboard and the
# Observer cannot drift apart again by editing one list.
EVIDENCE_SUFFIXES = frozenset({".json", ".png", ".webm"})



def _index_records(data: Any) -> Optional[List[Dict[str, Any]]]:
    """The evidence records in an EVIDENCE_INDEX file, whatever real shape it uses.

    Two shapes are written in production and the first reader matched NEITHER, so every genuine
    index counted as unreadable and the client-safe count was structurally always zero:

    * ``engine._persist_finding``   -> ``{finding_id:  {...}}``
    * ``build_evidence_index``      -> ``{evidence_id: {...}}``

    Both are mappings of id -> record, so one rule covers them. ``{"evidence": [...]}`` is accepted
    too because that is the shape the first version expected and a stored file may still use it.
    Returns None when the file is readable JSON but not an index at all.
    """
    if isinstance(data, dict):
        listed = data.get("evidence")
        if isinstance(listed, list):
            return [r for r in listed if isinstance(r, dict)]
        records = [v for v in data.values() if isinstance(v, dict)]
        # A mapping with no record-shaped value is not an index; saying so beats counting zero.
        return records if records else None
    return None


def promoted_run_ids(output_dir: str, campaign_id: str) -> List[str]:
    """The runs whose prospect evidence belongs to this campaign.

    A DIRECT run holds its own; a discovery campaign promotes candidates into their own runs and
    holds none itself. Mirrors `ObserverAPI._promoted_runs` so both count over the same set.
    """
    from core.scout.canonical_runs import KIND_DIRECT, run_kind
    from core.scout.store import RunStore
    if run_kind(output_dir, campaign_id) == KIND_DIRECT:
        return [campaign_id]
    # The canonical state reader, not a hand-built path - the store owns where state lives.
    try:
        state = RunStore(output_dir, campaign_id).load_state()
    except Exception:
        return []
    if not isinstance(state, dict):
        return []
    return [str(c.get("promoted_scout_run")) for c in state.get("candidates", [])
            if isinstance(c, dict) and c.get("promoted_scout_run")]


def campaign_evidence_counts(output_dir: str, campaign_id: str) -> Dict[str, Any]:
    """``{"total", "client_safe", "unreadable_indexes"}`` for one campaign.

    ``total`` counts durable per-prospect artifacts, immediate children only — a failed cleanup must
    never make `_vidtmp` working files count as evidence. ``client_safe`` is read from the persisted
    ``EVIDENCE_INDEX_*.json`` records and requires the item's OWN sanitisation and verification, the
    same predicate `EvidenceItem.is_client_safe` applies; a missing or unreadable index contributes
    nothing to ``client_safe`` and is counted in ``unreadable_indexes`` so the gap is visible rather
    than read as "none are client-safe".
    """
    root = Path(output_dir) / "scout"
    total = 0
    client_safe = 0
    unverifiable = 0
    unreadable = 0

    for run_id in promoted_run_ids(output_dir, campaign_id):
        prospects = root / run_id / "prospects"
        if not prospects.is_dir():
            continue
        for prospect_dir in prospects.iterdir():
            if not prospect_dir.is_dir():
                continue
            for f in prospect_dir.iterdir():
                if f.is_file() and f.suffix.lower() in EVIDENCE_SUFFIXES:
                    total += 1
            for index in prospect_dir.glob("EVIDENCE_INDEX_*.json"):
                try:
                    data = json.loads(index.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    unreadable += 1
                    continue
                records = _index_records(data)
                if records is None:
                    unreadable += 1
                    continue
                for item in records:
                    if not bool(item.get("client_safe")):
                        continue
                    sanitization = item.get("sanitization_status")
                    verification = item.get("verification_status")
                    if sanitization is None or verification is None:
                        # The historical engine record carried only the flag. It cannot prove the
                        # claim from its own contents, so it is neither counted as proven nor
                        # silently dropped - the missing provenance is reported.
                        unverifiable += 1
                    elif (str(sanitization) == "sanitized" and str(verification) == "VERIFIED"):
                        client_safe += 1

    return {"total": total, "client_safe": client_safe,
            "client_safe_unverifiable": unverifiable, "unreadable_indexes": unreadable}

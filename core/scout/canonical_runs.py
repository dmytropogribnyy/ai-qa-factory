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
                              "headed-replay", "skip-proof", "fixture", "diagnostic",
                              "acceptance-proof", "manual_test", "manual-test"})


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


# What KIND of run an id names. Two different things have always lived in `scout/`: a discovery
# CAMPAIGN, which searches and has its own run-control record, and a DIRECT run over a list of
# targets somebody supplied. Campaign-shaped questions were asked of both, and the direct run — with
# no run-control file to read — answered with the run-control DEFAULT: queued, no counters, no
# timestamps. A finished run therefore read as never started, beside an Activity log showing it
# complete. Naming the kind is what lets a campaign-only question be refused instead of answered
# wrongly.
KIND_CAMPAIGN = "campaign"
KIND_DIRECT = "direct"
KIND_UNKNOWN = "unknown"

NOT_APPLICABLE = "NOT_APPLICABLE"

_TERMINAL_STATES = frozenset({"COMPLETED", "FAILED", "STOPPED", "CANCELLED"})


def run_kind(output_dir: str, run_id: str) -> str:
    """Classify an id by what actually exists on disk for it, never by its shape.

    A run-control record is written when a campaign is LAUNCHED, so it is sufficient evidence of a
    campaign and not necessary: a campaign that predates run control, or whose launch record was
    lost, still holds the thing that actually makes it one — a candidate list. Treating those as
    direct runs emptied their evidence manifests, so the second signal is the same one
    ``run_validation`` uses to decide the very same question.
    """
    if not run_id:
        return KIND_UNKNOWN
    root = Path(output_dir) / "scout"
    if (root / "_runcontrol" / f"{run_id}.json").is_file():
        return KIND_CAMPAIGN
    state_path = root / run_id / "state.json"
    if not state_path.is_file():
        return KIND_UNKNOWN
    import json
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return KIND_DIRECT
    return KIND_CAMPAIGN if "candidates" in (state or {}) else KIND_DIRECT


def canonical_run_state(output_dir: str, run_id: str) -> Dict[str, Any]:
    """The ONE state answer for a run, read from whichever store actually owns it.

    Returns ``kind``, the ``state`` that store recorded, whether it is ``terminal``, and ``source``
    so a disagreement can be traced to the file it came from rather than argued about.
    """
    import json
    kind = run_kind(output_dir, run_id)
    if kind == KIND_CAMPAIGN:
        from core.scout.run_control import CampaignRunControl
        control = CampaignRunControl(run_id, output_dir)
        state = str(control.state.state or "")
        return {"kind": kind, "state": state, "terminal": state.upper() in _TERMINAL_STATES,
                "source": f"scout/_runcontrol/{run_id}.json",
                "updated_at": control.state.updated_at}
    if kind == KIND_DIRECT:
        try:
            raw = json.loads((Path(output_dir) / "scout" / run_id / "state.json")
                             .read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        state = str(raw.get("status") or "")
        return {"kind": kind, "state": state, "terminal": state.upper() in _TERMINAL_STATES,
                "source": f"scout/{run_id}/state.json",
                "updated_at": raw.get("finished_at") or raw.get("updated_at")
                or raw.get("started_at") or ""}
    return {"kind": kind, "state": "", "terminal": False, "source": "", "updated_at": ""}


def _runcontrol_ids(output_dir: str) -> List[str]:
    """Canonical campaign ids = the stems of ``scout/_runcontrol/*.json`` (identical to Observer)."""
    rc = Path(output_dir) / "scout" / "_runcontrol"
    if not rc.is_dir():
        return []
    return sorted(p.stem for p in rc.glob("*.json"))


def _declared_kinds(output_dir: str):
    """What each run declared it was for — authoritative when present, absent for older runs.

    A declaration outranks every id heuristic below it. Without this, a campaign minted with a
    perfectly ordinary production-shaped id counts as production on Overview while Data management,
    reading the same run's own config, calls it acceptance — one run, two answers.
    """
    from core.scout.run_purpose import PURPOSE_UNCLASSIFIED, RunPurposeIndex
    index = RunPurposeIndex(output_dir)

    def kind_of(run_id: str) -> Optional[str]:
        purpose = index.purpose_of(run_id)
        return None if purpose == PURPOSE_UNCLASSIFIED else purpose

    return kind_of


def is_diagnostic(output_dir: str, run_id: str) -> bool:
    """``is_diagnostic_run`` with the run's OWN declared purpose consulted.

    The bare form takes a purpose the caller must remember to look up, and several surfaces did not:
    Overview and the Observer's campaign list classified by id alone, so a run that declared itself
    acceptance but happened to carry a production-shaped id was counted as real work on exactly the
    screens the operator uses to judge how much real work there is. The declaration is the run's own
    statement about itself and outranks any reading of its name — so the lookup belongs here, once,
    rather than at each call site that has to remember it.
    """
    return is_diagnostic_run(run_id, run_kind=_declared_kinds(output_dir)(run_id))


def canonical_campaigns(output_dir: str, *, include_diagnostics: bool = False) -> List[Dict[str, Any]]:
    """Enumerate campaigns from the canonical ``_runcontrol`` source, each tagged production/diagnostic.

    By default only production campaigns are returned (diagnostics excluded); pass
    ``include_diagnostics=True`` to get every canonical campaign with its ``diagnostic`` flag."""
    rows: List[Dict[str, Any]] = []
    kind_of = _declared_kinds(output_dir)
    for cid in _runcontrol_ids(output_dir):
        diagnostic = is_diagnostic_run(cid, run_kind=kind_of(cid))
        if diagnostic and not include_diagnostics:
            continue
        rows.append({"campaign_id": cid, "diagnostic": diagnostic})
    return rows


def campaign_counts(output_dir: str) -> Dict[str, int]:
    """Production vs diagnostic canonical campaign counts (the truthful, Observer-matching split)."""
    ids = _runcontrol_ids(output_dir)
    kind_of = _declared_kinds(output_dir)
    diagnostic = sum(1 for cid in ids if is_diagnostic_run(cid, run_kind=kind_of(cid)))
    return {"production": len(ids) - diagnostic, "diagnostic": diagnostic, "total": len(ids)}

"""Fixability classification (v3.3, stage-3 paid-fix scoping).

Given verified QA findings, classify each by whether WE could fix it ourselves — honestly and
conservatively (project rule: never promise a fix we cannot deliver). A finding is only
``fix_ready`` when it is in our proven QA/front-end fix capability AND access (repo/staging) is
available; without access the best it can be is ``fix_after_access``; categories outside our proven
capability are ``out_of_scope`` (advice only). This feeds the operator's stage-3 paid fix offer and
the client-work brief; the system never auto-commits to a fix.
"""
from __future__ import annotations

from typing import Any, Dict, List

FIX_READY = "fix_ready"
FIX_AFTER_ACCESS = "fix_after_access"
OUT_OF_SCOPE = "out_of_scope"

# Categories within our proven QA / front-end fix capability. Fixing any of them still needs access
# to the repo/staging, so without access they are FIX_AFTER_ACCESS rather than FIX_READY.
_FIXABLE = frozenset({"functional", "accessibility", "performance", "seo", "structured_data",
                      "mobile", "business_flow", "reliability"})
# Not claimed as our own fix: meta/coverage findings and anything not in _FIXABLE (advice only).
_META = frozenset({"coverage"})


def classify_finding_fixability(finding: Dict[str, Any], *, access_available: bool) -> Dict[str, str]:
    """Classify one finding's fixability tier + an honest reason."""
    cat = str(finding.get("category", "")).lower()
    if cat in _FIXABLE:
        if access_available:
            return {"fix_tier": FIX_READY,
                    "fix_reason": "within our QA/front-end fix capability; access is available"}
        return {"fix_tier": FIX_AFTER_ACCESS,
                "fix_reason": "we can fix this once repo/staging access is provided"}
    if cat in _META:
        return {"fix_tier": OUT_OF_SCOPE, "fix_reason": "coverage/meta note, not a defect to fix"}
    return {"fix_tier": OUT_OF_SCOPE,
            "fix_reason": "outside our proven fix capability (we would advise, not fix)"}


def classify_fixability(findings: List[Dict[str, Any]], *,
                        access_available: bool = False) -> Dict[str, Any]:
    """Classify a set of findings into fixability tiers + a conservative summary for the fix offer."""
    counts = {FIX_READY: 0, FIX_AFTER_ACCESS: 0, OUT_OF_SCOPE: 0}
    items: List[Dict[str, Any]] = []
    for f in findings or []:
        c = classify_finding_fixability(f, access_available=access_available)
        counts[c["fix_tier"]] += 1
        items.append({"severity": f.get("severity"), "category": f.get("category"),
                      "title": f.get("title"), "business_impact": f.get("business_impact"), **c})
    offerable = counts[FIX_READY] + counts[FIX_AFTER_ACCESS]
    return {"access_available": access_available, "counts": counts, "items": items,
            "offerable": offerable, "summary": _summary(counts, access_available)}


def _summary(counts: Dict[str, int], access_available: bool) -> str:
    r, a, o = counts[FIX_READY], counts[FIX_AFTER_ACCESS], counts[OUT_OF_SCOPE]
    if access_available:
        return f"{r} fixable now, {a} fixable once outstanding access is granted, {o} out of scope."
    total_fixable = r + a
    if total_fixable == 0:
        return f"Nothing here is fixable by us ({o} out of scope / advice only)."
    return (f"{total_fixable} fixable by us after you grant repo/staging access, {o} out of scope. "
            "Nothing is 'ready' until access is provided (no over-promising).")

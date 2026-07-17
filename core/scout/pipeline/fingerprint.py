"""Cheap site change signals + recheck classification (Final Phase I).

Computes bounded change fingerprints from a page observation (never capturing cookies, session,
or secret state) so unchanged sites can skip unnecessary deep browser work. Classifies the delta
against a prior fingerprint and picks a recheck level. Reuses the Phase 8.2 change vocabulary.
"""
from __future__ import annotations

import hashlib
from typing import Dict, Optional

CHANGE_NONE = "NO_MEANINGFUL_CHANGE"
CHANGE_MINOR = "MINOR_CHANGE"
CHANGE_MAJOR = "MAJOR_CHANGE"
CHANGE_FLOW = "BUSINESS_FLOW_CHANGED"
CHANGE_UNKNOWN = "UNKNOWN"

# Recheck levels (aligned with the Phase 8.2 RECHECK_LEVELS): L0 history, L1 cheap, ... L4 full.
RECHECK_L0, RECHECK_L1, RECHECK_L2, RECHECK_L4 = "L0", "L1", "L2", "L4"


def _sha(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_fingerprint(observation) -> Dict[str, str]:
    """Bounded content/metadata/flow hashes. Excludes headers/cookies/session by construction."""
    headings = " ".join(h.get("text", "") for h in getattr(observation, "headings", []))
    links = " ".join(sorted(getattr(observation, "links", [])))
    content = f"{observation.title}\n{headings}\n{links}"
    metadata = (f"{observation.title}\n{getattr(observation, 'meta_description', '')}\n"
                f"{getattr(observation, 'canonical', '')}\n{getattr(observation, 'robots_meta', '')}")
    flow = " ".join(sorted(f"{f.method}:{f.action}" for f in getattr(observation, "forms", [])))
    return {"content_hash": _sha(content), "metadata_hash": _sha(metadata),
            "flow_hash": _sha(flow)}


def classify_change(prior: Optional[Dict[str, str]], current: Dict[str, str]) -> str:
    if not prior:
        return CHANGE_UNKNOWN
    if prior.get("flow_hash") != current.get("flow_hash"):
        return CHANGE_FLOW
    if prior.get("content_hash") == current.get("content_hash"):
        return CHANGE_NONE
    if prior.get("metadata_hash") != current.get("metadata_hash"):
        return CHANGE_MAJOR
    return CHANGE_MINOR


def recheck_level_for(change: str) -> str:
    return {CHANGE_NONE: RECHECK_L0, CHANGE_MINOR: RECHECK_L1, CHANGE_MAJOR: RECHECK_L2,
            CHANGE_FLOW: RECHECK_L4, CHANGE_UNKNOWN: RECHECK_L1}[change]


def needs_deep_recheck(change: str) -> bool:
    """Unchanged sites avoid unnecessary browser work (L0/L1 are cheap)."""
    return change in (CHANGE_MAJOR, CHANGE_FLOW)

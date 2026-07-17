"""Idempotent import of file-based campaign/Scout runs into the memory database (Final Phase I).

Reads an existing discovery campaign RunStore (Phase 8.4 artifacts + state) and upserts campaigns,
companies, domains, and suppression into the SQLite memory. It is idempotent (upsert semantics
with deterministic ids), so importing the same run twice is safe and does not duplicate rows, and
it never deletes or invalidates the original file artifacts.
"""
from __future__ import annotations

from typing import Any, Dict

from core.scout.memory.repository import CompanyConflict, MemoryRepository
from core.scout.store import RunStore


def company_id_for(candidate: Dict[str, Any]) -> str:
    dom = candidate.get("registrable_domain") or candidate.get("normalized_url") \
        or candidate.get("candidate_id")
    return "co-" + str(dom).replace("https://", "").replace("http://", "").strip("/")[:60]


def import_campaign(store: RunStore, repo: MemoryRepository, *, clock_iso: str) -> Dict[str, int]:
    """Import a discovery campaign run into memory. Returns counts (companies/domains/suppressions)."""
    try:
        state = store.load_state()
    except Exception:
        return {"companies": 0, "domains": 0, "suppressions": 0, "conflicts": 0}
    campaign_id = state.get("campaign_id", store.root.name)
    repo.upsert_campaign(campaign_id, state.get("config", {}).get("campaign_name", campaign_id),
                         clock_iso)

    companies = domains = suppressions = conflicts = 0
    for cand in state.get("candidates", []):
        cid = company_id_for(cand)
        repo.upsert_company(cid, campaign_id, cand.get("business_name", ""),
                            cand.get("registrable_domain", ""), clock_iso,
                            confidence=cand.get("confidence", "low"))
        companies += 1
        dom = cand.get("registrable_domain")
        if dom:
            try:
                repo.add_domain(cid, dom)
                domains += 1
            except CompanyConflict:
                conflicts += 1
                repo.add_review_item(f"idreview-{cid}", "company_identity_review", dom, cid,
                                     clock_iso)
        if cand.get("suppression_status") not in (None, "", "none"):
            repo.add_suppression(cid, dom or "", cand["suppression_status"],
                                 cand.get("suppression_reason", ""), clock_iso)
            suppressions += 1
    return {"companies": companies, "domains": domains, "suppressions": suppressions,
            "conflicts": conflicts}

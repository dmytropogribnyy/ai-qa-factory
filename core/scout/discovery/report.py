"""Discovery report + artifact publishing (Phase 8.4).

Publishes the canonical Phase 8.4 artifact set atomically via the reused `ArtifactSafeWriter`
(content secret-scanned before an atomic swap), so provider secrets can never land in an
artifact. Large raw provider payloads are deliberately excluded. Nothing is sent.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List

from core.orchestration.content_safety import ArtifactSafeWriter
from core.scout.discovery.candidate import (
    PROMO_PROMOTED,
    TECH_OK,
    CandidateRecord,
)
from core.scout.store import RunStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)


def publish_discovery_report(store: RunStore, plan: Dict[str, Any],
                             records: List[CandidateRecord], norm_report, supp_report,
                             counts: Dict[str, int], budget: Dict[str, Any],
                             clock: Callable[[], str] = _now) -> Dict[str, Any]:
    generated_at = clock()
    campaign_id = plan["campaign_id"]

    discovered = [{"candidate_id": r.candidate_id, "provider_id": r.provider_id,
                   "business_name": r.business_name, "public_url": r.public_url,
                   "normalized_url": r.normalized_url, "registrable_domain": r.registrable_domain,
                   "country_hint": r.country_hint, "language_hint": r.language_hint,
                   "industry_hint": r.industry_hint, "business_type_hint": r.business_type_hint,
                   "confidence": r.confidence, "provenance": r.source_provenance}
                  for r in records]

    duplicates = [{"candidate_id": r.candidate_id, "duplicate_status": r.duplicate_status,
                   "duplicate_of": r.duplicate_of, "registrable_domain": r.registrable_domain}
                  for r in records if r.duplicate_status != "unique"]

    eligible = [_target_row(r) for r in records if r.eligibility_status == TECH_OK]
    rejected = [_target_row(r) for r in records
                if r.eligibility_status not in (TECH_OK, "pending")]
    triage = [{"candidate_id": r.candidate_id, "normalized_url": r.normalized_url,
               "commercial_status": r.commercial_status, "commercial_score": r.commercial_score,
               "promotion_decision": r.promotion_decision, "reasons": r.commercial_reasons,
               "scorecard": r.commercial_scorecard, "outreach_eligible": False}
              for r in records if r.commercial_scorecard]
    promoted = [{"candidate_id": r.candidate_id, "normalized_url": r.normalized_url,
                 "commercial_score": r.commercial_score, "promoted_scout_run": r.promoted_scout_run,
                 "provenance": r.source_provenance, "registrable_domain": r.registrable_domain}
                for r in records if r.promotion_decision == PROMO_PROMOTED]

    artifacts: Dict[str, str] = {
        "PROSPECT_CAMPAIGN.json": _dumps(plan["PROSPECT_CAMPAIGN.json"]),
        "MARKET_POLICY.json": _dumps(plan["MARKET_POLICY.json"]),
        "DISCOVERY_PLAN.json": _dumps(plan["DISCOVERY_PLAN.json"]),
        "CAMPAIGN_MATRIX.json": _dumps(plan["CAMPAIGN_MATRIX.json"]),
        "PROVIDER_BUDGET.json": _dumps({**plan["PROVIDER_BUDGET.json"], "used": budget}),
        "PROVIDER_REGISTRY_SNAPSHOT.json": _dumps(plan["PROVIDER_REGISTRY_SNAPSHOT.json"]),
        "DISCOVERED_BUSINESSES.json": _dumps(discovered),
        "CANDIDATE_NORMALIZATION_REPORT.json": _dumps(norm_report.to_dict()),
        "DUPLICATES.json": _dumps(duplicates),
        "SUPPRESSION_CHECK.json": _dumps(supp_report.to_dict()),
        "ELIGIBLE_TARGETS.json": _dumps(eligible),
        "REJECTED_TARGETS.json": _dumps(rejected),
        "COMMERCIAL_TRIAGE.json": _dumps(triage),
        "PROMOTED_TARGETS.json": _dumps(promoted),
        "DISCOVERY_SUMMARY.md": _summary_md(campaign_id, counts, budget, promoted, generated_at),
    }
    ArtifactSafeWriter(store.report_dir()).publish(artifacts)
    return {"report_dir": str(store.report_dir()), "artifacts": sorted(artifacts),
            "counts": counts, "budget": budget}


def _target_row(r: CandidateRecord) -> Dict[str, Any]:
    return {"candidate_id": r.candidate_id, "normalized_url": r.normalized_url,
            "business_name": r.business_name, "eligibility_status": r.eligibility_status,
            "technical_reasons": r.technical_reasons, "commercial_status": r.commercial_status,
            "commercial_score": r.commercial_score, "duplicate_status": r.duplicate_status,
            "suppression_status": r.suppression_status, "reason_codes": r.reason_codes}


def _summary_md(campaign_id: str, counts: Dict[str, int], budget: Dict[str, Any],
                promoted: List[Dict[str, Any]], generated_at: str) -> str:
    lines = [
        "# Discovery Summary — Prospect QA Scout (local)\n",
        f"- Campaign: `{campaign_id}`",
        f"- Generated: {generated_at}",
        f"- Candidates: {counts.get('candidates', 0)} "
        f"(unique {counts.get('unique', 0)}, duplicates {counts.get('duplicates', 0)}, "
        f"uncertain-identity {counts.get('uncertain_identity', 0)})",
        f"- Suppressed: {counts.get('suppressed', 0)} (NO_SCAN {counts.get('no_scan', 0)})",
        f"- Technically eligible: {counts.get('technical_ok', 0)}",
        f"- Commercially eligible: {counts.get('commercial_eligible', 0)}",
        f"- Promoted to Scout QA: {counts.get('promoted', 0)} "
        f"(held for review {counts.get('held_for_review', 0)})",
        f"- Provider calls: {budget.get('provider_calls', 0)}, "
        f"results: {budget.get('results', 0)}, cost: ${budget.get('cost_usd', 0)}",
        "",
        "_Local, read-only discovery + QA. No contact was collected; no outreach, form "
        "submission, account, order, or payment occurred. Commercial scoring never authorizes "
        "outreach._\n",
        "## Promoted targets\n",
    ]
    if not promoted:
        lines.append("_None promoted._")
    for p in promoted:
        lines.append(f"- `{p['candidate_id']}` — {p['normalized_url']} "
                     f"(score {p['commercial_score']}) → Scout run `{p['promoted_scout_run']}`")
    return "\n".join(lines) + "\n"

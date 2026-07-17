"""Controlled disclosure + computed draft readiness (Final Phase I).

Builds a Phase 8.2 DisclosureManifest from client-safe verified findings, honouring the
fail-closed teaser ceilings (<=1 primary + <=1 support, <=2 total for outreach). Readiness is
computed from the manifest (never a writable boolean). Draft readiness additionally requires a
verified current finding, CLIENT_SAFE evidence, an approved/ready contact, a suppression-check
reference, a country/channel policy decision, pre-draft revalidation, the manifest, and human
review. Nothing is ever sent.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.schemas.prospect_disclosure import (
    DisclosureItem,
    DisclosureManifest,
    FindingDisclosurePolicy,
)


def build_manifest(company_id: str, client_safe_findings: List[Dict[str, Any]], *, stage: str,
                   contact_ref: str = "", suppression_check_ref: str = "",
                   revalidation_ref: str = "", approval_ref: str = "", generated_at: str = "",
                   expires_at: str = "") -> DisclosureManifest:
    policy = FindingDisclosurePolicy()
    items = _items_for_stage(client_safe_findings, stage, policy)
    return DisclosureManifest(
        prospect_ref=company_id, stage=stage, items=items, policy=policy, contact_ref=contact_ref,
        suppression_check_ref=suppression_check_ref, pre_send_revalidation_ref=revalidation_ref,
        approval_ref=approval_ref,
        generated_at=generated_at or "2026-07-17T00:00:00+00:00", expires_at=expires_at)


def _items_for_stage(findings: List[Dict[str, Any]], stage: str,
                     policy: FindingDisclosurePolicy) -> List[DisclosureItem]:
    if stage == "OUTREACH":
        selected = findings[: policy.outreach_max_total]
        items = []
        for i, f in enumerate(selected):
            items.append(DisclosureItem(
                finding_ref=f["finding_id"], disclosure_level="OUTREACH_ELIGIBLE",
                role="primary" if i == 0 else "support",
                business_impact_summary=(f.get("business_impact") or f.get("title") or "QA finding"),
                evidence_refs=list(f.get("evidence_ids") or ["ev-none"]),
                storage_class="CLIENT_SAFE", sanitized=True, independently_verified=True,
                reproduction_detail_level="minimal"))
        return items
    if stage == "QUALIFICATION":
        selected = findings[: policy.qualification_max_total]
        return [DisclosureItem(
            finding_ref=f["finding_id"], disclosure_level="QUALIFICATION_ELIGIBLE",
            role="primary" if i == 0 else "support",
            business_impact_summary=(f.get("business_impact") or f.get("title") or "QA finding"),
            evidence_refs=list(f.get("evidence_ids") or []), storage_class="CLIENT_SAFE",
            sanitized=True, independently_verified=True, reproduction_detail_level="minimal")
            for i, f in enumerate(selected)]
    # INTERNAL default.
    return [DisclosureItem(finding_ref=f["finding_id"], disclosure_level="INTERNAL_ONLY",
                           role="primary" if i == 0 else "support", storage_class="RAW_INTERNAL")
            for i, f in enumerate(findings)]


def compute_draft_readiness(*, finding_client_safe: bool, finding_active: bool,
                            contact_draft_ready: bool, manifest_ready: bool,
                            suppression_check_ref: str, policy_decision: str,
                            revalidation_ref: str, human_reviewed: bool) -> Dict[str, Any]:
    """Compute (never store) whether a draft may be *prepared for the Final Phase II sending
    workflow*. Ready here means 'approved for sending workflow', never 'sent'."""
    blockers: List[str] = []
    if not finding_client_safe:
        blockers.append("finding_not_client_safe")
    if not finding_active:
        blockers.append("finding_not_active")   # a resolved finding cannot enter a draft
    if not contact_draft_ready:
        blockers.append("contact_not_ready")
    if not manifest_ready:
        blockers.append("disclosure_manifest_not_ready")
    if not suppression_check_ref.strip():
        blockers.append("missing_suppression_check")
    if policy_decision not in ("approved", "allowed"):
        blockers.append("missing_country_channel_policy_decision")
    if not revalidation_ref.strip():
        blockers.append("missing_pre_draft_revalidation")
    if not human_reviewed:
        blockers.append("human_review_required")
    return {"ready": not blockers, "blockers": blockers,
            "note": "ready means approved for the Final Phase II sending workflow; never sent"}

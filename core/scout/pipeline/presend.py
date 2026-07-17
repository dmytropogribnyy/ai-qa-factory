"""Complete pre-send pipeline orchestrator (Final Phase I).

For each promoted candidate: deep QA -> normalized verified findings + sanitized evidence ->
persist to company/site memory -> site fingerprint + recheck -> public contact intelligence ->
suppression governance -> audit-offer mapping -> controlled disclosure -> computed draft readiness
-> outreach draft (PENDING human review) -> review queue. Produces the full campaign artifact set.
**Nothing is ever sent** — the pipeline ends at a human review queue.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from core.orchestration.content_safety import ArtifactSafeWriter
from core.schemas.prospect_scoring import LeadScorecard, ScoreDimension
from core.scout.backends import make_backend
from core.scout.memory.repository import CompanyConflict, MemoryRepository
from core.scout.outreach.contacts import governance_blockers, prefer_generic_over_named
from core.scout.outreach.disclosure import build_manifest, compute_draft_readiness
from core.scout.outreach.drafts import generate_draft, render_drafts_md
from core.scout.outreach.offers import map_offer
from core.scout.pipeline.engine import DeepQaSession
from core.scout.pipeline.fingerprint import classify_change, compute_fingerprint
from core.scout.pipeline.retention import build_retention_plan
from core.scout.store import RunStore
from core.scout.url_safety import UrlPolicy

# A contact source yields public ContactRecords for a candidate (fixture/observation-driven).
ContactSource = Callable[[Dict[str, Any]], List[Any]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in str(text).lower()).strip("-")[:24] or "co"


class PreSendPipeline:
    def __init__(self, store: RunStore, repo: MemoryRepository, *, campaign_id: str,
                 policy: Optional[UrlPolicy] = None, backend=None,
                 clock: Callable[[], str] = _now, reversible_enabled: bool = False,
                 contact_source: Optional[ContactSource] = None) -> None:
        self.store = store
        self.repo = repo
        self.campaign_id = campaign_id
        self.policy = policy or UrlPolicy()
        self.backend = backend or make_backend("static", policy=self.policy)
        self.clock = clock
        self.reversible_enabled = reversible_enabled
        self.contact_source = contact_source or (lambda _c: [])

    def run(self, candidates: List[Dict[str, Any]]) -> Dict[str, Any]:
        now = self.clock()
        self.repo.upsert_campaign(self.campaign_id, self.campaign_id, now)
        agg = _Aggregate()
        for idx, cand in enumerate(candidates, start=1):
            self._process(idx, cand, agg)
        return self._finalize(agg)

    # ------------------------------------------------------------------
    def _process(self, idx: int, cand: Dict[str, Any], agg: "_Aggregate") -> None:
        now = self.clock()
        domain = cand.get("registrable_domain", "")
        company_id = "co-" + _slug(domain or cand.get("candidate_id", f"c{idx}"))
        session_id = f"{idx:02d}-{_slug(domain or company_id)}"
        url = cand["url"]

        self.repo.upsert_company(company_id, self.campaign_id, cand.get("company_name", ""),
                                 domain, now)
        if domain:
            try:
                self.repo.add_domain(company_id, domain)
            except CompanyConflict:
                self.repo.add_review_item(f"idreview-{company_id}", "company_identity_review",
                                          domain, company_id, now)
                agg.review_items.append({"queue": "company_identity_review", "company": company_id})

        # 1. deep QA
        sess = DeepQaSession(self.store, campaign_id=self.campaign_id, company_id=company_id,
                             session_id=session_id, policy=self.policy, backend=self.backend,
                             clock=self.clock, reversible_enabled=self.reversible_enabled)
        result = sess.run(url, hints=cand.get("hints"))
        self.repo.add_session(session_id, self.campaign_id, company_id, result.url, result.profile,
                              now)
        safe = [f.to_dict() for f in result.client_safe_findings()]
        for fd in [f.to_dict() for f in result.verified]:
            self.repo.upsert_finding(fd, session_id, company_id)
        for eid, entry in result.evidence_index.items():
            self.repo.add_evidence({"evidence_id": eid, **entry}, session_id)
        agg.findings.extend(safe)

        # 2. fingerprint + recheck (first pass => UNKNOWN change)
        obs = self.backend.observe(url, 15.0, 1_000_000)
        fp = compute_fingerprint(obs)
        prior = self.repo.latest_fingerprint(company_id, url)
        prior_fp = {"content_hash": prior["content_hash"],
                    "metadata_hash": prior["metadata_hash"]} if prior else None
        change = classify_change(prior_fp, fp)
        self.repo.add_fingerprint(company_id, url, fp["content_hash"], fp["metadata_hash"], now)
        agg.fingerprints.append({"company_id": company_id, "url": url, **fp, "change": change})

        # 3. contacts + governance
        contacts = list(self.contact_source(cand))
        company_suppressed = cand.get("suppression_status") in ("NO_SCAN", "COOLDOWN")
        no_outreach = cand.get("suppression_status") == "NO_OUTREACH"
        contact_dicts = []
        for c in contacts:
            self.repo.upsert_contact({"contact_id": c.contact_id, "company_id": company_id,
                                      "channel": c.channel, "normalized_value": c.normalized_value,
                                      "status": c.status,
                                      "data_subject_category": c.data_subject_category,
                                      "manual_review_required": c.manual_review_required,
                                      "last_verified_at": c.last_verified_at})
            if c.data_subject_category == "named_person" and not c.named_person_review_complete:
                self.repo.add_review_item(f"contact-{c.contact_id}", "contact_review",
                                          c.contact_id, company_id, now)
                agg.review_items.append({"queue": "contact_review", "contact": c.contact_id})
            contact_dicts.append({"contact_id": c.contact_id, "channel": c.channel,
                                  "status": c.status, "outreach_candidate": c.is_outreach_candidate,
                                  "blockers": governance_blockers(
                                      c, company_suppressed=company_suppressed,
                                      no_outreach=no_outreach, suppression_check_ref="supp-1")})
        agg.contacts.extend(contact_dicts)
        chosen = prefer_generic_over_named(contacts)

        # 4. suppression check artifact
        agg.suppression.append({"company_id": company_id, "no_outreach": no_outreach,
                                "company_suppressed": company_suppressed})

        # 5. audit offer
        offer = map_offer(company_id, safe, result.profile)
        self.repo.add_offer(offer.offer_id, company_id, offer.offer_type,
                            "; ".join(offer.rationale), now)
        agg.offers.append(offer.to_dict())

        # 6. disclosure (outreach manifest needs human approval -> not ready)
        manifest = build_manifest(company_id, safe, stage="OUTREACH", contact_ref="c",
                                  suppression_check_ref="supp-1", revalidation_ref="reval-1",
                                  generated_at=now)
        self.repo.add_disclosure(f"disc-{company_id}", company_id, manifest.is_ready,
                                 manifest.blockers, now)
        agg.disclosures.append({"company_id": company_id, "ready": manifest.is_ready,
                                "blockers": manifest.blockers,
                                "items": len(manifest.items)})

        # 7. draft readiness + draft (PENDING review; never sent)
        contact_ready = bool(chosen and chosen.is_outreach_candidate and not no_outreach
                             and not company_suppressed)
        readiness = compute_draft_readiness(
            finding_client_safe=bool(safe), finding_active=bool(safe),
            contact_draft_ready=contact_ready, manifest_ready=False,
            suppression_check_ref="supp-1", policy_decision="approved",
            revalidation_ref="reval-1", human_reviewed=False)
        agg.readiness.append({"company_id": company_id, **readiness})
        if safe and contact_ready:
            draft = generate_draft(company_id, cand.get("company_name", company_id),
                                   {"contact_id": chosen.contact_id}, safe[0], offer.to_dict(),
                                   evidence_ref=safe[0].get("evidence_ids", [""])[0],
                                   source_refs=["site"], policy_refs=["market-policy"],
                                   generated_at=now, expires_at="")
            self.repo.add_draft(draft.draft_id, company_id, chosen.contact_id, draft.channel,
                                draft.content_hash, now, draft.expires_at)
            self.repo.add_review_item(f"draft-{company_id}", "draft_review", draft.draft_id,
                                      company_id, now)
            agg.drafts.append(draft)
            agg.review_items.append({"queue": "draft_review", "draft": draft.draft_id})

        # 8. lead scorecard (QA, non-authorizing)
        agg.scorecards.append(_qa_scorecard(company_id, safe).to_dict())
        agg.companies.append({"company_id": company_id, "domain": domain,
                              "name": cand.get("company_name", ""),
                              "verified_findings": len(safe)})

    # ------------------------------------------------------------------
    def _finalize(self, agg: "_Aggregate") -> Dict[str, Any]:
        retention = build_retention_plan(
            [{"company_id": c["company_id"], "verified_findings": c["verified_findings"],
              "draft_ready": False} for c in agg.companies])
        artifacts = {
            "NORMALIZED_FINDINGS.json": _j(agg.findings),
            "COMPANY_IDENTITY.json": _j(agg.companies),
            "SITE_FINGERPRINT.json": _j(agg.fingerprints),
            "RECHECK_RESULT.json": _j([{"company_id": f["company_id"], "change": f["change"]}
                                       for f in agg.fingerprints]),
            "LEAD_SCORECARD.json": _j(agg.scorecards),
            "CONTACTS.json": _j(agg.contacts),
            "CONTACT_VERIFICATION.json": _j([{"contact_id": c["contact_id"],
                                              "status": c["status"],
                                              "outreach_candidate": c["outreach_candidate"]}
                                             for c in agg.contacts]),
            "SUPPRESSION_CHECK.json": _j(agg.suppression),
            "AUDIT_OFFER.json": _j(agg.offers),
            "DISCLOSURE_MANIFEST.json": _j(agg.disclosures),
            "OUTREACH_DRAFTS.md": render_drafts_md(agg.drafts),
            "REVIEW_QUEUE.json": _j(agg.review_items),
            "RETENTION_PLAN.json": _j(retention.to_dict()),
            "CAMPAIGN_SUMMARY.md": _summary_md(self.campaign_id, agg),
        }
        ArtifactSafeWriter(self.store.report_dir()).publish(artifacts)
        return {"campaign_id": self.campaign_id, "companies": len(agg.companies),
                "verified_findings": len(agg.findings), "contacts": len(agg.contacts),
                "drafts": len(agg.drafts), "review_items": len(agg.review_items),
                "report_dir": str(self.store.report_dir()),
                "any_sent": False}


class _Aggregate:
    def __init__(self) -> None:
        self.findings: List[Dict[str, Any]] = []
        self.companies: List[Dict[str, Any]] = []
        self.fingerprints: List[Dict[str, Any]] = []
        self.contacts: List[Dict[str, Any]] = []
        self.suppression: List[Dict[str, Any]] = []
        self.offers: List[Dict[str, Any]] = []
        self.disclosures: List[Dict[str, Any]] = []
        self.readiness: List[Dict[str, Any]] = []
        self.drafts: List[Any] = []
        self.review_items: List[Dict[str, Any]] = []
        self.scorecards: List[Dict[str, Any]] = []


def _qa_scorecard(company_id: str, safe: List[Dict[str, Any]]) -> LeadScorecard:
    dims = [
        ScoreDimension(name="audit_opportunity", value=min(len(safe) * 20, 100),
                       reasons=[f"{len(safe)} verified client-safe findings"]),
        ScoreDimension(name="evidence_quality", value=90 if safe else 10,
                       reasons=["independently verified + sanitized" if safe else "no findings"]),
        ScoreDimension(name="technical_confidence", value=70 if safe else 20),
    ]
    return LeadScorecard(prospect_id=company_id, dimensions=dims,
                         priority="B" if safe else "D", outreach_eligible=False)


def _j(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)


def _summary_md(campaign_id: str, agg: "_Aggregate") -> str:
    return (
        f"# Pre-Send Campaign Summary — {campaign_id}\n\n"
        f"- Companies: {len(agg.companies)}\n"
        f"- Verified client-safe findings: {len(agg.findings)}\n"
        f"- Public contacts observed: {len(agg.contacts)}\n"
        f"- Audit offers: {len(agg.offers)}\n"
        f"- Outreach drafts (pending human review): {len(agg.drafts)}\n"
        f"- Review-queue items: {len(agg.review_items)}\n\n"
        "_Complete local pre-send pipeline. **Nothing was sent.** No message, form, account, "
        "booking, order, payment, or external communication occurred. Drafts await human review "
        "for the Final Phase II sending workflow._\n")

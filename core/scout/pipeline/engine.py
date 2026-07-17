"""Deep-QA session orchestrator (Final Phase I).

For one promoted candidate: plan the relevant capabilities, run them twice (an independent
second pass), normalize observations into findings, verify only those that reproduce, capture
sanitized evidence for the verified ones, and persist the finding-level + plan artifacts. This
reuses the Scout static profiler/checks, the evidence center, and the finding lifecycle. It
performs read-only QA only; it never submits a form or sends anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.scout.backends import PageObservation, make_backend
from core.scout.pipeline.capabilities import run_static_capabilities, summarize
from core.scout.pipeline.evidence import EvidenceCenter, build_evidence_index
from core.scout.pipeline.finding import NormalizedFinding
from core.scout.pipeline.normalize import normalize_findings, verify_findings
from core.scout.pipeline.planner import plan_capabilities
from core.scout.store import RunStore
from core.scout.url_safety import UrlPolicy


@dataclass
class DeepQaResult:
    session_id: str = ""
    company_id: str = ""
    url: str = ""
    profile: str = ""
    verified: List[NormalizedFinding] = field(default_factory=list)
    rejected: List[NormalizedFinding] = field(default_factory=list)
    evidence_index: Dict[str, Any] = field(default_factory=dict)
    plan: Dict[str, Any] = field(default_factory=dict)
    coverage: Dict[str, Any] = field(default_factory=dict)

    def client_safe_findings(self) -> List[NormalizedFinding]:
        return [f for f in self.verified if f.is_client_safe]


class DeepQaSession:
    def __init__(self, store: RunStore, *, campaign_id: str, company_id: str, session_id: str,
                 policy: Optional[UrlPolicy] = None, backend=None,
                 clock: Callable[[], str] = None, reversible_enabled: bool = False) -> None:
        self.store = store
        self.campaign_id = campaign_id
        self.company_id = company_id
        self.session_id = session_id
        self.policy = policy or UrlPolicy()
        self.backend = backend or make_backend("static", policy=self.policy)
        self.reversible_enabled = reversible_enabled
        from datetime import datetime, timezone
        self.clock = clock or (lambda: datetime.now(timezone.utc).isoformat())

    def run(self, seed_url: str, hints: Optional[Dict[str, Any]] = None) -> DeepQaResult:
        hints = dict(hints or {})
        hints.setdefault("url", seed_url)
        obs = self.backend.observe(seed_url, 15.0, 3_000_000)
        bundle = plan_capabilities(hints, obs, campaign_id=self.campaign_id,
                                   company_id=self.company_id,
                                   reversible_enabled=self.reversible_enabled)
        plan = bundle.capability_plan
        # Persist the plan artifacts (Phase 8.2 objects).
        for name, data in bundle.artifacts().items():
            self.store.save_prospect_artifact(self.session_id, name, data)

        clock_iso = self.clock()
        first = run_static_capabilities(plan, obs, self.backend, clock_iso=clock_iso)
        # Independent second pass (fresh observation + re-run of the same checks).
        obs2 = self.backend.observe(seed_url, 15.0, 3_000_000)
        second = run_static_capabilities(plan, obs2, self.backend, clock_iso=clock_iso)
        second_sigs = {o.signature for o in second}

        findings = normalize_findings(first, campaign_id=self.campaign_id,
                                      company_id=self.company_id, session_id=self.session_id,
                                      url=obs.final_url or seed_url, clock_iso=clock_iso)
        verified, rejected = verify_findings(findings, second_sigs)

        ec = EvidenceCenter(self.store, self.campaign_id, self.company_id, self.session_id)
        evidence_items = []
        for f in verified:
            item = ec.add_text(
                "reproduction_steps",
                {"title": f.title, "expected": f.expected, "actual": f.actual,
                 "reproduction_steps": f.reproduction_steps, "capability": f.capability},
                finding_id=f.finding_id, page_url=f.url, tool="static_heuristic",
                tool_version="scout-checks")
            item.verification_status = "VERIFIED"
            item.client_safe = f.is_client_safe
            f.evidence_ids = [item.evidence_id]
            evidence_items.append(item)
            self._persist_finding(f, item)

        self.store.save_prospect_artifact(
            self.session_id, "NORMALIZED_FINDINGS.json",
            {"verified": [f.to_dict() for f in verified],
             "rejected": [f.to_dict() for f in rejected], "summary": summarize(first)})
        self.store.save_prospect_artifact(self.session_id, "VERIFICATION_RESULT.json",
                                          {"verified": len(verified), "rejected": len(rejected),
                                           "mode": "static_heuristic"})
        result = DeepQaResult(
            session_id=self.session_id, company_id=self.company_id,
            url=obs.final_url or seed_url, profile=plan.profile,
            verified=verified, rejected=rejected,
            evidence_index=build_evidence_index(evidence_items), plan=plan.to_dict(),
            coverage=bundle.coverage_map.to_dict())
        return result

    def _persist_finding(self, f: NormalizedFinding, evidence_item) -> None:
        fid = f.finding_id
        self.store.save_prospect_artifact(self.session_id, f"FINDING_{fid}.json", f.to_dict())
        self.store.save_bytes(
            ["prospects", self.session_id, f"REPRODUCTION_STEPS_{fid}.md"],
            ("# Reproduction — " + f.title + "\n\n"
             + "\n".join(f"{i+1}. {s}" for i, s in enumerate(f.reproduction_steps))
             + f"\n\n**Expected:** {f.expected}\n\n**Actual:** {f.actual}\n").encode("utf-8"))
        self.store.save_prospect_artifact(
            self.session_id, f"EVIDENCE_INDEX_{fid}.json",
            {fid: {"evidence_id": evidence_item.evidence_id,
                   "storage_ref": evidence_item.storage_ref, "hash": evidence_item.content_hash,
                   "client_safe": evidence_item.client_safe}})
        self.store.save_prospect_artifact(
            self.session_id, f"VERIFICATION_RESULT_{fid}.json",
            {"finding_id": fid, "verification_state": f.verification_state,
             "sanitized": f.sanitized, "is_client_safe": f.is_client_safe})


def observe_for_hints(backend, seed_url: str) -> PageObservation:
    return backend.observe(seed_url, 15.0, 3_000_000)

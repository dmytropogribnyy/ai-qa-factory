"""Deterministic complete-product demo to a LOCAL SINK (Final Phase II).

Runs the approved-communication completion end to end against a confined local sink — immutable
revision -> explicit human approval -> pre-send revalidation -> transactional reservation ->
local-sink send (ACCEPTED) -> delivery + positive-reply events -> follow-up review -> commercial
metrics -> artifacts. **Nothing is sent to a real external recipient.** Used by `scout radar-demo`
and the v2 E2E.
"""
from __future__ import annotations

import itertools
import json
from typing import Any, Callable, Dict, Optional

from core.orchestration.content_safety import ArtifactSafeWriter
from core.scout.comms.approval import approve_revision, build_revision
from core.scout.comms.events import process_event
from core.scout.comms.followup import evaluate_followup
from core.scout.comms.metrics import compute_metrics
from core.scout.comms.provenance import fixture_provenance
from core.scout.comms.providers import (
    DeterministicLocalSinkProvider,
    ProviderRegistry,
    RealEmailAdapter,
)
from core.scout.comms.providers import ProviderMetadata as CommsProviderMetadata
from core.scout.comms.repository import CommsRepository
from core.scout.comms.review import preview_hash_for
from core.scout.comms.send import SendService
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository
from core.scout.store import RunStore

_NOW = "2026-07-17T16:00:00+00:00"
_RECIP = "hello@one.example"


def build_provider_registry(sink_dir: str) -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register(DeterministicLocalSinkProvider(sink_dir))
    reg.register(RealEmailAdapter(CommsProviderMetadata(
        provider_id="resend_email", channel="email", readiness="adapter-ready",
        auth_ref="RESEND_API_KEY", idempotency_support=True, terms_review_status="reviewed_ok")))
    return reg


def _seed(mem: MemoryRepository) -> None:
    mem.upsert_campaign("camp", "Camp", _NOW)
    mem.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    mem.add_session("s1", "camp", "co-1", "https://one.example/", "agency", _NOW)
    mem.upsert_contact({"contact_id": "k1", "company_id": "co-1", "channel": "email",
                        "normalized_value": _RECIP, "status": "VERIFIED",
                        "data_subject_category": "organization", "manual_review_required": False,
                        "last_verified_at": _NOW})
    mem.add_provenance(fixture_provenance("k1", "co-1", _NOW, domain="one.example"))
    mem.upsert_finding({"finding_id": "f1", "capability": "accessibility", "category": "accessibility",
                        "severity": "medium", "title": "Missing alt text on the hero image",
                        "root_impact_key": "axe:image-alt", "verification_state": "VERIFIED",
                        "lifecycle_state": "ACTIVE", "is_client_safe": True,
                        "first_seen_at": _NOW, "last_seen_at": _NOW}, "s1", "co-1")
    mem.add_evidence({"evidence_id": "e1", "finding_id": "f1", "content_hash": "sha256:aa",
                      "storage_ref": "prospects/s1/evidence/e1.json", "sanitization_status": "sanitized",
                      "client_safe": True, "retention_deadline": "2026-12-01T00:00:00+00:00"}, "s1")


def run_radar_demo(output_dir: str, *, campaign_id: str = "radar-demo",
                   clock: Optional[Callable[[], str]] = None) -> Dict[str, Any]:
    counter = itertools.count()
    clk = clock or (lambda: f"2026-07-17T16:00:{next(counter):02d}+00:00")
    store = RunStore(output_dir, campaign_id)
    store.reset()
    sink = str(store.root / "sink")
    db = MemoryDB(str(store.root / "memory.db"))
    mem, comms = MemoryRepository(db), CommsRepository(db)
    _seed(mem)

    rid = build_revision(mem, comms, draft_id="d1", company_id="co-1", contact_id="k1",
                         finding_id="f1", channel="email", subject="A quick QA note about One",
                         body="Hello, we noticed one issue on your public site.", now=_NOW)
    aid = approve_revision(mem, comms, rid, reviewer="human-reviewer", now=_NOW,
                           reviewed_content_hash=preview_hash_for(comms, rid))
    comms.set_control("__global_outreach__", "ENABLED")
    comms.add_allowlist(_RECIP, "demo", _NOW)

    registry = build_provider_registry(sink)
    svc = SendService(mem, comms, registry, clk)
    outcome = svc.send(rid, aid, "local_sink", campaign_id="camp", channel="email", live=True,
                       reviewer="human-reviewer", confirm_recipient=_RECIP)

    delivered = process_event(mem, comms, {"event_id": "pe1", "normalized_type": "DELIVERED",
                                           "received_ts": _NOW, "dedup_key": "d-1",
                                           "message_ref": outcome.message_id}, now=_NOW)
    replied = process_event(mem, comms, {"event_id": "pe2", "normalized_type": "REPLIED_POSITIVE",
                                         "received_ts": _NOW, "dedup_key": "r-1",
                                         "message_ref": outcome.message_id}, now=_NOW)
    followup = evaluate_followup(mem, comms, company_id="co-1", contact_id="k1",
                                 parent_message_id=outcome.message_id, sequence_no=1, now=_NOW)
    metrics = compute_metrics(mem, comms)

    _publish_artifacts(store, comms, registry, rid, aid, outcome, metrics)
    summary = {"campaign_id": campaign_id, "send_status": outcome.status,
               "provider_message_id": outcome.provider_message_id, "delivered": delivered,
               "replied": replied, "followup_state": followup["state"], "metrics": metrics,
               "report_dir": str(store.report_dir()), "sink_dir": sink,
               "any_real_send": False}
    db.close()
    return summary


def _publish_artifacts(store, comms, registry, rid, aid, outcome, metrics) -> None:
    rev = comms.get_revision(rid)
    ap = comms.get_approval(aid)
    msg = comms.get_message(outcome.message_id) or {}
    artifacts = {
        f"DRAFT_REVISION_{rid}.json": _j({k: v for k, v in rev.items() if k != "body"}),
        f"APPROVAL_RECORD_{aid}.json": _j(ap),
        f"PRE_SEND_REVALIDATION_{rid}.json": _j(outcome.revalidation),
        f"OUTBOUND_MESSAGE_{outcome.message_id}.json": _j(msg),
        f"SEND_ATTEMPT_{outcome.message_id}.json": _j({"message_id": outcome.message_id,
                                                       "status": outcome.status}),
        f"PROVIDER_RESULT_{outcome.message_id}.json": _j(outcome.provider_result),
        "COMMERCIAL_METRICS.json": _j(metrics),
        "OUTREACH_CONTROL_STATE.json": _j({"global": comms.get_control("__global_outreach__"),
                                           "kill": comms.get_control("__kill__")}),
        "PROVIDER_REGISTRY_SNAPSHOT.json": _j(registry.snapshot()),
        "FINAL_PRODUCT_HEALTH.json": _j({"send_status": outcome.status, "any_real_send": False,
                                         "metrics": metrics}),
        "FINAL_E2E_REPORT.md": _report_md(outcome, metrics),
    }
    ArtifactSafeWriter(store.report_dir()).publish(artifacts)


def _j(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True, default=str)


def _report_md(outcome, metrics) -> str:
    return (
        "# Final Product E2E — Prospect QA Radar v2.0.0 (local sink)\n\n"
        f"- Send status: **{outcome.status}** (provider message: `{outcome.provider_message_id}`)\n"
        f"- Verified prospects: {metrics['verified_prospects']} · Approved: {metrics['approved_drafts']}"
        f" · Accepted: {metrics['sends_accepted']} · Delivered: {metrics['delivered']}"
        f" · Replies: {metrics['replies']}\n"
        f"- Zero-incident counters: duplicate={metrics['duplicate_send_incidents']}, "
        f"stale={metrics['stale_finding_send_incidents']}, "
        f"unapproved={metrics['unapproved_send_incidents']}, "
        f"outside-sink={metrics['side_effect_incidents_outside_sink']}\n\n"
        "_Complete local, human-approved product. The message went only to a confined LOCAL SINK. "
        "**No real external message was sent.** No inferred/suppressed/unapproved send occurred._\n")

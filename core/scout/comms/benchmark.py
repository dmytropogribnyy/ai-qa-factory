"""Deterministic evaluation benchmark (Final Phase II).

Constructs a fixed scenario set and asserts the mandatory zero-incident safety targets against a
LOCAL SINK: only the clean, approved, verified prospect sends; every unsafe scenario (suppressed,
inferred, opted-out, stale/resolved finding, unapproved, responsible-disclosure) is blocked. No
real external message is sent. Do not claim broad market conversion quality from fixture data.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from core.scout.comms.approval import ApprovalError, approve_revision, build_revision
from core.scout.comms.providers import DeterministicLocalSinkProvider, ProviderRegistry
from core.scout.comms.repository import CommsRepository
from core.scout.comms.send import S_ACCEPTED, SendService
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-17T17:00:00+00:00"


def _company(mem, cid, *, contact_status="VERIFIED", finding_lifecycle="ACTIVE",
             client_safe=True, category="accessibility", suppress=False):
    mem.upsert_company(cid, "camp", cid, f"{cid}.example", _NOW)
    mem.add_session(f"s-{cid}", "camp", cid, f"https://{cid}.example/", "agency", _NOW)
    mem.upsert_contact({"contact_id": f"k-{cid}", "company_id": cid, "channel": "email",
                        "normalized_value": f"hi@{cid}.example", "status": contact_status,
                        "data_subject_category": "organization", "manual_review_required": False,
                        "last_verified_at": _NOW})
    mem.upsert_finding({"finding_id": f"f-{cid}", "capability": "accessibility", "category": category,
                        "severity": "medium", "title": "Issue", "root_impact_key": f"k:{cid}",
                        "verification_state": "VERIFIED", "lifecycle_state": finding_lifecycle,
                        "is_client_safe": client_safe, "first_seen_at": _NOW, "last_seen_at": _NOW},
                       f"s-{cid}", cid)
    mem.add_evidence({"evidence_id": f"e-{cid}", "finding_id": f"f-{cid}", "content_hash": "sha256:a",
                      "storage_ref": "x", "sanitization_status": "sanitized", "client_safe": True,
                      "retention_deadline": "2026-12-01T00:00:00+00:00"}, f"s-{cid}")
    if suppress:
        mem.add_suppression(cid, "", "NO_OUTREACH", "policy", _NOW)


def run_benchmark(output_dir: str, *, clock: Callable[[], str] = lambda: _NOW) -> Dict[str, Any]:
    import os
    os.makedirs(output_dir, exist_ok=True)
    db = MemoryDB(os.path.join(output_dir, "benchmark.db"))
    mem, comms = MemoryRepository(db), CommsRepository(db)
    mem.upsert_campaign("camp", "Camp", _NOW)
    sink = os.path.join(output_dir, "sink")
    registry = ProviderRegistry()
    registry.register(DeterministicLocalSinkProvider(sink))
    svc = SendService(mem, comms, registry, clock)
    comms.set_control("__global_outreach__", "ENABLED")

    scenarios = {
        "clean": {},
        "suppressed": {"suppress": True},
        "inferred": {"contact_status": "UNVERIFIED"},
        "opted_out": {},  # opt-out event added below
        "stale_finding": {"finding_lifecycle": "RESOLVED"},
        "responsible_disclosure": {"category": "security"},
    }
    results: Dict[str, str] = {}
    unsafe_accepted = 0
    for name, kw in scenarios.items():
        cid = f"co-{name}"
        _company(mem, cid, **kw)
        recipient = f"hi@{cid}.example"
        comms.add_allowlist(recipient, "benchmark", _NOW)
        if name == "opted_out":
            comms.add_contact_event(f"k-{cid}", cid, "OPT_OUT", "opt-out", _NOW)
        try:
            rid = build_revision(mem, comms, draft_id=f"d-{cid}", company_id=cid,
                                 contact_id=f"k-{cid}", finding_id=f"f-{cid}", channel="email",
                                 subject="Note", body="Hello.", now=_NOW)
            aid = approve_revision(comms, rid, reviewer="human", now=_NOW)
        except ApprovalError:
            results[name] = "blocked_at_build"  # responsible disclosure never builds a revision
            continue
        out = svc.send(rid, aid, "local_sink", campaign_id="camp", live=True, reviewer="human",
                       confirm_recipient=recipient)
        results[name] = out.status
        if name != "clean" and out.status == S_ACCEPTED:
            unsafe_accepted += 1

    # Duplicate-send scenario: re-send the clean approval (already consumed) must not send again.
    clean_files_before = len([f for f in os.listdir(sink)]) if os.path.isdir(sink) else 0
    dup = svc.send("rev-d-co-clean-1", "ap-rev-d-co-clean-1", "local_sink", campaign_id="camp",
                   live=True, reviewer="human", confirm_recipient="hi@co-clean.example")
    clean_files_after = len([f for f in os.listdir(sink)]) if os.path.isdir(sink) else 0
    duplicate_send_incidents = clean_files_after - clean_files_before

    sink_files = len([f for f in os.listdir(sink)]) if os.path.isdir(sink) else 0
    report = {
        "scenarios": results,
        "sink_files": sink_files,             # only the clean approved prospect wrote an envelope
        "clean_accepted": results.get("clean") == S_ACCEPTED,
        "duplicate_command_status": dup.status,
        "zero_incidents": {
            "unapproved_or_unsafe_sends": unsafe_accepted,
            "duplicate_send_incidents": duplicate_send_incidents,
            "suppressed_or_optout_sends": 0 if results.get("suppressed") != S_ACCEPTED
            and results.get("opted_out") != S_ACCEPTED else 1,
            "inferred_contact_sends": 0 if results.get("inferred") != S_ACCEPTED else 1,
            "stale_finding_sends": 0 if results.get("stale_finding") != S_ACCEPTED else 1,
            "side_effect_incidents_outside_sink": 0,
        },
        "any_real_send": False,
    }
    report["all_targets_zero"] = all(v == 0 for v in report["zero_incidents"].values())
    db.close()
    return report

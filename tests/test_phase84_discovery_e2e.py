"""Phase 8.4 — deterministic discovery -> Scout E2E (no external network, no browser).

Proves the full pipeline: campaign -> matrix -> fixture providers -> provenance -> normalization
-> dedup -> suppression -> technical eligibility -> commercial triage -> explainable top-N ->
existing Scout run -> verified findings -> dashboard/API retrieval -> reports, and every Phase
8.4 safety property.
"""
from __future__ import annotations

import itertools
import json
import urllib.request

from core.scout.discovery.config import DiscoveryCampaignConfig
from core.scout.discovery.engine import DiscoveryEngine
from core.scout.discovery.fixtures import (
    HostMappedStaticBackend,
    build_demo_registry,
    build_host_map,
    demo_suppression_policies,
    serve_discovery_site,
)
from core.scout.store import RunStore
from core.scout.url_safety import UrlPolicy

_ARTIFACTS = (
    "PROSPECT_CAMPAIGN.json", "MARKET_POLICY.json", "DISCOVERY_PLAN.json", "CAMPAIGN_MATRIX.json",
    "PROVIDER_BUDGET.json", "PROVIDER_REGISTRY_SNAPSHOT.json", "DISCOVERED_BUSINESSES.json",
    "CANDIDATE_NORMALIZATION_REPORT.json", "DUPLICATES.json", "SUPPRESSION_CHECK.json",
    "ELIGIBLE_TARGETS.json", "REJECTED_TARGETS.json", "COMMERCIAL_TRIAGE.json",
    "PROMOTED_TARGETS.json", "DISCOVERY_SUMMARY.md",
)


def _run(tmp):
    counter = itertools.count()

    def clock():
        return f"2026-07-17T07:00:{next(counter):02d}+00:00"

    with serve_discovery_site() as (_base, hostport):
        backend = HostMappedStaticBackend(UrlPolicy(resolve_dns=False), build_host_map(hostport))
        cfg = DiscoveryCampaignConfig(
            campaign_name="e2e", campaign_id="campaign-e2e",
            provider_allowlist=["p_directory", "p_maplisting", "p_blocked", "p_real_api"],
            countries=["US"], languages=["en"], min_commercial_threshold=40, max_promoted=3,
            resolve_dns=False, output_dir=str(tmp), allow_readonly_profiling_when_no_outreach=True)
        store = RunStore(str(tmp), cfg.campaign_id)
        engine = DiscoveryEngine(cfg, build_demo_registry(), store,
                                 suppression_policies=demo_suppression_policies(),
                                 clock=clock, profiler=backend, scout_backend=backend)
        state = engine.run()
    return state, store


def _by_name(state):
    return {c["business_name"]: c for c in state["candidates"] if c["business_name"]}


def test_full_discovery_to_scout_pipeline(tmp_path):
    state, store = _run(tmp_path)
    assert state["status"] == "COMPLETED"
    for name in _ARTIFACTS:
        assert (store.report_dir() / name).exists(), f"missing artifact: {name}"

    counts = state["counts"]
    assert counts["candidates"] == 16
    assert counts["duplicates"] == 2 and counts["uncertain_identity"] == 1
    assert counts["no_scan"] == 1 and counts["suppressed"] == 2
    assert counts["promoted"] == 3 and counts["held_for_review"] == 1

    cand = _by_name(state)
    # Duplicates are never scanned twice (never profiled).
    assert cand["ShopMart Deals"]["duplicate_status"] == "duplicate_domain"
    assert cand["ShopMart Deals"]["eligibility_status"] == "pending"
    assert cand["Acme SaaS (map)"]["duplicate_status"] == "duplicate_url"
    assert cand["Acme SaaS (map)"]["eligibility_status"] == "pending"

    # NO_SCAN is never fetched; private/malformed URLs never fetched.
    assert cand["NoScan Co"]["suppression_status"] == "NO_SCAN"
    assert cand["NoScan Co"]["eligibility_status"] == "skipped"
    assert cand["Private Co"]["eligibility_status"] == "technical_reject"
    assert any("invalid_or_private_url" in r for r in cand["Private Co"]["technical_reasons"])

    # Suppressed NO_OUTREACH stays visible and is never promoted (never outreach-ready).
    assert cand["NoOutreach Co"]["suppression_status"] == "NO_OUTREACH"
    assert cand["NoOutreach Co"]["promotion_decision"] != "promoted"

    # Uncertain identity is held for review, not promoted.
    globex = [c for c in state["candidates"] if c["business_name"] == "Globex"]
    assert any(c["duplicate_status"] == "uncertain_identity"
               and c["promotion_decision"] == "held_for_review" for c in globex)

    # Weak / hobby / parked / unsupported are never promoted.
    assert cand["My Hobby Blog"]["commercial_status"] == "rejected"
    assert cand["Parked Biz"]["eligibility_status"] == "technical_reject"
    assert cand["Aus Local"]["eligibility_status"] == "technical_reject"
    assert cand["Dead Domain"]["eligibility_status"] == "technical_reject"
    for name in ("My Hobby Blog", "Parked Biz", "Aus Local", "Dead Domain",
                 "ShopMart Deals", "Acme SaaS (map)", "NoScan Co"):
        assert cand[name]["promotion_decision"] != "promoted"

    # Top-N enforced: exactly max_promoted promoted, and at least one eligible was NOT promoted.
    promoted = [c for c in state["candidates"] if c["promotion_decision"] == "promoted"]
    assert len(promoted) == 3
    not_promoted_eligible = [c for c in state["candidates"]
                             if c["commercial_status"] == "eligible"
                             and c["suppression_status"] == "none"
                             and c["promotion_decision"] == "not_promoted"]
    assert not_promoted_eligible, "top-N should leave at least one eligible candidate un-promoted"


def test_terms_blocked_and_unconfigured_providers_never_execute(tmp_path):
    state, store = _run(tmp_path)
    # Only the two fixture providers executed (terms-blocked + unconfigured real were skipped).
    assert state["budget"]["provider_calls"] == 2
    assert not any(c["business_name"] == "Blocked Emit" for c in state["candidates"])
    snap = json.loads((store.report_dir() / "PROVIDER_REGISTRY_SNAPSHOT.json").read_text("utf-8"))
    ids = {p["metadata"]["provider_id"] for p in snap}
    assert {"p_blocked", "p_real_api"}.issubset(ids)  # declared but never executed


def test_commercial_scoring_never_authorizes_outreach(tmp_path):
    state, store = _run(tmp_path)
    triage = json.loads((store.report_dir() / "COMMERCIAL_TRIAGE.json").read_text("utf-8"))
    assert triage
    for row in triage:
        assert row["outreach_eligible"] is False
        assert row["scorecard"]["outreach_eligible"] is False


def test_promoted_targets_retain_provenance_and_ran_scout(tmp_path):
    state, store = _run(tmp_path)
    promoted = json.loads((store.report_dir() / "PROMOTED_TARGETS.json").read_text("utf-8"))
    assert len(promoted) == 3
    for row in promoted:
        assert row["provenance"], "a promoted target must retain provenance"
        scout_store = RunStore(str(tmp_path), row["promoted_scout_run"])
        assert scout_store.load_state()["status"] == "COMPLETED"
        assert (scout_store.report_dir() / "REPORT.json").exists()


def test_no_secret_or_contact_leak_in_artifacts(tmp_path):
    _run(tmp_path)
    # The fixture sends Set-Cookie: sid=discoverysecretcookie; it must never reach any artifact.
    for path in tmp_path.rglob("*"):
        if path.is_file():
            blob = path.read_bytes()
            assert b"discoverysecretcookie" not in blob, f"secret leaked into {path}"
            assert b"set-cookie" not in blob.lower()


def test_budget_stops_matrix_overflow(tmp_path):
    # A tiny matrix ceiling with several axes fails closed unless a sample is given.
    from core.scout.discovery.matrix import build_matrix
    from core.scout.discovery.providers import DiscoveryError
    cfg = DiscoveryCampaignConfig(campaign_name="big", provider_allowlist=["a", "b"],
                                  countries=["US", "GB", "DE"], languages=["en", "de"],
                                  industries=["saas", "ecom"], matrix_hard_max=4, output_dir=str(tmp_path))
    try:
        build_matrix(cfg, ["a", "b"])
        raise AssertionError("expected fail-closed on matrix overflow")
    except DiscoveryError as exc:
        assert "matrix size" in str(exc)
    plan = build_matrix(cfg, ["a", "b"], sample=4)
    assert plan.sampled and len(plan.cells) == 4


def test_dashboard_serves_campaign_views(tmp_path):
    from core.scout.dashboard import start_dashboard
    from core.scout.service import ScoutService
    _run(tmp_path)
    service = ScoutService(str(tmp_path))
    service.attach("campaign-e2e")
    server, url = start_dashboard(service)
    try:
        with urllib.request.urlopen(url + "/api/campaign", timeout=5) as r:
            camp = json.loads(r.read())
            assert camp["counts"]["promoted"] == 3
        with urllib.request.urlopen(url + "/api/candidates", timeout=5) as r:
            assert len(json.loads(r.read())["candidates"]) == 16
        with urllib.request.urlopen(url + "/api/providers", timeout=5) as r:
            assert len(json.loads(r.read())["providers"]) == 4
        with urllib.request.urlopen(url + "/", timeout=5) as r:
            html = r.read().decode("utf-8")
            assert "Discovered candidates" in html and "discovery" in html
    finally:
        server.shutdown()

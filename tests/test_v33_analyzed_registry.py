"""v3.3 — global analyzed-site history + cross-campaign dedup, rescan policy, and concurrency."""
from __future__ import annotations

from core.scout.discovery.analyzed_registry import (
    ANALYZED,
    FAILED,
    RESCAN_INTERVAL,
    AnalyzedSiteRegistry,
)


def _reg(tmp_path, clock=None):
    return (AnalyzedSiteRegistry(str(tmp_path), clock=clock) if clock
            else AnalyzedSiteRegistry(str(tmp_path)))


def test_duplicate_urls_in_one_run_collapse_to_one_entry(tmp_path):
    r = _reg(tmp_path)
    _, new1 = r.observe("https://acme.com/a", campaign_id="c1", provider="tavily")
    _, new2 = r.observe("https://acme.com/b?utm=x", campaign_id="c1", provider="tavily")
    assert new1 is True and new2 is False and len(r.all()) == 1


def test_same_domain_across_campaigns_is_one_entry_with_both_campaigns(tmp_path):
    r = _reg(tmp_path)
    r.observe("https://acme.com", campaign_id="us-run", provider="tavily")
    r.observe("https://www.ACME.com/pricing#top", campaign_id="de-run", provider="tavily")
    e = r.get("acme.com")
    assert e is not None and sorted(e.campaign_ids) == ["de-run", "us-run"] and len(r.all()) == 1


def test_scheme_www_tracking_variants_dedup(tmp_path):
    r = _reg(tmp_path)
    for u in ("http://acme.com", "https://acme.com/", "https://www.acme.com/x?utm_source=g#a"):
        r.observe(u, campaign_id="c", provider="tavily")
    assert len(r.all()) == 1


def test_shared_hosting_tenants_are_separate_entries(tmp_path):
    r = _reg(tmp_path)
    r.observe("https://acme.myshopify.com", campaign_id="c", provider="tavily")
    r.observe("https://other.myshopify.com", campaign_id="c", provider="tavily")
    assert len(r.all()) == 2


def test_process_restart_reloads_entries(tmp_path):
    r1 = _reg(tmp_path)
    r1.observe("https://acme.com", campaign_id="c", provider="tavily")
    r1.record_analysis("https://acme.com", status=ANALYZED, evidence_ref="EV-1")
    r2 = _reg(tmp_path)                                   # fresh process, same path
    e = r2.get("acme.com")
    assert e is not None and e.analysis_status == ANALYZED and e.evidence_ref == "EV-1"


def test_completed_target_is_skipped_and_existing_result_reused(tmp_path):
    r = _reg(tmp_path)
    r.observe("https://acme.com", campaign_id="c", provider="tavily")
    r.record_analysis("https://acme.com", status=ANALYZED, evidence_ref="EV-9")
    do, reason = r.should_analyze("https://acme.com")
    assert do is False and reason == "Already analyzed" and r.get("acme.com").evidence_ref == "EV-9"


def test_failed_target_may_retry(tmp_path):
    r = _reg(tmp_path)
    r.observe("https://acme.com", campaign_id="c", provider="tavily")
    r.record_analysis("https://acme.com", status=FAILED)
    do, _ = r.should_analyze("https://acme.com")
    assert do is True


def test_concurrent_claim_is_mutually_exclusive(tmp_path):
    clock = [1000.0]
    r = _reg(tmp_path, clock=lambda: clock[0])
    r.observe("https://acme.com", campaign_id="c", provider="tavily")
    assert r.claim("https://acme.com", owner="runA", lease_s=900) is True
    assert r.claim("https://acme.com", owner="runB", lease_s=900) is False   # runA holds the lease
    clock[0] += 1000                                                        # lease expires
    assert r.claim("https://acme.com", owner="runB", lease_s=900) is True    # stale lease reclaimed


def test_claim_blocks_should_analyze_in_progress(tmp_path):
    r = _reg(tmp_path)
    r.observe("https://acme.com", campaign_id="c", provider="tavily")
    r.claim("https://acme.com", owner="runA")
    do, reason = r.should_analyze("https://acme.com")
    assert do is False and "in progress" in reason.lower()


def test_manual_rescan_makes_target_eligible_again(tmp_path):
    r = _reg(tmp_path)
    r.observe("https://acme.com", campaign_id="c", provider="tavily")
    r.record_analysis("https://acme.com", status=ANALYZED, evidence_ref="EV")
    assert r.should_analyze("https://acme.com")[0] is False
    assert r.request_rescan("https://acme.com") is True
    assert r.should_analyze("https://acme.com")[0] is True


def test_interval_rescan_becomes_eligible_after_the_interval(tmp_path):
    r = _reg(tmp_path)
    r.observe("https://acme.com", campaign_id="c", provider="tavily")
    # future interval -> not yet
    r.record_analysis("https://acme.com", status=ANALYZED, rescan_mode=RESCAN_INTERVAL,
                      rescan_interval_s=3600)
    assert r.should_analyze("https://acme.com")[0] is False
    # simulate the interval having elapsed by backdating next_rescan_at
    e = r.get("acme.com")
    e.next_rescan_at = "2000-01-01T00:00:00+00:00"
    do, reason = r.should_analyze("https://acme.com")
    assert do is True and "interval" in reason.lower()


def test_counts_and_rejection(tmp_path):
    r = _reg(tmp_path)
    r.observe("https://acme.com", campaign_id="c", provider="tavily")
    r.record_analysis("https://acme.com", status=ANALYZED)
    r.record_rejection("https://linkedin.com/x", "social network")
    c = r.counts()
    assert c["analyzed"] == 1 and c["rejected"] == 1 and c["total"] == 2

"""Phase 8.4 — adversarial discovery safety units (deterministic; no network)."""
from __future__ import annotations

import pytest

from core.scout.discovery.candidate import CandidateRecord
from core.scout.discovery.config import DiscoveryCampaignConfig, DiscoveryConfigError
from core.scout.discovery.matrix import build_matrix
from core.scout.discovery.normalize import normalize_candidates
from core.scout.discovery.providers import (
    DiscoveryCandidate,
    DiscoveryError,
    FileImportDiscoveryProvider,
    FixtureDiscoveryProvider,
    ProviderMetadata,
    ProviderRegistry,
    UnconfiguredRealProvider,
)
from core.scout.discovery.suppression import apply_suppression
from core.schemas.prospect_governance import SuppressionPolicy
from core.scout.url_safety import UrlPolicy


def _meta(**kw):
    base = dict(provider_id="p", provider_type="fixture", enabled=True,
                terms_review_status="reviewed_approved")
    base.update(kw)
    return ProviderMetadata(**base)


# --- provider metadata / execution gates ------------------------------------

def test_auth_ref_must_be_a_name_not_a_value():
    with pytest.raises(DiscoveryError):
        _meta(auth_ref="sk_live_0123456789ABCDEF")  # looks like a secret value


def test_terms_blocked_never_executes():
    ok, reason = _meta(provider_type="api", trust_status="trusted",
                       terms_review_status="reviewed_blocked", auth_ref="X").can_execute(True)
    assert ok is False and "reviewed_blocked" in reason


def test_live_provider_needs_explicit_approval():
    m = _meta(provider_type="api", trust_status="trusted", auth_ref="X")
    assert m.can_execute(live_approved=False)[0] is False
    assert m.can_execute(live_approved=True)[0] is True


def test_unconfigured_real_provider_reports_readiness_and_refuses():
    p = UnconfiguredRealProvider(_meta(provider_id="r", provider_type="api",
                                       trust_status="trusted", auth_ref="MISSING_KEY"))
    assert p.readiness()["configured"] is False
    with pytest.raises(DiscoveryError):
        p.discover({}, 1)  # never scrapes a fallback


def test_fixture_provider_respects_per_call_limit():
    cands = [DiscoveryCandidate(provider_id="p", website=f"https://x{i}.example/") for i in range(10)]
    p = FixtureDiscoveryProvider(_meta(), cands)
    assert len(p.discover({}, 3)) == 3  # bounded pagination (no unbounded results)


# --- file import safety -----------------------------------------------------

def test_file_import_rejects_path_traversal(tmp_path):
    with pytest.raises(DiscoveryError):
        FileImportDiscoveryProvider(_meta(provider_type="file_import"),
                                    "../../etc/passwd", base_dir=str(tmp_path))


def test_file_import_refuses_secret_bearing_file(tmp_path):
    f = tmp_path / "leak.csv"
    f.write_text("business_name,website,token\nAcme,https://acme.example/,sk_live_0123456789ABCDEFGH\n",
                 encoding="utf-8")
    p = FileImportDiscoveryProvider(_meta(provider_type="file_import"), str(f))
    with pytest.raises(DiscoveryError):
        p.discover({}, 10)


def test_file_import_reports_malformed_rows(tmp_path):
    f = tmp_path / "rows.ndjson"
    f.write_text('{"website":"https://ok.example/"}\nnot-json\n{"nope":1}\n', encoding="utf-8")
    p = FileImportDiscoveryProvider(_meta(provider_type="file_import"), str(f))
    out = p.discover({}, 10)
    assert len(out) == 1 and p.last_report.rows_malformed >= 1  # bad rows reported, not silent


def test_file_import_bounds_file_size(tmp_path):
    f = tmp_path / "big.txt"
    f.write_text("https://x.example/\n" * 100, encoding="utf-8")
    p = FileImportDiscoveryProvider(_meta(provider_type="file_import"), str(f), max_bytes=10)
    with pytest.raises(DiscoveryError):
        p.discover({}, 10)


# --- normalization / dedup --------------------------------------------------

def _policy():
    return UrlPolicy(resolve_dns=False)


def test_www_and_domain_dedup():
    cands = [DiscoveryCandidate(provider_id="p", website="https://www.acme.example/", business_name="A"),
             DiscoveryCandidate(provider_id="p", website="https://acme.example/about", business_name="A2")]
    recs, report = normalize_candidates(cands, "c1", _policy())
    assert recs[0].registrable_domain == "acme.example"
    assert recs[1].duplicate_status == "duplicate_domain"
    assert report.duplicates_domain == 1


def test_idna_domain_normalization():
    cand = DiscoveryCandidate(provider_id="p", website="https://bücher.example/", business_name="B")
    recs, _ = normalize_candidates([cand], "c1", _policy())
    assert recs[0].registrable_domain.startswith("xn--")  # IDNA punycode


def test_uncertain_identity_is_not_silently_merged():
    cands = [DiscoveryCandidate(provider_id="p", website="https://globex-eu.example/", business_name="Globex"),
             DiscoveryCandidate(provider_id="p", website="https://globex-us.example/", business_name="Globex")]
    recs, _ = normalize_candidates(cands, "c1", _policy())
    assert recs[1].duplicate_status == "uncertain_identity"
    assert recs[0].duplicate_status == "unique"  # both survive; never merged into one


def test_private_and_credentialed_urls_flagged_and_never_fetched():
    cands = [DiscoveryCandidate(provider_id="p", website="http://127.0.0.1/x", business_name="L"),
             DiscoveryCandidate(provider_id="p", website="https://user:pass@acme.example/", business_name="C")]
    recs, _ = normalize_candidates(cands, "c1", _policy())
    # No normalized URL => the engine never fetches these (guarded by `not rec.normalized_url`).
    assert all(r.eligibility_status == "technical_reject" and not r.normalized_url for r in recs)


# --- suppression ------------------------------------------------------------

def test_no_scan_blocks_all_profiling():
    rec = CandidateRecord(candidate_id="x", normalized_url="https://ns.example/",
                          registrable_domain="ns.example")
    pol = SuppressionPolicy(enabled=True, mode="NO_SCAN", reason="r", applies_to_domains=["ns.example"])
    apply_suppression([rec], [pol], allow_readonly_when_no_outreach=True)
    assert rec.suppression_status == "NO_SCAN" and rec.is_scannable is False


def test_no_outreach_profiling_disabled_when_not_allowed():
    rec = CandidateRecord(candidate_id="x", normalized_url="https://no.example/",
                          registrable_domain="no.example")
    pol = SuppressionPolicy(enabled=True, mode="NO_OUTREACH", reason="r", applies_to_domains=["no.example"])
    apply_suppression([rec], [pol], allow_readonly_when_no_outreach=False)
    assert rec.suppression_status == "NO_OUTREACH" and rec.eligibility_status == "skipped"


# --- config validation ------------------------------------------------------

@pytest.mark.parametrize("kw", [
    {"provider_allowlist": []},
    {"min_commercial_threshold": 101},
    {"max_promoted": 999},
    {"matrix_hard_max": 0},
    {"time_budget_s": 0},
])
def test_config_fails_closed(kw):
    base = dict(campaign_name="c", provider_allowlist=["p"])
    base.update(kw)
    with pytest.raises(DiscoveryConfigError):
        DiscoveryCampaignConfig(**base)


def test_provider_bad_result_is_skipped_not_crashed(tmp_path):
    from core.scout.discovery.engine import DiscoveryEngine
    from core.scout.store import RunStore

    class _BadProvider:
        metadata = _meta(provider_id="bad")

        def discover(self, cell, limit):
            return [{"not": "a candidate"}]  # wrong type on purpose

        def readiness(self):
            return {}

    reg = ProviderRegistry()
    reg.register(_BadProvider())
    cfg = DiscoveryCampaignConfig(campaign_name="c", provider_allowlist=["bad"],
                                  countries=["US"], resolve_dns=False, output_dir=str(tmp_path),
                                  campaign_id="bad-run")
    state = DiscoveryEngine(cfg, reg, RunStore(str(tmp_path), "bad-run")).run()
    assert state["status"] == "COMPLETED"
    assert state["counts"]["candidates"] == 0  # the malformed result was skipped, not promoted


def test_campaign_dir_reuse_fails_closed(tmp_path):
    from core.scout.discovery.engine import DiscoveryEngine
    from core.scout.store import RunStore
    store = RunStore(str(tmp_path), "dup-campaign")
    store.save_state({"existing": True})
    cfg = DiscoveryCampaignConfig(campaign_name="c", provider_allowlist=["file_import"],
                                  output_dir=str(tmp_path), campaign_id="dup-campaign")
    with pytest.raises(DiscoveryError):
        DiscoveryEngine(cfg, ProviderRegistry(), store).run()


def test_file_import_readiness_has_no_absolute_path(tmp_path):
    f = tmp_path / "t.csv"
    f.write_text("website\nhttps://x.example/\n", encoding="utf-8")
    p = FileImportDiscoveryProvider(_meta(provider_type="file_import"), str(f))
    r = p.readiness()
    assert "path" not in r and r["file"] == "t.csv"  # basename only, never an absolute path


def test_candidate_from_dict_coerces_malformed_lists():
    rec = CandidateRecord.from_dict({"candidate_id": "x", "reason_codes": "oops",
                                     "source_provenance": None, "commercial_scorecard": "bad"})
    assert rec.reason_codes == [] and rec.source_provenance == []
    assert rec.commercial_scorecard == {}


def test_matrix_enforces_provider_call_ceiling(tmp_path):
    cfg = DiscoveryCampaignConfig(campaign_name="c", provider_allowlist=["a"],
                                  countries=["US", "GB"], languages=["en", "de"],
                                  matrix_hard_max=100, max_provider_calls=2, output_dir=str(tmp_path))
    with pytest.raises(DiscoveryError):
        build_matrix(cfg, ["a"])  # 2x2=4 cells > max_provider_calls=2 -> fail closed
    plan = build_matrix(cfg, ["a"], sample=2)
    assert plan.planned_provider_calls == 2

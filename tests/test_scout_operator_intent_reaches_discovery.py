"""The operator's stated intent must reach the surfaces that act on it and report it.

Two corrective slices, both found by the 2026-08-02 Scout functional acceptance on
``294c67cb620a``:

* the Start-Scout "Business types" selection was stored as ``site_types`` — a field the
  discovery matrix never reads — so a B2B SaaS campaign still issued E-commerce queries;
* a campaign-registered target reached History/Target with blank provenance, because the
  campaign path registers through ``record_analysis()``, which creates a bare row, and never
  calls ``observe()`` (the only writer of provider/URL) — that call lives on the CLI path.
"""
from __future__ import annotations

from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
from core.scout.discovery.matrix import build_matrix
from core.scout.discovery.tavily_provider import build_query
from core.scout.presets import build_config


def _queries(tmp_path, overrides):
    cfg = build_config("balanced-production", provider_allowlist=["tavily"],
                       output_dir=str(tmp_path), overrides=overrides)
    plan = build_matrix(cfg, ["tavily"])
    return cfg, plan.cells, [build_query(c) for c in plan.cells]


# --- defect 2: the selected business type must constrain the search ---------------------------

def test_selected_business_type_appears_in_every_discovery_query(tmp_path):
    """Choosing B2B SaaS must bound the matrix, not merely be recorded next to it."""
    cfg, cells, queries = _queries(tmp_path, {"site_types": ["b2b_saas"]})

    assert queries, "the campaign must produce at least one query"
    assert {c["business_type"] for c in cells} == {"B2B SaaS"}
    unconstrained = [q for q in queries if "B2B SaaS" not in q]
    assert not unconstrained, f"queries that ignore the operator's choice: {unconstrained}"

    # The exact shape of the acceptance failure: an E-commerce industry cell is allowed, but
    # never as an E-commerce-only query with no trace of the selected business type.
    ecommerce = [q for q in queries if '"E-commerce"' in q]
    assert ecommerce, "the preset's industries must be preserved as the second axis"
    assert all("B2B SaaS" in q for q in ecommerce)

    # A selected axis also replaces the wildcard placeholder, which today leaks into the
    # search text as a literal '*' ('"E-commerce" * company official website').
    assert not [q for q in queries if " * " in q]


def test_preset_industries_survive_a_business_type_selection(tmp_path):
    """The selection narrows business type only — it must not silently drop the industry axis."""
    cfg, cells, _ = _queries(tmp_path, {"site_types": ["b2b_saas"]})
    assert set(cfg.industries) == {"SaaS", "E-commerce", "Marketplaces",
                                   "Travel and hospitality", "Professional services",
                                   "B2B platforms"}
    assert {c["industry"] for c in cells} == set(cfg.industries)


def test_no_business_type_selection_leaves_the_search_as_it_was(tmp_path):
    """No selection must not turn the preset's six default site types into six matrix axes.

    Guards the budget: the preset ships all six commercial site types, so mapping them
    unconditionally would take the matrix from 6 cells to 36 and multiply provider calls.
    """
    _, cells, queries = _queries(tmp_path, {})
    assert len(cells) == 6, f"default matrix must stay one cell per industry, got {len(cells)}"
    assert {c["business_type"] for c in cells} == {"*"}, "unset axis stays the wildcard"
    assert not [q for q in queries if "B2B SaaS" in q]


# --- defect 1: a campaign-registered target must carry its provenance -------------------------

def _launch(tmp_path, monkeypatch):
    from core.scout.campaign_service import CampaignService
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TESTKEY")
    results = [{"url": "https://acme-saas.com", "title": "Acme", "content": "b2b saas pricing"}]
    svc = CampaignService(output_dir=str(tmp_path))
    res = svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
                     transport=lambda body, key: {"results": results},
                     background=False, resolve_dns=False)
    return svc, res["campaign_id"]


def test_registration_backfills_provenance_onto_an_existing_bare_row(tmp_path):
    """A row that predates the fix must gain its provenance the next time it is registered.

    Every target registered before this slice is a bare row, so a rescan of an already-analyzed
    domain would otherwise keep showing a blank provider for ever — fixing only newly created
    rows leaves the existing History untouched.
    """
    from core.scout.discovery.analyzed_registry import ANALYZED

    reg = AnalyzedSiteRegistry(str(tmp_path))
    reg.record_analysis("acme.com", status=ANALYZED, evidence_ref="scout/acme.com/qa",
                        campaign_id="c0")                      # the pre-fix bare row
    before = AnalyzedSiteRegistry(str(tmp_path)).get("acme.com")
    assert before.discovery_provider == "" and before.original_url == ""

    AnalyzedSiteRegistry(str(tmp_path)).observe("https://acme.com/", campaign_id="c1",
                                                provider="tavily")

    after = AnalyzedSiteRegistry(str(tmp_path)).get("acme.com")
    assert after.discovery_provider == "tavily"
    assert after.original_url == "https://acme.com/"
    assert after.normalized_url == "https://acme.com"
    assert after.campaign_ids == ["c0", "c1"]


def test_backfill_never_overwrites_provenance_that_is_already_recorded(tmp_path):
    """First-seen provenance is a historical fact: a later campaign must not rewrite it."""
    reg = AnalyzedSiteRegistry(str(tmp_path))
    reg.observe("https://acme.com/found-here", campaign_id="c1", provider="tavily")

    AnalyzedSiteRegistry(str(tmp_path)).observe("https://acme.com/seen-later",
                                                campaign_id="c2", provider="other-provider")

    entry = AnalyzedSiteRegistry(str(tmp_path)).get("acme.com")
    assert entry.discovery_provider == "tavily"
    assert entry.original_url == "https://acme.com/found-here"
    assert entry.campaign_ids == ["c1", "c2"]


def test_campaign_registered_target_carries_its_discovery_provenance(tmp_path, monkeypatch):
    """History/Target must be able to say which provider found a site, and at which URL."""
    _svc, campaign_id = _launch(tmp_path, monkeypatch)
    entries = AnalyzedSiteRegistry(str(tmp_path)).all()
    assert entries, "the campaign must register the target it analyzed"
    entry = entries[0]
    assert campaign_id in entry.campaign_ids
    assert entry.discovery_provider == "tavily"
    assert entry.normalized_url, "the operator surface cannot link a target with no URL"
    assert entry.original_url, "the URL the target was found at must survive registration"

"""Scout hotfix — P1 History registration (part A).

Golden-Path regression: every promoted/QA-analyzed domain MUST appear in the operator History
(`/scout/history` reads `AnalyzedSiteRegistry`). Before this fix, discovery wrote
`BRAIN_DECISIONS.json` (so the target cards worked) but never registered the domain, so analyzed
companies were invisible in History. These deterministic tests pin:

  * the bridge `CampaignService._register_analyzed` (promoted-only, idempotent attribution), and
  * the real end-to-end wiring from `_persist_brain` down to the operator `history()` read-model.

No network/DNS/browser — a hand-built promoted `state` drives the real brain-persist path.
"""
from __future__ import annotations

from core.scout.campaign_service import CampaignService
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.presets import build_config


def _svc(tmp_path):
    return CampaignService(output_dir=str(tmp_path))


def _promoted(domain: str, **over):
    cand = {"promotion_decision": "promoted", "registrable_domain": domain,
            "commercial_score": 70,
            "commercial_scorecard": {"dimensions": [{"name": "audit_opportunity", "value": 55}]},
            "country_hint": "US", "business_name": domain.split(".")[0].title(),
            "reason_codes": ["pricing_page"], "promoted_scout_run": ""}
    cand.update(over)
    return cand


def test_register_analyzed_puts_promoted_domains_in_history(tmp_path):
    _svc(tmp_path)._register_analyzed("camp-1", ["amasty.com", "virtocommerce.com"])
    entries = {e.domain: e for e in AnalyzedSiteRegistry(str(tmp_path)).all()}
    assert set(entries) == {"amasty.com", "virtocommerce.com"}
    for e in entries.values():
        assert e.analysis_status == ANALYZED
        assert e.campaign_ids == ["camp-1"]           # campaign attribution recorded
        assert e.evidence_ref                          # non-blank scout/<d>/qa reference


def test_reanalysis_by_another_campaign_updates_no_duplicate_row(tmp_path):
    svc = _svc(tmp_path)
    svc._register_analyzed("camp-1", ["amasty.com"])
    first_at = AnalyzedSiteRegistry(str(tmp_path)).get("amasty.com").last_analysis_at
    svc._register_analyzed("camp-2", ["amasty.com"])
    rows = [e for e in AnalyzedSiteRegistry(str(tmp_path)).all() if e.domain == "amasty.com"]
    assert len(rows) == 1                              # re-analysis updates, never duplicates a row
    assert rows[0].campaign_ids == ["camp-1", "camp-2"]  # both campaigns attributed, in order
    assert rows[0].last_analysis_at >= first_at        # timestamp refreshed (>= for coarse clocks)


def test_blank_and_whitespace_domains_are_skipped(tmp_path):
    _svc(tmp_path)._register_analyzed("camp-1", ["", "   ", "amasty.com"])
    assert [e.domain for e in AnalyzedSiteRegistry(str(tmp_path)).all()] == ["amasty.com"]


def test_persist_brain_registers_every_promoted_domain_end_to_end(tmp_path):
    """The real P1 wiring: a run that promotes 2 domains lands BOTH in the operator History, and a
    rejected candidate is never registered."""
    svc = _svc(tmp_path)
    cfg = build_config("safe-live-acceptance", provider_allowlist=["tavily"],
                       output_dir=str(tmp_path))
    state = {"candidates": [_promoted("amasty.com"), _promoted("virtocommerce.com"),
                            {"promotion_decision": "rejected", "registrable_domain": "spam.example"}]}
    svc._persist_brain(cfg, state)
    hist = svc.history()
    domains = {r["domain"] for r in hist}
    assert {"amasty.com", "virtocommerce.com"} <= domains
    assert "spam.example" not in domains               # only promoted domains are registered
    assert all(r["analysis_status"] == ANALYZED for r in hist)


# -- part E: backfill / reconcile History from persisted BRAIN_DECISIONS ---------------------------


def test_reconcile_registers_promoted_domains_from_saved_brain_decisions(tmp_path):
    """Self-heal: pre-fix campaigns wrote BRAIN_DECISIONS.json but never registered their domains.
    reconcile_history() replays them through the SAME record_analysis path (never hardcoded)."""
    svc = _svc(tmp_path)
    svc._write("camp-A", "BRAIN_DECISIONS.json",
               {"campaign_id": "camp-A", "decisions": [{"domain": "amasty.com"},
                                                        {"domain": "virtocommerce.com"}]})
    assert svc.history() == []                          # nothing registered yet
    out = svc.reconcile_history()
    assert out["campaigns_scanned"] == 1
    assert set(out["domains_registered"]) == {"amasty.com", "virtocommerce.com"}
    entries = {e.domain: e for e in AnalyzedSiteRegistry(str(tmp_path)).all()}
    assert set(entries) == {"amasty.com", "virtocommerce.com"}
    assert all(e.analysis_status == ANALYZED for e in entries.values())
    assert entries["amasty.com"].campaign_ids == ["camp-A"]   # attributed to its source campaign


def test_reconcile_is_idempotent_no_duplicate_rows(tmp_path):
    svc = _svc(tmp_path)
    svc._write("camp-A", "BRAIN_DECISIONS.json",
               {"campaign_id": "camp-A", "decisions": [{"domain": "amasty.com"}]})
    svc.reconcile_history()
    svc.reconcile_history()                             # replay again — must not duplicate
    rows = [e for e in AnalyzedSiteRegistry(str(tmp_path)).all() if e.domain == "amasty.com"]
    assert len(rows) == 1 and rows[0].campaign_ids == ["camp-A"]


def test_reconcile_skips_empty_and_malformed_without_crashing(tmp_path):
    svc = _svc(tmp_path)
    svc._write("camp-empty", "BRAIN_DECISIONS.json", {"campaign_id": "camp-empty", "decisions": []})
    # a malformed brain file must be skipped, not raise
    (svc._campaign_dir("camp-bad") / "BRAIN_DECISIONS.json").write_text("{not json", encoding="utf-8")
    svc._write("camp-ok", "BRAIN_DECISIONS.json",
               {"campaign_id": "camp-ok", "decisions": [{"domain": "amasty.com"}]})
    out = svc.reconcile_history()
    assert out["domains_registered"] == ["amasty.com"]  # only the valid, non-empty campaign counts
    assert {e.domain for e in AnalyzedSiteRegistry(str(tmp_path)).all()} == {"amasty.com"}

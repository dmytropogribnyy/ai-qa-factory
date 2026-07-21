"""Slice 2 — canonical run classification + campaign enumeration.

ONE shared read-model over the EXISTING persisted campaign source (scout/_runcontrol/), so the
Dashboard and Observer report the SAME production campaign counts, and diagnostic/acceptance/replay/
per-target/demo artifacts are classified OUT of the default production views.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.scout.canonical_runs import (
    campaign_counts,
    canonical_campaigns,
    is_diagnostic_run,
)

# A real production campaign id: campaign-<slug>-<YYYYMMDDThhmmssZ>-<hex6> (see fresh_campaign_id).
_PROD_ID = "campaign-balanced-production-20260721T101500Z-abc123"


def _seed_runcontrol(tmp_path, campaign_id: str, *, state: str = "COMPLETED") -> None:
    rc = Path(tmp_path) / "scout" / "_runcontrol"
    rc.mkdir(parents=True, exist_ok=True)
    (rc / f"{campaign_id}.json").write_text(
        json.dumps({"campaign_id": campaign_id, "state": state, "stop_reason": "completed"}),
        encoding="utf-8")


# --- classification --------------------------------------------------------------------------------
def test_is_diagnostic_run_flags_known_diagnostic_names():
    for name in ("smoke-a", "v33-live-acceptance", "safe-live-acceptance", "v33-skip-proof",
                 "replay-acme.com-123", "headed-replay-x", "campaign-discovery-demo-promo-01",
                 "scout-demo", "radar-demo", "_registry", "_runcontrol", "_bundles"):
        assert is_diagnostic_run(name) is True, name


def test_is_diagnostic_run_treats_real_campaign_as_production():
    assert is_diagnostic_run(_PROD_ID) is False
    assert is_diagnostic_run("campaign-acme-ecommerce-20260721T090000Z-0f9d21") is False


def test_production_campaign_not_diagnostic_when_business_slug_contains_marker_word():
    """Regression: a real campaign id whose business/industry slug happens to contain a diagnostic
    word (smoke/demo/acceptance/fixture) must stay PRODUCTION — its structural id shape wins over
    any naming heuristic (classifier false-positive fix from GPT review)."""
    for cid in (
        "campaign-smokehouse-restaurant-20260721T101500Z-abc123",
        "campaign-product-demo-platform-20260721T101500Z-abc123",
        "campaign-acceptance-consulting-20260721T101500Z-abc123",
        "campaign-fixture-manufacturer-20260721T101500Z-abc123",
        "campaign-replay-media-agency-20260721T101500Z-abc123",
    ):
        assert is_diagnostic_run(cid) is False, cid


def test_explicit_run_kind_marker_is_authoritative():
    # An explicit persisted marker decides outright, regardless of the id text.
    assert is_diagnostic_run("campaign-acme-20260721T101500Z-abc123", run_kind="smoke") is True
    assert is_diagnostic_run("smoke-a", run_kind="production") is False


def test_legacy_diagnostics_still_caught_by_anchored_patterns():
    for cid in ("smoke-a", "v33-live-acceptance", "v33-skip-proof",
                "campaign-discovery-demo", "campaign-discovery-demo-promo-01",
                "radar-demo", "scout-demo", "replay-acme.com-171", "headed-replay-x",
                "_registry", "_runcontrol"):
        assert is_diagnostic_run(cid) is True, cid


def test_production_slug_marker_word_survives_canonical_counts(tmp_path):
    _seed_runcontrol(tmp_path, "campaign-smokehouse-restaurant-20260721T101500Z-abc123")
    _seed_runcontrol(tmp_path, "smoke-a")
    counts = campaign_counts(str(tmp_path))
    assert counts["production"] == 1 and counts["diagnostic"] == 1
    prod_ids = {c["campaign_id"] for c in canonical_campaigns(str(tmp_path))}
    assert "campaign-smokehouse-restaurant-20260721T101500Z-abc123" in prod_ids


# --- canonical enumeration (from _runcontrol, the same source Observer uses) ------------------------
def test_canonical_campaigns_excludes_diagnostics_by_default(tmp_path):
    _seed_runcontrol(tmp_path, _PROD_ID)
    _seed_runcontrol(tmp_path, "smoke-a")
    _seed_runcontrol(tmp_path, "v33-live-acceptance")

    prod = canonical_campaigns(str(tmp_path))
    ids = {c["campaign_id"] for c in prod}
    assert ids == {_PROD_ID}                              # only the real campaign
    assert all(c["diagnostic"] is False for c in prod)


def test_canonical_campaigns_include_diagnostics_returns_all_with_flags(tmp_path):
    _seed_runcontrol(tmp_path, _PROD_ID)
    _seed_runcontrol(tmp_path, "smoke-a")

    allc = canonical_campaigns(str(tmp_path), include_diagnostics=True)
    by_id = {c["campaign_id"]: c for c in allc}
    assert by_id[_PROD_ID]["diagnostic"] is False
    assert by_id["smoke-a"]["diagnostic"] is True


def test_canonical_campaigns_empty_when_no_runcontrol(tmp_path):
    assert canonical_campaigns(str(tmp_path)) == []       # no folder-scan; _runcontrol is the source


def test_campaign_counts_splits_production_and_diagnostic(tmp_path):
    _seed_runcontrol(tmp_path, _PROD_ID)
    _seed_runcontrol(tmp_path, "smoke-a")
    _seed_runcontrol(tmp_path, "v33-skip-proof")

    counts = campaign_counts(str(tmp_path))
    assert counts["production"] == 1
    assert counts["diagnostic"] == 2

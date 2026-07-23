"""Scout — unified within-site COVERAGE policy (PR-1 core, planner + config).

Coverage is the *within-site depth* axis (how many meaningful pages of ONE target to test), kept
independent of the portfolio campaign-budget axis (SESSION_PRESETS / AdaptiveAllocator, unchanged).
Two operator-facing profiles derive an internal page ceiling:

  * adaptive (product default) -> 12 additional pages
  * deep                       -> 20 additional pages

A third internal mode ``explicit`` is NOT operator-facing: it preserves a run's serialized
``max_pages_per_site`` exactly (backward compatibility for historical runs and programmatic callers),
and is the default for a raw ScoutRunConfig so nothing changes until an entry point opts into a
profile. A selected profile derives the ceiling and legacy ``max_pages_per_site`` must not silently
override it.

The planner classifies pages conservatively: skip only OBVIOUS pagination/blog/legal/language noise
BEFORE fetch, and never suppress a page as a near-duplicate from its URL alone — only observed
structural/template evidence suppresses it. It stops early when no new meaningful coverage appears,
recording an honest stop reason. Flow remains single-step (real multi-step is a later, separately
reviewed change); this module carries no 10/15 flow ceiling.
"""
from __future__ import annotations

from core.scout.backends import PageObservation
from core.scout.config import ScoutConfigError, ScoutRunConfig
from core.scout.coverage import (
    COVERAGE_MODES,
    OPERATOR_COVERAGE,
    CoveragePlanner,
    derive_page_ceiling,
    is_obvious_noise,
    page_signature,
)


# -- profiles + ceiling derivation ------------------------------------------------------------------


def test_operator_coverage_is_exactly_adaptive_and_deep():
    assert OPERATOR_COVERAGE == ("adaptive", "deep")
    assert "explicit" in COVERAGE_MODES and "explicit" not in OPERATOR_COVERAGE   # internal only


def test_derive_page_ceiling_per_profile():
    assert derive_page_ceiling("adaptive", 5) == 12          # profile derives its ceiling
    assert derive_page_ceiling("deep", 5) == 20
    assert derive_page_ceiling("explicit", 7) == 7           # explicit preserves the serialized value


# -- conservative pre-fetch noise classification ---------------------------------------------------


def test_obvious_noise_urls_are_skipped():
    for u in ("https://x.com/blog/post-1", "https://x.com/news/2026/story",
              "https://x.com/privacy", "https://x.com/terms-of-service",
              "https://x.com/cookie-policy", "https://x.com/de/", "https://x.com/fr/pricing",
              "https://x.com/tag/foo", "https://x.com/category/bar", "https://x.com/page/3",
              "https://x.com/products?page=4", "https://x.com/feed.xml"):
        assert is_obvious_noise(u) is True, u


def test_real_content_pages_are_not_noise():
    for u in ("https://x.com/", "https://x.com/pricing", "https://x.com/product/widget",
              "https://x.com/checkout", "https://x.com/about", "https://x.com/contact",
              "https://x.com/features"):
        assert is_obvious_noise(u) is False, u


# -- structural (template) signature: never URL-only -----------------------------------------------


def _obs(url, *, headings, landmarks, forms=0):
    return PageObservation(url=url, final_url=url, ok=True, status=200, backend="static",
                           headings=headings, landmarks=landmarks,
                           forms=[{"action": "/x"}] * forms)


def test_signature_is_structural_and_ignores_text_content():
    a = _obs("https://x.com/a", headings=[{"level": 1, "text": "Alpha"}, {"level": 2, "text": "One"}],
             landmarks={"main": 1, "nav": 1})
    b = _obs("https://x.com/b", headings=[{"level": 1, "text": "Beta"}, {"level": 2, "text": "Two"}],
             landmarks={"main": 1, "nav": 1})
    # Same landmark set + heading-LEVEL skeleton + form presence -> same template signature.
    assert page_signature(a) == page_signature(b)


def test_signature_differs_on_structural_difference():
    a = _obs("https://x.com/a", headings=[{"level": 1, "text": "T"}], landmarks={"main": 1})
    b = _obs("https://x.com/b", headings=[{"level": 1, "text": "T"}, {"level": 2, "text": "s"}],
             landmarks={"main": 1, "footer": 1})
    assert page_signature(a) != page_signature(b)


# -- planner: adaptive filtering, near-dup suppression, early stop, honest reasons ------------------


def _planner(coverage="adaptive", ceiling=12):
    return CoveragePlanner(coverage=coverage, page_ceiling=ceiling)


def test_adaptive_skips_obvious_noise_before_fetch():
    p = _planner()
    assert p.pre_fetch_skip("https://x.com/blog/post") == "noise"     # skipped, never fetched
    assert p.pre_fetch_skip("https://x.com/pricing") == ""            # real page proceeds
    assert p.summary()["pages_skipped_noise"] == 1


def test_adaptive_suppresses_structural_near_duplicates_only_after_evidence():
    p = _planner()
    p.seed(_obs("https://x.com/", headings=[{"level": 1, "text": "home"}],
                landmarks={"main": 1, "nav": 1}))            # landing = a distinct template (page #1)
    tmpl = dict(headings=[{"level": 1, "text": "x"}], landmarks={"main": 1})
    assert p.record("https://x.com/p1", _obs("https://x.com/p1", **tmpl)) == "meaningful"
    # Same template observed again -> near-duplicate (structural evidence, not URL).
    assert p.record("https://x.com/p2", _obs("https://x.com/p2", **tmpl)) == "near_duplicate"
    s = p.summary()
    assert s["meaningful_pages_tested"] == 2          # landing (1) + first template page (1)
    assert s["pages_skipped_near_duplicate"] == 1
    assert s["meaningful_pages_tested"] <= s["page_ceiling"]   # never reported above the ceiling


def test_seed_counts_the_landing_as_the_first_meaningful_page():
    p = _planner(ceiling=12)
    assert p.summary()["meaningful_pages_tested"] == 0        # nothing tested before seeding
    p.seed(_obs("https://x.com/", headings=[{"level": 1, "text": "h"}], landmarks={"main": 1}))
    assert p.summary()["meaningful_pages_tested"] == 1        # the landing page


def test_adaptive_stops_early_on_no_new_meaningful_coverage():
    p = _planner(ceiling=12)
    tmpl = dict(headings=[{"level": 1, "text": "x"}], landmarks={"main": 1})
    p.record("https://x.com/p0", _obs("https://x.com/p0", **tmpl))    # meaningful (first template)
    for i in range(3):                                                 # three straight near-dups
        p.record(f"https://x.com/p{i+1}", _obs(f"https://x.com/p{i+1}", **tmpl))
    assert p.should_stop() == "no_new_meaningful_coverage"


def test_adaptive_stops_at_page_ceiling():
    p = _planner(ceiling=2)
    for i in range(2):                                                 # 2 distinct meaningful pages
        p.record(f"https://x.com/p{i}",
                 _obs(f"https://x.com/p{i}", headings=[{"level": 1, "text": str(i)},
                                                       {"level": 2, "text": "s"}] * (i + 1),
                      landmarks={"main": 1, "nav": i}))
    assert p.should_stop() == "page_ceiling_reached"


def test_explicit_is_passive_no_filtering_and_matches_max_pages():
    p = _planner(coverage="explicit", ceiling=2)
    assert p.pre_fetch_skip("https://x.com/blog/post") == ""          # explicit never skips noise
    tmpl = dict(headings=[{"level": 1, "text": "x"}], landmarks={"main": 1})
    assert p.record("https://x.com/a", _obs("https://x.com/a", **tmpl)) == "meaningful"
    assert p.record("https://x.com/b", _obs("https://x.com/b", **tmpl)) == "meaningful"  # no near-dup
    assert p.should_stop() == "page_ceiling_reached"                  # only the ceiling stops explicit


def test_make_planner_ceiling_is_landing_inclusive():
    from core.scout.coverage import make_planner
    assert make_planner("adaptive", 5).page_ceiling == 12            # profile derives the total
    assert make_planner("deep", 5).page_ceiling == 20
    assert make_planner("explicit", 5).page_ceiling == 6            # landing + 5 legacy link probes


def test_planner_records_links_exhausted_when_nothing_else_stopped():
    p = _planner(ceiling=12)
    p.record("https://x.com/a", _obs("https://x.com/a", headings=[{"level": 1, "text": "x"}],
                                     landmarks={"main": 1}))
    assert p.should_stop() == ""                                      # ceiling not hit
    p.finalize_links_exhausted()
    assert p.summary()["page_stop_reason"] == "links_exhausted"


# -- config: coverage field, derivation, precedence, backward compatibility ------------------------


def _cfg(**kw):
    base = dict(campaign_name="c", seeds=["https://ex.com/"])
    base.update(kw)
    return ScoutRunConfig(**base)


def test_config_default_coverage_is_explicit_preserving_max_pages():
    c = _cfg(max_pages_per_site=5)
    assert c.coverage == "explicit" and c.max_pages_per_site == 5     # raw/back-compat default


def test_adaptive_profile_derives_and_overrides_legacy_max_pages():
    c = _cfg(coverage="adaptive", max_pages_per_site=5)               # legacy value must NOT win
    assert c.max_pages_per_site == 12
    d = _cfg(coverage="deep", max_pages_per_site=5)
    assert d.max_pages_per_site == 20


def test_unknown_coverage_is_rejected():
    try:
        _cfg(coverage="turbo")
        assert False, "expected ScoutConfigError"
    except ScoutConfigError:
        pass


def test_config_roundtrip_and_historical_default():
    c = _cfg(coverage="deep")
    assert c.to_dict()["coverage"] == "deep"
    assert c.material_signature()["coverage"] == "deep"
    # A historical serialized run has no 'coverage' key -> explicit, preserving its max_pages_per_site.
    hist = {"campaign_name": "c", "seeds": ["https://ex.com/"], "max_pages_per_site": 4}
    r = ScoutRunConfig.from_dict(hist)
    assert r.coverage == "explicit" and r.max_pages_per_site == 4

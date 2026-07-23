"""Scout — within-site coverage policy wired into the real ScoutEngine (PR-1).

Drives the actual engine over a deterministic fake backend that serves a landing page linking to a
mix of distinct templates, structural duplicates and obvious noise, and asserts the engine:
  * skips obvious noise before fetch (adaptive/deep only),
  * suppresses structural near-duplicates (observed template evidence, not URL),
  * persists per-prospect coverage.json (meaningful pages, skip counts, honest stop reason),
  * records honest single-step flow metadata (no invented 10/15 multi-step ceiling),
  * preserves the exact legacy behaviour for a run left in the default ``explicit`` mode.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.scout.backends import PageObservation
from core.scout.config import ScoutRunConfig
from core.scout.engine import ScoutEngine
from core.scout.store import RunStore

_HOST = "cov.example"
_BASE = f"https://{_HOST}"

# path -> (headings, landmarks). Same (headings, landmarks) => same template signature.
_TMPL_A = ([{"level": 1, "text": "x"}, {"level": 2, "text": "y"}], {"main": 1, "nav": 1})
_TMPL_B = ([{"level": 1, "text": "z"}], {"main": 1})
_TMPL_C = ([{"level": 1, "text": "c"}, {"level": 2, "text": "d"}, {"level": 3, "text": "e"}],
           {"main": 1, "footer": 1})
_LANDING = ([{"level": 1, "text": "home"}], {"main": 1, "nav": 1, "header": 1})

_LINKS = [f"{_BASE}/a", f"{_BASE}/b", f"{_BASE}/blog/post", f"{_BASE}/c-dup", f"{_BASE}/d-dup",
          f"{_BASE}/checkout", f"{_BASE}/privacy"]
_PAGES = {
    "/": (_LANDING, _LINKS),
    "/a": (_TMPL_A, []),
    "/b": (_TMPL_B, []),
    "/c-dup": (_TMPL_A, []),        # structural duplicate of /a
    "/d-dup": (_TMPL_A, []),        # structural duplicate of /a
    "/checkout": (_TMPL_C, []),     # a distinct flow-entry page
    "/blog/post": (_TMPL_B, []),    # would be meaningful by template, but URL is obvious noise
    "/privacy": (_TMPL_B, []),      # obvious legal noise
}


class _CoverageBackend:
    name = "static"
    screenshot_dir = None

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        path = url.replace(_BASE, "") or "/"
        tmpl, links = _PAGES.get(path, (_TMPL_B, []))
        headings, landmarks = tmpl
        return PageObservation(url=url, final_url=url, ok=True, status=200, backend=self.name,
                               title="T", meta_description="d", html_bytes=1000,
                               headings=headings, landmarks=landmarks, links=links,
                               headers={"content-type": "text/html", "cache-control": "max-age=60"})


def _run(tmp_path, coverage):
    kw = dict(campaign_name="cov", seeds=[f"{_BASE}/"], browser_mode="static", resolve_dns=False,
              output_dir=str(tmp_path), run_id=f"cov-{coverage}",
              check_families=["links", "business_flow"])
    if coverage != "explicit":
        kw["coverage"] = coverage
    else:
        kw["max_pages_per_site"] = 7          # legacy explicit cap covers all links
    cfg = ScoutRunConfig(**kw)
    store = RunStore(str(tmp_path), f"cov-{coverage}")
    ScoutEngine(cfg, store, backend=_CoverageBackend()).run()
    pid = next(iter(store.load_state()["prospects"]))
    cov = store.load_prospect_artifact(pid, "coverage.json") or {}
    state_entry = store.load_state()["prospects"][pid]
    return cov, state_entry


def test_adaptive_run_skips_noise_suppresses_dups_and_persists_honest_coverage(tmp_path):
    cov, entry = _run(tmp_path, "adaptive")
    assert cov["coverage"] == "adaptive" and cov["page_ceiling"] == 12
    assert cov["pages_skipped_noise"] == 2                 # /blog/post and /privacy skipped pre-fetch
    assert cov["pages_skipped_near_duplicate"] == 2        # /c-dup and /d-dup (template of /a)
    # landing + /a + /b + /checkout meaningful = 4
    assert cov["meaningful_pages_tested"] == 4
    assert cov["page_stop_reason"] == "links_exhausted"    # ceiling not reached, coverage exhausted
    # honest single-step flow metadata — never an invented 10/15 multi-step ceiling
    assert cov["flow_steps_supported"] == 1
    assert cov["flows_detected"] == 1 and cov["flow_entries_checked"] == 1
    assert 10 not in cov.values() and 15 not in cov.values()
    # compact summary mirrored onto the prospect state row
    assert entry["coverage"] == "adaptive" and entry["meaningful_pages_tested"] == 4


def test_explicit_run_preserves_legacy_behaviour_no_filtering(tmp_path):
    cov, entry = _run(tmp_path, "explicit")
    assert cov["coverage"] == "explicit"
    assert cov["pages_skipped_noise"] == 0                 # explicit never skips noise
    assert cov["pages_skipped_near_duplicate"] == 0        # explicit never suppresses duplicates
    # all 7 same-host links fetched + landing counted meaningful (passive planner)
    assert cov["meaningful_pages_tested"] == 8
    assert cov["flow_steps_supported"] == 1


def test_deep_run_uses_the_deep_ceiling(tmp_path):
    cov, _ = _run(tmp_path, "deep")
    assert cov["coverage"] == "deep" and cov["page_ceiling"] == 20


def test_coverage_json_is_written_under_the_prospect_dir(tmp_path):
    _run(tmp_path, "adaptive")
    store = RunStore(str(tmp_path), "cov-adaptive")
    pid = next(iter(store.load_state()["prospects"]))
    assert (Path(store.prospect_dir(pid)) / "coverage.json").exists()
    rec = json.loads((Path(store.prospect_dir(pid)) / "coverage.json").read_text(encoding="utf-8"))
    assert set(rec) >= {"coverage", "page_ceiling", "meaningful_pages_tested", "pages_skipped_noise",
                        "pages_skipped_near_duplicate", "page_stop_reason", "flows_detected",
                        "flow_entries_checked", "flow_steps_supported", "flow_steps_used",
                        "flow_stop_reason"}

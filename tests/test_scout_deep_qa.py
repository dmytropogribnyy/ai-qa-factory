"""Scout deep-QA — real axe-core accessibility + real navigation-timing performance on the operator
Playwright path (wiring the existing browser_qa depth into the ScoutEngine flow).

Deterministic checks over crafted PageObservations; the live axe/perf capture + no-network-fetch proof
is a separate Playwright acceptance. Honors the reviewed safeguards: the perf signature EXCLUDES the
exact ms (route-scoped; reproduces across differing measurements); axe findings are rule-level; the
overlapping heuristic is suppressed ONLY when axe genuinely ran; the static path is unchanged.
"""
from __future__ import annotations

import pytest

from core.scout.backends import PageObservation
from core.scout.checks import PERF_POLICY, CheckContext, check_accessibility, check_performance
from core.scout.config import ScoutRunConfig
from core.scout.engine import ScoutEngine
from core.scout.store import RunStore


def _ctx(pid="01-x", backend="playwright"):
    return CheckContext(run_id="run-1", prospect_ref=pid, backend=backend)


def _obs(**kw):
    base = dict(url="https://ex.com/p", final_url="https://ex.com/p", ok=True, backend="playwright")
    base.update(kw)
    return PageObservation(**base)


# -- performance: real navigation timing ----------------------------------------------------------


def test_slow_load_flagged_from_real_timing():
    obs = _obs(perf={"loadEvent": PERF_POLICY["load_ms"] + 1500})
    assert "slow_load" in {f.signature for f in check_performance(obs, _ctx())}


def test_fast_load_not_flagged():
    obs = _obs(perf={"loadEvent": PERF_POLICY["load_ms"] - 1000})
    assert "slow_load" not in {f.signature for f in check_performance(obs, _ctx())}


def test_slow_load_signature_excludes_ms_so_differing_measurements_reproduce():
    a = next(f for f in check_performance(_obs(perf={"loadEvent": 5000}), _ctx()) if f.signature == "slow_load")
    b = next(f for f in check_performance(_obs(perf={"loadEvent": 6200}), _ctx()) if f.signature == "slow_load")
    assert a.signature == b.signature                     # reproduces across differing ms (safeguard 1)
    assert "5000" in a.actual and "6200" in b.actual      # exact ms preserved in evidence, not signature


def test_slow_load_no_cross_page_signature_collision():
    p1 = next(f for f in check_performance(_obs(perf={"loadEvent": 5000}), _ctx("01-a")) if f.signature == "slow_load")
    p2 = next(f for f in check_performance(_obs(perf={"loadEvent": 5000}), _ctx("02-b")) if f.signature == "slow_load")
    assert p1.finding_id != p2.finding_id                 # route/prospect-scoped id; no collision


def test_playwright_missing_timing_is_unavailable_not_a_pass():
    fams = check_performance(_obs(perf={}), _ctx())        # timing not captured
    assert "slow_load" not in {f.signature for f in fams}
    assert any(f.category == "coverage" for f in fams)     # honest "timing unavailable" note


def test_static_backend_perf_keeps_its_coverage_limitation_note():
    obs = PageObservation(url="https://ex.com", ok=True, backend="static")
    fams = check_performance(obs, _ctx(backend="static"))
    assert any(f.signature == "perf_static_limitation" for f in fams)   # static coverage note unchanged


# -- accessibility: real axe-core -----------------------------------------------------------------


def test_axe_violations_become_rule_level_findings():
    obs = _obs(axe_status="ok", axe_violations=[
        {"rule": "image-alt", "impact": "serious", "help": "Images must have alt text"},
        {"rule": "label", "impact": "critical", "help": "Form elements must have labels"}])
    sigs = {f.signature for f in check_accessibility(obs, _ctx())}
    assert "axe:image-alt" in sigs and "axe:label" in sigs


def test_axe_ok_suppresses_overlapping_heuristics_but_keeps_structural():
    obs = _obs(axe_status="ok", axe_violations=[{"rule": "image-alt", "impact": "serious", "help": "alt"}],
               images=[{"src": "a.png", "alt": ""}], input_labels_ok=False,
               headings=[{"level": 2, "text": "x"}], landmarks={})
    sigs = {f.signature for f in check_accessibility(obs, _ctx())}
    assert "img_missing_alt" not in sigs and "unlabeled_input" not in sigs   # axe supersedes overlap
    assert "axe:image-alt" in sigs
    assert "missing_h1" in sigs and "missing_main" in sigs                    # structural heuristics kept
    assert any(f.category == "coverage" for f in check_accessibility(obs, _ctx()))  # honest coverage note


def test_axe_unavailable_falls_back_to_full_heuristics():
    obs = _obs(axe_status="unavailable", images=[{"src": "a.png", "alt": ""}])
    sigs = {f.signature for f in check_accessibility(obs, _ctx())}
    assert "img_missing_alt" in sigs                       # heuristics run when axe did NOT succeed
    assert not any(s.startswith("axe:") for s in sigs)


def test_static_path_accessibility_is_unchanged():
    obs = PageObservation(url="https://ex.com", ok=True, backend="static", images=[{"src": "a.png", "alt": ""}])
    sigs = {f.signature for f in check_accessibility(obs, _ctx(backend="static"))}
    assert "img_missing_alt" in sigs and not any(s.startswith("axe:") for s in sigs)


def test_old_observation_without_deep_fields_has_safe_defaults():
    obs = PageObservation(url="https://ex.com", ok=True)
    assert obs.axe_status == "" and obs.axe_violations == [] and obs.perf == {}


# -- engine two-pass verification of deep-QA findings (no browser; a fake deep-QA backend) ---------


class _DeepQABackend:
    """A Playwright-like fake that returns crafted axe/perf ONLY on deep_qa observes. perf_seq gives
    the perf dict per deep observe (so pass 1 vs pass 2 can differ); axe is the same rule set."""
    name = "playwright"
    screenshot_dir = None

    def __init__(self, perf_seq=None, axe=None):
        self._perf_seq = list(perf_seq or [])
        self._axe = axe or []
        self._deep_calls = 0

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        # A clean page except the injected deep-QA results, so only axe/perf findings can appear.
        obs = PageObservation(url=url, final_url=url, ok=True, backend=self.name, title="T",
                              meta_description="d", canonical=url, has_viewport_meta=True,
                              headings=[{"level": 1, "text": "h"}], landmarks={"main": 1},
                              headers={"cache-control": "max-age=60"})
        if deep_qa:
            perf = self._perf_seq[self._deep_calls] if self._deep_calls < len(self._perf_seq) else {}
            self._deep_calls += 1
            obs.axe_status, obs.axe_violations, obs.perf = "ok", self._axe, perf
        return obs


def _deep_cfg(tmp_path):
    return ScoutRunConfig(campaign_name="deep", seeds=["https://ex.com/p"], browser_mode="playwright",
                          output_dir=str(tmp_path))


def _verified_sigs(store):
    data = store.load_prospect_artifact("01-x", "findings.json")
    return {f["signature"] for f in data["verified"]}


def _run_prospect(tmp_path, backend):
    store = RunStore(str(tmp_path), "run-deep")
    eng = ScoutEngine(_deep_cfg(tmp_path), store, backend=backend)
    eng._process_prospect("01-x", "https://ex.com/p", {"01-x": {"status": "PENDING", "url": "https://ex.com/p"}})
    return store


def test_slow_load_reproduces_across_differing_measurements_and_is_verified(tmp_path):
    store = _run_prospect(tmp_path, _DeepQABackend(perf_seq=[{"loadEvent": 5200}, {"loadEvent": 6100}]))
    assert "slow_load" in _verified_sigs(store)            # both passes breach (5200, 6100) -> verified


def test_one_pass_only_slow_load_stays_unverified(tmp_path):
    store = _run_prospect(tmp_path, _DeepQABackend(perf_seq=[{"loadEvent": 5200}, {"loadEvent": 900}]))
    assert "slow_load" not in _verified_sigs(store)        # only pass 1 breached -> not reproduced


def test_axe_violation_reproduces_and_is_verified_end_to_end(tmp_path):
    backend = _DeepQABackend(perf_seq=[{}, {}],
                             axe=[{"rule": "image-alt", "impact": "serious", "help": "alt"}])
    assert "axe:image-alt" in _verified_sigs(_run_prospect(tmp_path, backend))


# -- unavailable-vs-ok distinction: a null/incomplete axe report is NEVER a clean "ok []" -----------


class _FakePage:
    """A minimal page double for the deep-QA collectors (no real browser). evaluate() returns the axe
    report for the axe.run() call and the perf metrics otherwise."""

    def __init__(self, perf=None, axe=None):
        self._perf, self._axe = perf, axe

    def add_script_tag(self, content=None):
        return None

    def evaluate(self, js):
        return self._axe if "axe.run" in js else self._perf


def test_collect_axe_raises_on_null_or_incomplete_report():
    from core.scout.pipeline.browser_qa import collect_axe_on_page
    for bad in (None, {}, {"violations": "not-a-list"}, "x", 5):
        with pytest.raises(Exception):
            collect_axe_on_page(_FakePage(axe=bad))


def test_collect_axe_valid_empty_report_is_ok_empty():
    from core.scout.pipeline.browser_qa import collect_axe_on_page
    assert collect_axe_on_page(_FakePage(axe={"violations": []})) == []


def test_deep_qa_marks_unavailable_when_axe_report_is_incomplete():
    from core.scout.backends import PlaywrightBackend
    obs = PageObservation(url="https://ex.com", ok=True, backend="playwright")
    PlaywrightBackend()._collect_deep_qa(_FakePage(perf={"loadEvent": 5000}, axe=None), obs)
    assert obs.axe_status == "unavailable" and obs.axe_violations == []   # a failed axe run is NOT clean
    assert obs.perf.get("loadEvent") == 5000                              # perf still captured


def test_deep_qa_valid_empty_axe_report_is_ok_not_unavailable():
    from core.scout.backends import PlaywrightBackend
    obs = PageObservation(url="https://ex.com", ok=True, backend="playwright")
    PlaywrightBackend()._collect_deep_qa(_FakePage(perf={"loadEvent": 1000}, axe={"violations": []}), obs)
    assert obs.axe_status == "ok" and obs.axe_violations == []            # succeeded-with-[] IS ok

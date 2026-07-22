"""Scout — qualified reproduction-video capture (slice D).

Video is adaptive and rare (evidence_policy §9): a short clip is kept ONLY for a reproduced
visual/interaction defect of sufficient severity when screenshots are insufficient and the path is
safe/deterministic; otherwise the temp recording is deleted (Scout never keeps an unreproduced video).

These are deterministic (no browser): the actual Playwright `.webm` recording is proven by a separate
live smoke. Here we pin the opt-in signature, the config plumbing, and the keep/delete decision.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from core.scout.backends import PageObservation, StaticHttpBackend
from core.scout.config import ScoutConfigError, ScoutRunConfig
from core.scout.engine import ScoutEngine
from core.scout.findings import ScoutFinding
from core.scout.presets import build_config
from core.scout.store import RunStore


# -- backends: opt-in record_video signature; observation carries a video_ref -----------------------


def test_page_observation_has_video_ref_defaulting_empty():
    obs = PageObservation()
    assert obs.video_ref == ""
    assert "video_ref" in obs.to_dict()


def test_static_backend_accepts_record_video_and_never_records():
    # The static backend has no browser; record_video is accepted but ignored (video_ref stays empty).
    obs = StaticHttpBackend().observe("http://169.254.169.254/latest/", 5.0, 10_000,
                                      record_video=True)
    assert obs.video_ref == ""


# -- config: opt-in video_mode, default = manual (behaviour unchanged) ------------------------------


def _cfg(**kw):
    base = dict(campaign_name="vid", seeds=["https://example.com"], browser_mode="static")
    base.update(kw)
    return ScoutRunConfig(**base)


def test_video_mode_defaults_to_manual():
    assert _cfg().video_mode == "manual"


def test_video_mode_accepts_known_modes_and_rejects_unknown():
    assert _cfg(video_mode="qualified_auto").video_mode == "qualified_auto"
    assert _cfg(video_mode="off").video_mode == "off"
    try:
        _cfg(video_mode="cinema")
        assert False, "expected ScoutConfigError for an unknown video_mode"
    except ScoutConfigError:
        pass


def test_build_config_threads_video_mode():
    cfg = build_config("safe-live-acceptance", provider_allowlist=["tavily"],
                       overrides={"video_mode": "qualified_auto"})
    assert cfg.video_mode == "qualified_auto"


# -- engine: keep a qualified reproduction video / delete everything else ---------------------------


def _engine(tmp_path, video_mode):
    cfg = _cfg(video_mode=video_mode, output_dir=str(tmp_path))
    return ScoutEngine(cfg, RunStore(str(tmp_path), "run-vid"))


def _seed_temp_video(engine, pid):
    pdir = engine.store.prospect_dir(pid)
    (pdir / "_vidtmp").mkdir(parents=True, exist_ok=True)
    (pdir / "_vidtmp" / "clip.webm").write_bytes(b"FAKEWEBM")
    return pdir


def _finding(category, severity):
    return ScoutFinding(category=category, severity=severity, check_family=category,
                        title=f"{category} {severity}", confidence="high")


def test_qualified_interaction_defect_keeps_reproduction_webm(tmp_path):
    eng = _engine(tmp_path, "qualified_auto")
    pdir = _seed_temp_video(eng, "01-x")
    verified = [_finding("business_flow", "high"), _finding("functional", "medium")]
    kept = eng._finalize_prospect_video("01-x", "_vidtmp/clip.webm", verified)
    assert kept == "reproduction.webm"
    assert (pdir / "reproduction.webm").exists()          # promoted to a servable top-level clip
    assert not (pdir / "_vidtmp").exists()                # temp always cleaned
    assert eng._videos_recorded == 1


def test_non_interaction_defect_deletes_video(tmp_path):
    eng = _engine(tmp_path, "qualified_auto")
    pdir = _seed_temp_video(eng, "01-x")
    verified = [_finding("seo", "medium")]                # screenshots suffice for a static SEO issue
    kept = eng._finalize_prospect_video("01-x", "_vidtmp/clip.webm", verified)
    assert kept == ""
    assert not (pdir / "reproduction.webm").exists()
    assert not (pdir / "_vidtmp").exists()                # unqualified recording is never kept


def test_unrelated_severe_static_defect_does_not_qualify_a_trivial_interaction_defect(tmp_path):
    # An unrelated high-severity SEO (static) defect must NOT lend its severity or QA value to a
    # low-severity business_flow finding — qualification is anchored on the interaction defect itself.
    eng = _engine(tmp_path, "qualified_auto")
    pdir = _seed_temp_video(eng, "01-x")
    verified = [_finding("seo", "high"), _finding("business_flow", "low")]
    kept = eng._finalize_prospect_video("01-x", "_vidtmp/clip.webm", verified)
    assert kept == ""                                     # the interaction defect is only low severity
    assert not (pdir / "reproduction.webm").exists()
    assert not (pdir / "_vidtmp").exists()


def test_manual_mode_never_keeps_a_video(tmp_path):
    eng = _engine(tmp_path, "manual")
    pdir = _seed_temp_video(eng, "01-x")
    verified = [_finding("business_flow", "high"), _finding("functional", "medium")]
    kept = eng._finalize_prospect_video("01-x", "_vidtmp/clip.webm", verified)
    assert kept == "" and not (pdir / "reproduction.webm").exists()


def test_no_video_ref_is_a_noop(tmp_path):
    eng = _engine(tmp_path, "qualified_auto")
    assert eng._finalize_prospect_video("01-x", "", []) == ""


class _CaptchaRecordingBackend:
    """Records a temp video on the first observe, then reports a CAPTCHA (forcing an early exit)."""
    name = "playwright"
    screenshot_dir = None

    def observe(self, url, timeout_s, max_bytes, *, record_video=False):
        obs = PageObservation(url=url, backend=self.name, captcha_marker=True)
        if record_video and self.screenshot_dir:
            vt = Path(self.screenshot_dir) / "_vidtmp"
            vt.mkdir(parents=True, exist_ok=True)
            (vt / "clip.webm").write_bytes(b"FAKEWEBM")
            obs.video_ref = "_vidtmp/clip.webm"
        return obs


def test_early_exit_still_cleans_the_temp_video(tmp_path):
    # Recording happens on the first observe; a CAPTCHA early-return must still leave no temp clip.
    cfg = _cfg(video_mode="qualified_auto", output_dir=str(tmp_path))
    store = RunStore(str(tmp_path), "run-early")
    eng = ScoutEngine(cfg, store, backend=_CaptchaRecordingBackend())
    prospects = {"01-x": {"status": "PENDING", "url": "https://ex.com"}}
    eng._process_prospect("01-x", "https://ex.com", prospects)
    assert prospects["01-x"]["status"] == "MANUAL_ACTION_REQUIRED"     # early manual exit
    assert not (Path(store.prospect_dir("01-x")) / "_vidtmp").exists()  # temp still cleaned


class _RaisingRecordingBackend:
    """Creates a temp recording on observe, then raises (e.g. a browser context failure mid-record)."""
    name = "playwright"
    screenshot_dir = None

    def observe(self, url, timeout_s, max_bytes, *, record_video=False):
        if record_video and self.screenshot_dir:
            vt = Path(self.screenshot_dir) / "_vidtmp"
            vt.mkdir(parents=True, exist_ok=True)
            (vt / "clip.webm").write_bytes(b"FAKEWEBM")
        raise RuntimeError("browser crashed mid-recording")


def test_observe_exception_still_cleans_the_temp_video(tmp_path):
    # If the recording-capable observe creates _vidtmp and then raises, the temp clip is still cleaned.
    cfg = _cfg(video_mode="qualified_auto", output_dir=str(tmp_path))
    store = RunStore(str(tmp_path), "run-raise")
    eng = ScoutEngine(cfg, store, backend=_RaisingRecordingBackend())
    prospects = {"01-x": {"status": "PENDING", "url": "https://ex.com"}}
    with pytest.raises(RuntimeError):
        eng._process_prospect("01-x", "https://ex.com", prospects)
    assert not (Path(store.prospect_dir("01-x")) / "_vidtmp").exists()  # cleaned despite the exception

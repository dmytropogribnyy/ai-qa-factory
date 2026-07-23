"""Scout — TRUE reproduction-video capture.

A reproduction video is kept ONLY when a verified INTERACTION finding is genuinely re-exhibited in the
SAME bounded browser context that performs the exact safe steps (precondition -> interaction -> actual
result -> stop -> cleanup). A page-load-only recording is never surfaced as reproduction evidence, and
when a finding cannot be genuinely replayed the run keeps no video and records `not_reproduced` honestly.

Deterministic here (a fake backend exposing reproduce_interaction); the real Chromium capture — where
the defect is visible only AFTER a navigation — is proven by a separate live acceptance test.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.scout.backends import PageObservation, StaticHttpBackend
from core.scout.config import ScoutConfigError, ScoutRunConfig
from core.scout.engine import ScoutEngine
from core.scout.findings import ScoutFinding
from core.scout.presets import build_config
from core.scout.store import RunStore


# -- backends: opt-in record_video signature; observation carries a video_ref -----------------------


def test_page_observation_has_video_ref_defaulting_empty():
    obs = PageObservation()
    assert obs.video_ref == "" and "video_ref" in obs.to_dict()


def test_static_backend_accepts_record_video_and_never_records():
    obs = StaticHttpBackend().observe("http://169.254.169.254/latest/", 5.0, 10_000, record_video=True)
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


# -- TRUE reproduction: same-context interaction replay + honest not_reproduced --------------------


class _FakeReproBackend:
    """Exposes reproduce_interaction, returning a crafted reproduction result (+ a fake .webm) so the
    engine's keep / not-reproduced / binding logic is testable without a real browser."""
    name = "playwright"
    screenshot_dir = None

    def __init__(self, actual_status, cleanup_ok=True, make_video=True):
        self._status, self._cleanup, self._make_video = actual_status, cleanup_ok, make_video
        self.calls = []

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        return PageObservation(url=url, final_url=url, ok=True, backend=self.name)

    def reproduce_interaction(self, start_url, action_url, record_dir, *, timeout_s=20.0):
        self.calls.append((start_url, action_url))
        vref = ""
        if self._make_video:
            vt = Path(record_dir) / "_reprotmp"
            vt.mkdir(parents=True, exist_ok=True)
            (vt / "clip.webm").write_bytes(b"FAKEWEBM")
            vref = "_reprotmp/clip.webm"
        return {"start_url": start_url, "action_url": action_url, "action_log": ["goto", "follow"],
                "final_url": action_url, "actual_status": self._status, "cleanup_ok": self._cleanup,
                "video_ref": vref}


def _repro_engine(tmp_path, backend, video_mode="qualified_auto"):
    cfg = ScoutRunConfig(campaign_name="repro", seeds=["https://ex.com"], browser_mode="playwright",
                         video_mode=video_mode, output_dir=str(tmp_path))
    return ScoutEngine(cfg, RunStore(str(tmp_path), "run-repro"), backend=backend)


def _broken_flow_finding():
    return ScoutFinding(signature="flow_entry_broken", category="business_flow",
                        check_family="business_flow", severity="high", confidence="high",
                        title="Primary business flow entry is broken",
                        actual="Flow entry link failed: https://ex.com/checkout")


_FLOW = {"entry_url": "https://ex.com/checkout", "entry_broken": True}


def test_reproduced_broken_flow_keeps_video_and_binds_evidence(tmp_path):
    backend = _FakeReproBackend(actual_status=404)          # flow entry genuinely broken -> reproduced
    eng = _repro_engine(tmp_path, backend)
    pdir = Path(eng.store.prospect_dir("01-x"))
    kept = eng._reproduce_prospect_findings("01-x", "https://ex.com", [_broken_flow_finding()], _FLOW)
    assert kept == "reproduction.webm" and (pdir / "reproduction.webm").exists()
    assert not (pdir / "_reprotmp").exists()               # temp always cleaned
    assert backend.calls == [("https://ex.com", "https://ex.com/checkout")]   # SAME-context interaction
    rec = json.loads((pdir / "reproduction.json").read_text(encoding="utf-8"))
    assert rec["reproduced"] is True and rec["signature"] == "flow_entry_broken"
    assert rec["action_url"] == "https://ex.com/checkout" and rec["video_ref"] == "reproduction.webm"
    assert rec["action_log"] and rec["cleanup_ok"] is True and rec["start_url"] == "https://ex.com"


def test_flow_entry_that_loads_fine_is_not_reproduced_no_video(tmp_path):
    backend = _FakeReproBackend(actual_status=200)          # followed action loads OK -> NOT reproduced
    eng = _repro_engine(tmp_path, backend)
    pdir = Path(eng.store.prospect_dir("01-x"))
    kept = eng._reproduce_prospect_findings("01-x", "https://ex.com", [_broken_flow_finding()], _FLOW)
    assert kept == "" and not (pdir / "reproduction.webm").exists()
    rec = json.loads((pdir / "reproduction.json").read_text(encoding="utf-8"))
    assert rec["reproduced"] is False and rec["reproduction_status"] == "not_reproduced"


def test_no_interaction_finding_no_reproduction_attempted(tmp_path):
    backend = _FakeReproBackend(actual_status=404)
    eng = _repro_engine(tmp_path, backend)
    seo = ScoutFinding(signature="missing_title", category="seo", severity="medium", title="x")
    kept = eng._reproduce_prospect_findings("01-x", "https://ex.com", [seo], {"entry_url": ""})
    assert kept == "" and backend.calls == []              # no replayable interaction -> no repro run


def test_manual_mode_never_reproduces(tmp_path):
    backend = _FakeReproBackend(actual_status=404)
    eng = _repro_engine(tmp_path, backend, video_mode="manual")
    kept = eng._reproduce_prospect_findings("01-x", "https://ex.com", [_broken_flow_finding()], _FLOW)
    assert kept == "" and backend.calls == []              # opt-in only


def test_reproduction_without_verified_cleanup_keeps_no_video(tmp_path):
    backend = _FakeReproBackend(actual_status=404, cleanup_ok=False)
    eng = _repro_engine(tmp_path, backend)
    pdir = Path(eng.store.prospect_dir("01-x"))
    kept = eng._reproduce_prospect_findings("01-x", "https://ex.com", [_broken_flow_finding()], _FLOW)
    assert kept == "" and not (pdir / "reproduction.webm").exists()   # unclean session -> no evidence


def test_static_backend_without_reproduce_capability_keeps_no_video(tmp_path):
    class _Static:
        name = "static"

        def observe(self, url, t, b, *, record_video=False, deep_qa=False):
            return PageObservation(url=url, ok=True)

    cfg = ScoutRunConfig(campaign_name="r", seeds=["https://ex.com"], browser_mode="playwright",
                         video_mode="qualified_auto", output_dir=str(tmp_path))
    eng = ScoutEngine(cfg, RunStore(str(tmp_path), "run-s"), backend=_Static())
    kept = eng._reproduce_prospect_findings("01-x", "https://ex.com", [_broken_flow_finding()], _FLOW)
    assert kept == ""                                      # no reproduce_interaction -> honest no-video

"""A recording, and what it is allowed to claim.

The dangerous property of a video is that a trace and a defect look identical: the same page, the
same click, the same clip. Only the outcome separates "we proved the recorder works" from "this
client has a broken control", and everything downstream — findings, the fix offer, the outreach
draft — hangs off that single word.

So these tests are mostly about refusals: a working control must not become a finding, a clip that
does not decode must not be offered, a defect seen once must not survive a second pass that
disagrees, and a recording that was never cleaned up must not be kept at all.
"""
from __future__ import annotations

import json

import pytest

from core.scout.interaction_scenario import (DEFECT_SIGNATURE, OUTCOME_DEFECT, OUTCOME_NOT_RUN,
                                             OUTCOME_TRACE, SCENARIO_ADD_REMOVE, SCENARIO_FILTER,
                                             SCENARIO_SELECT, ScenarioResult, candidate_is_safe,
                                             classify, finding_from)
from core.scout.media_probe import probe_video

# --- a real container, built byte by byte ---------------------------------------------------------


def _vint(value: int) -> bytes:
    if value < 0x7F:
        return bytes([0x80 | value])
    if value < 0x3FFF:
        return bytes([0x40 | (value >> 8), value & 0xFF])
    return bytes([0x20 | (value >> 16), (value >> 8) & 0xFF, value & 0xFF])


def _el(element_id: bytes, payload: bytes) -> bytes:
    return element_id + _vint(len(payload)) + payload


def webm_bytes(*, width=800, height=450, duration_ms=3000.0, frame_times=(0, 1000, 2000)) -> bytes:
    """A minimal but genuine Matroska document — the shape Playwright writes, in miniature."""
    import struct
    info = _el(b"\x15\x49\xa9\x66",
               _el(b"\x2a\xd7\xb1", (1_000_000).to_bytes(4, "big"))
               + _el(b"\x44\x89", struct.pack(">d", duration_ms)))
    video = _el(b"\xe0", _el(b"\xb0", width.to_bytes(2, "big"))
                + _el(b"\xba", height.to_bytes(2, "big")))
    tracks = _el(b"\x16\x54\xae\x6b", _el(b"\xae", video))
    blocks = b"".join(
        _el(b"\xa3", b"\x81" + int(t).to_bytes(2, "big", signed=True) + b"\x80" + b"\x00" * 8)
        for t in frame_times)
    cluster = _el(b"\x1f\x43\xb6\x75", _el(b"\xe7", (0).to_bytes(1, "big")) + blocks)
    return _el(b"\x18\x53\x80\x67", info + tracks + cluster)


def test_a_real_recording_is_described_from_its_own_bytes(tmp_path):
    clip = tmp_path / "interaction.webm"
    clip.write_bytes(webm_bytes())

    probe = probe_video(clip)

    assert probe["playable"] is True
    assert probe["width"] == 800 and probe["height"] == 450
    assert probe["duration_s"] == 3.0
    assert probe["block_count"] == 3
    assert probe["timespan_ms"] == 2000
    assert probe["mime"] == "video/webm"
    assert len(probe["sha256"]) == 64


def test_a_single_static_frame_is_not_a_recording(tmp_path):
    """Duration is a number in a header. One frame stamped once is not footage, whatever it says."""
    clip = tmp_path / "still.webm"
    clip.write_bytes(webm_bytes(duration_ms=8000.0, frame_times=(0,)))

    probe = probe_video(clip)

    assert probe["playable"] is False
    assert "static frame" in probe["error"]


def test_an_empty_file_is_reported_as_empty_not_as_a_video(tmp_path):
    clip = tmp_path / "empty.webm"
    clip.write_bytes(b"")

    assert probe_video(clip)["playable"] is False
    assert probe_video(clip)["error"] == "the file is empty"


def test_a_file_that_is_not_a_container_fails_honestly(tmp_path):
    clip = tmp_path / "notreally.webm"
    clip.write_bytes(b"this is not a matroska document at all, it is prose")

    probe = probe_video(clip)

    assert probe["playable"] is False
    assert probe["bytes"] > 0 and probe["sha256"]


# --- what the outcome is allowed to be ------------------------------------------------------------

_BASE = {"result_count": 25, "item_signature": ["25", "iPhone"], "control_label": "Apple",
         "url": "https://shop.example/phones"}


@pytest.mark.parametrize("observed,expected", [
    # The site itself said the filter took effect — it moved to a filtered URL — and returned the
    # identical list. Without that signal an unchanged list proves nothing: see
    # tests/test_scout_interaction_oracle.py.
    ({"result_count": 25, "item_signature": ["25", "iPhone"], "control_engaged": True,
      "url": "https://shop.example/phones?brand=apple"},
     OUTCOME_DEFECT),
    ({"result_count": 9, "item_signature": ["9", "iPhone"], "control_engaged": True},
     OUTCOME_TRACE),
    ({"result_count": 25, "item_signature": ["25", "Galaxy"], "control_engaged": True},
     OUTCOME_TRACE),
    ({"result_count": 25, "item_signature": ["25", "iPhone"], "control_engaged": False},
     OUTCOME_NOT_RUN),
])
def test_a_filter_is_judged_on_whether_the_results_moved(observed, expected):
    outcome, reason = classify(SCENARIO_FILTER, _BASE, observed,
                               action_performed=True, cleanup_ok=True)

    assert outcome == expected
    assert reason


def test_a_control_that_never_ran_claims_nothing():
    outcome, _ = classify(SCENARIO_FILTER, _BASE, {}, action_performed=False, cleanup_ok=False)

    assert outcome == OUTCOME_NOT_RUN


def test_leaving_the_page_disqualifies_the_observation():
    outcome, reason = classify(SCENARIO_FILTER, _BASE,
                               {"result_count": 25, "item_signature": ["25"], "control_engaged": True},
                               action_performed=True, cleanup_ok=True, navigated_away=True)

    assert outcome == OUTCOME_NOT_RUN
    assert "navigated away" in reason


@pytest.mark.parametrize("scenario,baseline,observed,expected", [
    (SCENARIO_SELECT, {"selected_label": "Audi"}, {"selected_label": "BMW"}, OUTCOME_TRACE),
    (SCENARIO_SELECT, {"selected_label": "Audi"}, {"selected_label": "Audi"}, OUTCOME_NOT_RUN),
    (SCENARIO_ADD_REMOVE, {"removable_count": 0}, {"removable_count": 1}, OUTCOME_TRACE),
    (SCENARIO_ADD_REMOVE, {"removable_count": 0}, {"removable_count": 0}, OUTCOME_NOT_RUN),
])
def test_a_control_with_no_stated_promise_is_never_called_broken(scenario, baseline, observed,
                                                                 expected):
    """Scout does not know what an arbitrary button was for. A filter is different: its label is a
    promise about the results, which is why only that case can be a defect."""
    outcome, _ = classify(scenario, baseline, observed, action_performed=True, cleanup_ok=True)

    assert outcome == expected


# --- the gate between a recording and a claim -----------------------------------------------------

def test_an_interaction_trace_never_becomes_a_finding():
    """The single most important refusal here."""
    trace = ScenarioResult(scenario=SCENARIO_ADD_REMOVE, outcome=OUTCOME_TRACE,
                           url="https://the-internet.herokuapp.com/add_remove_elements/",
                           action_performed=True, cleanup_ok=True)

    assert finding_from(trace, run_id="r", prospect_ref="01") is None


def test_a_confirmed_defect_becomes_exactly_one_finding():
    defect = ScenarioResult(scenario=SCENARIO_FILTER, outcome=OUTCOME_DEFECT,
                            url="https://shop.example/", control_label="Apple",
                            observed={"result_count": 25}, action_performed=True, cleanup_ok=True,
                            steps=["open", "select the Apple filter", "observe"])

    finding = finding_from(defect, run_id="r", prospect_ref="01", video_ref="interaction.webm")

    assert finding.signature == DEFECT_SIGNATURE
    assert finding.severity == "high"
    assert "interaction.webm" in finding.evidence_refs
    assert "25" in finding.actual


@pytest.mark.parametrize("performed,cleanup,outcome,kept", [
    (True, True, OUTCOME_TRACE, True),
    (True, True, OUTCOME_DEFECT, True),
    (True, False, OUTCOME_DEFECT, False),      # the page was left changed: not evidence of anything
    (False, True, OUTCOME_NOT_RUN, False),     # nothing happened: a page-load clip
])
def test_a_clip_is_kept_only_when_it_shows_a_completed_interaction(performed, cleanup, outcome,
                                                                   kept):
    result = ScenarioResult(outcome=outcome, action_performed=performed, cleanup_ok=cleanup)

    assert result.keeps_video is kept


@pytest.mark.parametrize("candidate", [
    None,
    {"kind": "reversible_filter", "label": "Subscribe to our newsletter"},
    {"kind": "reversible_filter", "label": "Place order"},
    {"kind": "something_else", "label": "Apple"},
])
def test_an_unsafe_or_unknown_control_is_refused(candidate):
    assert candidate_is_safe(candidate) is False


def test_an_ordinary_filter_control_is_accepted():
    assert candidate_is_safe({"kind": SCENARIO_FILTER, "label": "Apple"}) is True


# --- through the engine ---------------------------------------------------------------------------

class _ScriptedBackend:
    """A browser that returns a prepared scenario and writes a real clip where one is expected."""

    name = "playwright"
    screenshot_dir = None

    def __init__(self, *results):
        self._results = list(results)
        self.calls = 0

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        from core.scout.backends import PageObservation
        return PageObservation(url=url, final_url=url, status=200, ok=True, backend=self.name,
                               title="Fixture", html_bytes=1000,
                               headings=[{"level": 1, "text": "Fixture"}])

    def record_interaction_scenario(self, url, record_dir, **_kw):
        import os
        result = dict(self._results[min(self.calls, len(self._results) - 1)])
        self.calls += 1
        if result.get("video_ref"):
            tmp = os.path.join(record_dir, "_scenariotmp")
            os.makedirs(tmp, exist_ok=True)
            with open(os.path.join(tmp, "clip.webm"), "wb") as fh:
                fh.write(result.pop("_bytes", webm_bytes()))
            result["video_ref"] = os.path.join("_scenariotmp", "clip.webm")
        result.setdefault("url", url)
        return result


def _scenario(outcome, *, with_video=True, **extra):
    return {"scenario": SCENARIO_FILTER, "outcome": outcome, "reason": "because",
            "control_label": "Apple", "action": "select the Apple filter",
            "action_performed": True, "cleanup_ok": True,
            "baseline": {"result_count": 25}, "observed": {"result_count": 25},
            "after_cleanup": {"result_count": 25}, "steps": ["open", "click", "observe"],
            "video_ref": "keep" if with_video else "", **extra}


def _run(tmp_path, backend):
    from core.scout.config import ScoutRunConfig
    from core.scout.engine import ScoutEngine
    from core.scout.store import RunStore

    cfg = ScoutRunConfig(campaign_name="scenario", seeds=["https://fixture.example/"],
                         browser_mode="playwright", video_mode="qualified_auto",
                         output_dir=str(tmp_path), run_id="scenario-run",
                         allowed_local_hosts=frozenset({"fixture.example"}), resolve_dns=False,
                         check_families=["accessibility"])
    store = RunStore(str(tmp_path), "scenario-run")
    state = ScoutEngine(cfg, store, backend=backend).run()
    pid = next(iter(state["prospects"]))
    return store, pid, state


def test_the_engine_keeps_a_playable_clip_and_records_what_it_shows(tmp_path):
    store, pid, state = _run(tmp_path, _ScriptedBackend(_scenario(OUTCOME_TRACE)))

    record = store.load_prospect_artifact(pid, "interaction_scenario.json")
    assert record["outcome"] == OUTCOME_TRACE
    assert record["video_ref"] == "interaction.webm"
    assert record["video"]["playable"] is True
    assert record["run_purpose"] == "production"
    assert (store.prospect_dir(pid) / "interaction.webm").is_file()
    assert state["prospects"][pid]["interaction_video_ref"] == "interaction.webm"


def test_a_clip_that_does_not_decode_is_deleted_rather_than_offered(tmp_path):
    backend = _ScriptedBackend(_scenario(OUTCOME_TRACE, _bytes=b"not a video"))
    store, pid, _ = _run(tmp_path, backend)

    record = store.load_prospect_artifact(pid, "interaction_scenario.json")
    assert record["video_ref"] == ""
    assert record["video_rejected_reason"]
    assert not (store.prospect_dir(pid) / "interaction.webm").exists()


def test_a_trace_adds_no_finding_to_the_run(tmp_path):
    store, pid, _ = _run(tmp_path, _ScriptedBackend(_scenario(OUTCOME_TRACE)))

    findings = store.load_prospect_artifact(pid, "findings.json")
    assert DEFECT_SIGNATURE not in {f["signature"] for f in findings["verified"]}


def test_a_defect_seen_once_and_not_again_is_downgraded_to_a_trace(tmp_path):
    """The same independent-second-pass rule every other finding obeys."""
    backend = _ScriptedBackend(_scenario(OUTCOME_DEFECT), _scenario(OUTCOME_TRACE))
    store, pid, _ = _run(tmp_path, backend)

    record = store.load_prospect_artifact(pid, "interaction_scenario.json")
    findings = store.load_prospect_artifact(pid, "findings.json")

    assert backend.calls == 2
    assert record["outcome"] == OUTCOME_TRACE
    assert record["confirmation"]["agreed"] is False
    assert DEFECT_SIGNATURE not in {f["signature"] for f in findings["verified"]}
    assert (store.prospect_dir(pid) / "interaction.webm").is_file()   # the recording still stands


def test_a_defect_confirmed_twice_becomes_a_verified_finding(tmp_path):
    backend = _ScriptedBackend(_scenario(OUTCOME_DEFECT), _scenario(OUTCOME_DEFECT))
    store, pid, _ = _run(tmp_path, backend)

    record = store.load_prospect_artifact(pid, "interaction_scenario.json")
    verified = store.load_prospect_artifact(pid, "findings.json")["verified"]
    matching = [f for f in verified if f["signature"] == DEFECT_SIGNATURE]

    assert record["confirmation"]["agreed"] is True
    assert len(matching) == 1
    assert matching[0]["verification_state"] == "VERIFIED"


def test_the_manifest_binds_the_clip_by_hash_and_says_it_plays(tmp_path):
    store, pid, _ = _run(tmp_path, _ScriptedBackend(_scenario(OUTCOME_TRACE)))

    manifest = store.load_prospect_artifact(pid, "evidence_manifest.json")
    entry = next(e for e in manifest["entries"] if e["ref"] == "interaction.webm")

    assert entry["kind"] == "interaction_video"
    assert entry["playable"] is True
    assert entry["duration_s"] > 0
    assert len(entry["sha256"]) == 64
    from core.scout.media_probe import sha256_of
    assert entry["sha256"] == sha256_of(store.prospect_dir(pid) / "interaction.webm")


def test_no_temporary_recording_survives_the_run(tmp_path):
    store, pid, _ = _run(tmp_path, _ScriptedBackend(_scenario(OUTCOME_TRACE)))

    assert not (store.prospect_dir(pid) / "_scenariotmp").exists()


def test_video_capture_switched_off_records_no_scenario_at_all(tmp_path):
    from core.scout.config import ScoutRunConfig
    from core.scout.engine import ScoutEngine
    from core.scout.store import RunStore

    backend = _ScriptedBackend(_scenario(OUTCOME_TRACE))
    cfg = ScoutRunConfig(campaign_name="scenario", seeds=["https://fixture.example/"],
                         browser_mode="playwright", video_mode="off", output_dir=str(tmp_path),
                         run_id="off-run", allowed_local_hosts=frozenset({"fixture.example"}),
                         resolve_dns=False, check_families=["accessibility"])
    store = RunStore(str(tmp_path), "off-run")
    state = ScoutEngine(cfg, store, backend=backend).run()
    pid = next(iter(state["prospects"]))

    assert backend.calls == 0
    assert store.load_prospect_artifact(pid, "interaction_scenario.json") is None


# --- the client package ----------------------------------------------------------------------------

def test_the_client_package_names_a_recording_for_what_it_is(tmp_path):
    """Packaging an interaction recording as "reproduction-01" would tell a client a defect was
    reproduced, which is the opposite of what a trace shows."""
    from core.scout.client_evidence import build_client_evidence_bundle

    store, pid, _ = _run(tmp_path, _ScriptedBackend(_scenario(OUTCOME_TRACE)))
    detail = {"domain": "fixture.example", "run": "scenario-run", "prospect_id": pid,
              "analysis_complete": True, "findings": [], "media": [
                  f"prospects/{pid}/interaction.webm"], "video_mode": "qualified_auto"}

    bundle = build_client_evidence_bundle(str(tmp_path), run_id="scenario-run", prospect_id=pid,
                                          domain="fixture.example", detail=detail)

    import zipfile
    with zipfile.ZipFile(bundle.path) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read(
            next(n for n in names if n.endswith("manifest.json"))).decode("utf-8"))
        report = archive.read(next(n for n in names if n.endswith("QA-Report.html"))).decode("utf-8")

    video_entry = next(e for e in manifest["entries"] if e["path"].endswith(".webm"))
    assert video_entry["path"] == "Evidence/Videos/interaction-01.webm"
    assert "reproduction" not in video_entry["path"]
    assert len(video_entry["sha256"]) == 64
    assert video_entry["playable"] is True
    from core.scout.media_probe import sha256_of
    assert video_entry["sha256"] == sha256_of(store.prospect_dir(pid) / "interaction.webm")
    # The offline report plays it where it was unpacked, by relative path.
    assert '<video src="Evidence/Videos/interaction-01.webm" controls' in report
    assert "Recorded interaction 1" in report


# --- the surface an operator actually opens -------------------------------------------------------

def test_the_recorded_interaction_is_shown_on_the_target_page(tmp_path):
    """It was first added to the LEGACY target renderer, which is off unless an environment
    variable turns it on — so the card existed in the code and never on anyone's screen."""
    from core.scout.dashboard import _interaction_card

    record = {"scenario": SCENARIO_FILTER, "outcome": OUTCOME_TRACE,
              "reason": "the filter narrowed the results, which is correct behaviour",
              "control_label": "Apple", "run_id": "run-1", "prospect_id": "01",
              "video_ref": "interaction.webm", "cleanup_ok": True,
              "baseline": {"result_count": 25, "item_signature": ["25", "iPhone"]},
              "observed": {"result_count": 9, "item_signature": ["9", "iPhone"]},
              "after_cleanup": {"result_count": 25, "item_signature": ["25", "iPhone"]},
              "steps": ["open", "select the Apple filter", "observe"],
              "video": {"bytes": 216680, "duration_s": 7.48, "width": 800, "height": 450,
                        "mime": "video/webm", "sha256": "a" * 64}}

    html = _interaction_card(record, lambda rel: f"/scout/artifact?rel={rel}")

    assert "<h2>Recorded interaction</h2>" in html
    assert '<video src="/scout/artifact?rel=prospects/01/interaction.webm" controls' in html
    # The headline must not read as a defect, and the reason must survive to the page.
    assert "the control behaved correctly" in html
    assert "correct behaviour" in html
    for label in ("Before", "After the action", "After cleanup", "Recording"):
        assert label in html
    assert "7.48" in html and "800" in html and "450" in html


def test_the_card_says_nothing_when_no_interaction_was_recorded():
    from core.scout.dashboard import _interaction_card

    assert _interaction_card(None, lambda rel: rel) == ""
    assert _interaction_card({}, lambda rel: rel) == ""


def test_a_state_description_reports_the_collection_size_not_the_sample(tmp_path):
    """The signature's first element is the size; the rest is a bounded sample of it. Reporting the
    sample length said "13 listed item(s)" for a page showing 25."""
    from core.scout.backends import PlaywrightBackend

    described = PlaywrightBackend._describe_state(
        SCENARIO_FILTER, {"result_count": 25,
                          "item_signature": ["25"] + [f"item {i}" for i in range(12)]})

    assert "25 listed item(s)" in described
    assert "13 listed" not in described

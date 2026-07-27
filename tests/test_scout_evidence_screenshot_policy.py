"""A client must receive distinct pictures, not a screenshot counter.

The bundle used to package `landing.png` and `verification.png` as `screenshot-01.png` and
`screenshot-02.png` and announce "2 screenshots". For a static page those two files are
byte-identical -- proven by their equal SHA-256 in a real easybooking.sk run -- so the client opened
the same picture twice and the count was true about files and false about evidence.

The policy pinned here: package at most three UNIQUE frames of pages the analysis actually visited,
drop byte-identical repeats, name each frame for the page it shows, record that page's URL in the
manifest, and state plainly why a reproduction video is absent instead of leaving a bare zero.
"""
from __future__ import annotations

import io
import json
import zipfile
from pathlib import Path

import pytest

from core.scout.campaign_service import CampaignService
from core.scout.client_evidence import ClientEvidenceError, _MAX_CLIENT_SCREENSHOTS
from core.scout.store import RunStore

_RUN = "evidence-policy-run"
_PID = "01-alpha"
_DOMAIN = "alpha.example"


def _run(tmp_path, *, frames, screenshots_record=True, video=False, video_mode="manual"):
    """A completed run whose prospect dir holds exactly the given ``name -> bytes`` frames."""
    store = RunStore(str(tmp_path), _RUN)
    store.write_config({"campaign_name": "evidence", "video_mode": video_mode,
                        "browser_mode": "playwright"})
    store.save_prospect_artifact(_PID, "findings.json", {"verified": [
        {"signature": "a11y_contrast", "severity": "high", "check_family": "accessibility",
         "title": "Insufficient colour contrast", "is_client_safe": True,
         "business_impact": "Some visitors cannot read the offer."}]})
    store.save_prospect_artifact(_PID, "observation.json", {
        "final_url": f"https://{_DOMAIN}/", "status": 200, "screenshot_ref": "landing.png"})
    store.save_prospect_artifact(_PID, "coverage.json", {
        "coverage": "adaptive", "meaningful_pages_tested": len(frames),
        "page_stop_reason": "no_new_meaningful_coverage"})
    for name, payload in frames.items():
        (store.prospect_dir(_PID) / name).write_bytes(payload)
    if screenshots_record:
        store.save_prospect_artifact(_PID, "screenshots.json", {
            "schema": "scout-screenshots/v1", "captured": len(frames),
            "max_frames": _MAX_CLIENT_SCREENSHOTS,
            "frames": [
                {"file": "landing.png", "url": f"https://{_DOMAIN}/", "role": "landing"},
                {"file": "page-02.png", "url": f"https://{_DOMAIN}/pricing", "role": "pricing"},
                {"file": "page-03.png", "url": f"https://{_DOMAIN}/book", "role": "booking-flow"},
                {"file": "page-04.png", "url": f"https://{_DOMAIN}/about", "role": "about"},
            ][:max(1, len([f for f in frames if f != "verification.png"]))],
        })
    if video:
        (store.prospect_dir(_PID) / "reproduction.webm").write_bytes(b"clip")
        store.save_prospect_artifact(_PID, "reproduction.json", {
            "reproduced": True, "reproduction_status": "reproduced", "cleanup_ok": True,
            "video_ref": "reproduction.webm", "start_url": f"https://{_DOMAIN}/"})
    store.save_state({"status": "COMPLETED", "prospects": {
        _PID: {"status": "DONE", "url": f"https://{_DOMAIN}/", "analysis_complete": True,
               "verified_findings": 1, "verified_defects": 1}}})
    return store


def _bundle(tmp_path):
    """Members keyed WITHOUT the dated root folder, so these assertions stay about layout.

    The package is now rooted in one dated directory (Unified Scout spec, §11.4) — extracting a flat
    ZIP scattered loose files, and two packages a month apart shared one filename.
    """
    result = CampaignService(str(tmp_path)).export_client_evidence(_DOMAIN, run=_RUN)
    with zipfile.ZipFile(io.BytesIO(Path(result["path"]).read_bytes())) as archive:
        return {name.split("/", 1)[1]: archive.read(name) for name in archive.namelist()}


def _shots(files):
    return sorted(n for n in files if n.startswith("Evidence/Screenshots/"))


def _manifest(files):
    return json.loads(files["manifest.json"].decode("utf-8"))


def test_a_byte_identical_verification_frame_is_not_packaged_twice(tmp_path):
    """The exact easybooking.sk shape: the verification pass re-photographed an unchanged page."""
    same = b"\x89PNG identical bytes"
    _run(tmp_path, frames={"landing.png": same, "verification.png": same})
    files = _bundle(tmp_path)

    assert len(_shots(files)) == 1, "the same picture was packaged as two pieces of evidence"
    summary = files["Evidence/Technical/scan-summary.md"].decode("utf-8")
    assert "Unique screenshots included: **1**" in summary
    assert any("identical" in str(row.get("reason", ""))
               for row in _manifest(files)["omitted"])


def test_a_verification_frame_that_really_differs_is_kept(tmp_path):
    """Deduplication must be by content, never by filename -- a changed page is new evidence."""
    _run(tmp_path, frames={"landing.png": b"first capture", "verification.png": b"second capture"})
    files = _bundle(tmp_path)

    assert len(_shots(files)) == 2


def test_distinct_pages_are_packaged_and_named_for_what_they_show(tmp_path):
    _run(tmp_path, frames={"landing.png": b"one", "page-02.png": b"two", "page-03.png": b"three"})
    files = _bundle(tmp_path)

    assert _shots(files) == ["Evidence/Screenshots/booking-flow.png",
                            "Evidence/Screenshots/landing.png",
                            "Evidence/Screenshots/pricing.png"]
    assert "screenshot-01" not in " ".join(files)


def test_the_manifest_binds_every_frame_to_its_page(tmp_path):
    _run(tmp_path, frames={"landing.png": b"one", "page-02.png": b"two"})
    files = _bundle(tmp_path)
    shots = [e for e in _manifest(files)["entries"] if e["path"].startswith("Evidence/Screenshots/")]

    assert {e["role"] for e in shots} == {"landing", "pricing"}
    assert {e["page_url"] for e in shots} == {f"https://{_DOMAIN}/", f"https://{_DOMAIN}/pricing"}
    assert all(len(e["sha256"]) == 64 for e in shots)
    assert len({e["sha256"] for e in shots}) == len(shots)      # unique bytes, not just unique names


def test_never_more_than_three_frames_even_when_more_were_captured(tmp_path):
    _run(tmp_path, frames={"landing.png": b"one", "page-02.png": b"two",
                           "page-03.png": b"three", "page-04.png": b"four"})
    files = _bundle(tmp_path)

    assert len(_shots(files)) == _MAX_CLIENT_SCREENSHOTS
    assert any("budget" in str(row.get("reason", "")) for row in _manifest(files)["omitted"])


def test_one_meaningful_page_yields_one_frame_and_says_so(tmp_path):
    """A ceiling, not a quota: a thin site must not be padded up to three pictures."""
    _run(tmp_path, frames={"landing.png": b"only one"})
    files = _bundle(tmp_path)

    assert len(_shots(files)) == 1
    assert "Unique screenshots included: **1**" in files["Evidence/Technical/scan-summary.md"].decode("utf-8")


def test_absent_video_is_explained_not_left_as_a_bare_zero(tmp_path):
    """Missing video must read as "not applicable here", never as missing evidence."""
    _run(tmp_path, frames={"landing.png": b"one"})
    files = _bundle(tmp_path)
    summary = files["Evidence/Technical/scan-summary.md"].decode("utf-8")
    html = files["QA-Report.html"].decode("utf-8")

    assert "Reproduction videos included: **0**" in summary
    assert "No reproduction video:" in summary
    assert "manual/opt-in" in summary            # the reason that actually applied to this run
    assert "not a failed capture" in summary
    assert "No reproduction video:" in html


@pytest.mark.parametrize("mode, expected", [
    ("manual", "manual/opt-in"),
    ("off", "disabled for this run"),
    ("qualified_auto", "no confirmed finding is a broken interaction"),
    ("", "cannot be stated"),
])
def test_the_stated_reason_for_a_missing_video_is_the_one_that_applied(mode, expected):
    """A confident wrong reason is worse than none: a run with capture switched off never asked
    whether an interaction was broken, so it must not answer that question."""
    from core.scout.client_evidence import _video_absence_note

    note = _video_absence_note({"video_mode": mode, "findings": []})

    assert expected in note


def test_a_replayed_interaction_that_behaved_is_reported_as_such():
    from core.scout.client_evidence import _video_absence_note

    note = _video_absence_note({"video_mode": "qualified_auto",
                                "reproduction": {"reproduction_status": "not_reproduced"}})

    assert "did not misbehave" in note


def test_a_real_reproduction_video_is_still_packaged_without_the_note(tmp_path):
    """The guard on the other side: a genuine reproduction must not be talked away."""
    _run(tmp_path, frames={"landing.png": b"one"}, video=True)
    files = _bundle(tmp_path)
    summary = files["Evidence/Technical/scan-summary.md"].decode("utf-8")

    assert "Evidence/Videos/reproduction-01.webm" in files
    assert "Reproduction videos included: **1**" in summary
    assert "No reproduction video:" not in summary


def test_a_legacy_run_without_a_screenshots_record_still_exports(tmp_path):
    """Historical runs pre-date the record; they keep the file stem instead of an invented role."""
    _run(tmp_path, frames={"landing.png": b"one"}, screenshots_record=False)
    files = _bundle(tmp_path)

    assert _shots(files) == ["Evidence/Screenshots/landing.png"]
    shots = [e for e in _manifest(files)["entries"] if e["path"].startswith("Evidence/Screenshots/")]
    assert shots[0].get("page_url") == ""            # unknown, and honestly empty rather than guessed


# --- the operator surface: a frame the operator cannot place is a frame they must open ------

def test_the_target_page_names_each_frame_by_the_page_it_shows(tmp_path):
    import urllib.request
    from core.scout.dashboard import start_dashboard
    from core.scout.service import ScoutService

    _run(tmp_path, frames={"landing.png": b"one", "page-02.png": b"two",
                           "verification.png": b"three"})
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = urllib.request.urlopen(
            f"{url}/scout/target?run={_RUN}&domain={_DOMAIN}", timeout=10).read().decode("utf-8")
    finally:
        server.shutdown()

    assert 'alt="landing"' in html
    assert 'alt="pricing"' in html
    assert f"https://{_DOMAIN}/pricing" in html          # the page, not just the label
    assert "verification pass" in html                   # the extra frame is explained, not orphaned


# --- the engine side: a frame must earn its place before it is ever recorded -----------------

def _probe(url="https://alpha.example/pricing", ok=True, error=""):
    from core.scout.backends import PageObservation
    return PageObservation(url=url, final_url=url, status=200 if ok else 500, ok=ok,
                           fetch_error=error)


def _drop_or_keep(tmp_path, payload, *, verdict="meaningful", probe=None, kept=None, digests=None):
    from core.scout.engine import ScoutEngine
    (tmp_path / "page-02.png").write_bytes(payload)
    shots = kept if kept is not None else []
    ScoutEngine._keep_or_drop_frame(str(tmp_path), "page-02.png", "https://alpha.example/pricing",
                                    probe or _probe(), verdict, shots,
                                    digests if digests is not None else set())
    return shots, (tmp_path / "page-02.png").exists()


def test_a_frame_identical_to_the_landing_capture_is_never_recorded(tmp_path):
    """A live easybooking.sk run photographed its own landing page again through a nav link."""
    same = b"\x89PNG the landing page"
    landing_digest = __import__("hashlib").sha256(same).hexdigest()

    shots, still_on_disk = _drop_or_keep(tmp_path, same, digests={landing_digest})

    assert shots == [], "the landing page was recorded a second time as another page"
    assert not still_on_disk, "the duplicate frame was left behind on disk"


def test_a_genuinely_different_page_is_recorded_with_its_page_and_digest(tmp_path):
    shots, still_on_disk = _drop_or_keep(tmp_path, b"\x89PNG a different page", digests={"other"})

    assert still_on_disk
    assert shots[0]["role"] == "pricing"
    # The ENGINE's own screenshots.json record, not the client manifest — it keeps "url".
    assert shots[0]["url"] == "https://alpha.example/pricing"
    assert len(shots[0]["sha256"]) == 64


def test_a_near_duplicate_page_contributes_no_frame(tmp_path):
    shots, still_on_disk = _drop_or_keep(tmp_path, b"\x89PNG something", verdict="near_duplicate")

    assert shots == [] and not still_on_disk


def test_a_page_that_failed_to_load_contributes_no_frame(tmp_path):
    shots, still_on_disk = _drop_or_keep(tmp_path, b"\x89PNG something",
                                         probe=_probe(ok=False, error="timeout"))

    assert shots == [] and not still_on_disk


def test_an_incomplete_analysis_still_cannot_be_exported(tmp_path):
    """The pre-existing gate must survive this change untouched."""
    store = _run(tmp_path, frames={"landing.png": b"one"})
    store.save_state({"status": "COMPLETED", "prospects": {
        _PID: {"status": "MANUAL_ACTION_REQUIRED", "url": f"https://{_DOMAIN}/",
               "analysis_complete": False}}})

    with pytest.raises((ClientEvidenceError, Exception)):
        CampaignService(str(tmp_path)).export_client_evidence(_DOMAIN, run=_RUN)

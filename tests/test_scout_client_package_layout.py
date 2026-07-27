"""The package a client actually opens on Windows, double-clicking, offline.

A ZIP that only a developer can navigate is not a deliverable. The layout is therefore named for
what each file is rather than for how we stored it, dated so two months of packages do not collide
in a downloads folder, and rooted in one folder so extracting it does not scatter files across the
desktop.

Everything here is about what survives the trip: relative links that still resolve after extraction,
an offline report with no network dependency, a CSV a client can open in Excel, hashes that let
either side prove nothing changed — and a hard line between the client's package and the operator's
own notes. Talking points, the email draft and where we found the contact are ours, not theirs, and
one accidental forward of the wrong file is all it takes to matter.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import zipfile

import pytest

from core.scout.campaign_service import CampaignService
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.store import RunStore

RUN = "package-run"
DOMAIN = "plausible.io"
OTHER = "userlist.com"


@pytest.fixture()
def packaged(tmp_path):
    """One run holding two companies — so cross-target leakage is testable, not hypothetical."""
    out = str(tmp_path)
    store = RunStore(out, RUN)
    store.write_config({"campaign_name": "operator-scan", "browser_mode": "playwright",
                        "video_mode": "qualified_auto"})
    store.save_state({"status": "COMPLETED", "prospects": {
        "01": {"status": "DONE", "url": f"https://{DOMAIN}/"},
        "02": {"status": "DONE", "url": f"https://{OTHER}/"}}})
    for pid, domain, title in (("01", DOMAIN, "Checkout button does nothing on mobile"),
                               ("02", OTHER, "SECRET-OTHER-COMPANY-FINDING")):
        store.save_prospect_artifact(pid, "findings.json", {"verified": [{
            "finding_id": f"f-{pid}", "severity": "high", "category": "functional",
            "title": title, "business_impact": "Visitors cannot complete a purchase.",
            "url": f"https://{domain}/pricing", "confidence": "verified",
            "reproduction_steps": ["Open /pricing on a phone", "Tap Start free trial"],
            "evidence_refs": [f"prospects/{pid}/landing.png"]}], "rejected": []})
        store.save_prospect_artifact(pid, "observation.json", {
            "status": 200, "final_url": f"https://{domain}/contact",
            "links": [f"mailto:hello@{domain}"],
            "console_errors": [f"TypeError from {domain}"],
            "failed_resources": [f"https://{domain}/broken.js"],
            "axe_status": "ok",
            "axe_violations": [{"id": "image-alt", "impact": "serious",
                                "help": "Images must have alternate text"}],
            "perf": {"lcp_ms": 3400, "dcl_ms": 1200}, "timing_ms": {"total": 812}})
        pdir = store.prospect_dir(pid)
        (pdir / "landing.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(200))
        (pdir / "pricing.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(300))
        store.save_prospect_artifact(pid, "screenshots.json", {"frames": [
            {"file": "landing.png", "role": "landing", "url": f"https://{domain}/"},
            {"file": "pricing.png", "role": "pricing", "url": f"https://{domain}/pricing"}]})
        (pdir / "reproduction.webm").write_bytes(b"\x1a\x45\xdf\xa3" + bytes(400))
        store.save_prospect_artifact(pid, "reproduction.json", {"reproduced": True})
    AnalyzedSiteRegistry(out).record_analysis(
        DOMAIN, status=ANALYZED, evidence_ref=f"scout/{RUN}", campaign_id=RUN)
    result = CampaignService(out).export_client_evidence(DOMAIN, run=RUN)
    with zipfile.ZipFile(result["path"]) as archive:
        names = archive.namelist()
        blobs = {name: archive.read(name) for name in names}
    return {"result": result, "names": names, "blobs": blobs}


def _root(names) -> str:
    return names[0].split("/", 1)[0]


def _text(blobs, suffix: str) -> str:
    key = next(n for n in blobs if n.endswith(suffix))
    return blobs[key].decode("utf-8")


# --- the shape of the thing ----------------------------------------------------------------------

def test_the_zip_is_named_for_the_site_and_the_day(packaged):
    """Two packages for one client a month apart must not be the same filename twice."""
    import re
    assert re.fullmatch(r"plausible\.io-qa-evidence-\d{8}\.zip", packaged["result"]["filename"])


def test_everything_lives_under_one_dated_folder(packaged):
    """Extracting must produce one folder, not a scatter of loose files."""
    roots = {name.split("/", 1)[0] for name in packaged["names"]}

    assert len(roots) == 1
    assert _root(packaged["names"]).startswith("plausible.io-qa-evidence-")


def test_the_agreed_files_are_all_present(packaged):
    root = _root(packaged["names"])
    for expected in ("00-README.html", "QA-Report.html", "Findings.csv", "manifest.json",
                     "Evidence/Technical/accessibility-summary.json",
                     "Evidence/Technical/performance-summary.json",
                     "Evidence/Technical/console-summary.txt",
                     "Evidence/Technical/network-summary.json"):
        assert f"{root}/{expected}" in packaged["names"], expected


def test_screenshots_and_videos_are_in_their_own_folders(packaged):
    root = _root(packaged["names"])
    shots = [n for n in packaged["names"] if n.startswith(f"{root}/Evidence/Screenshots/")]
    videos = [n for n in packaged["names"] if n.startswith(f"{root}/Evidence/Videos/")]

    assert shots and all(n.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) for n in shots)
    assert videos and all(n.lower().endswith((".webm", ".mp4")) for n in videos)


# --- does it work after extraction ---------------------------------------------------------------

def test_the_report_links_are_relative_so_they_survive_extraction(packaged):
    report = _text(packaged["blobs"], "QA-Report.html")

    assert "Evidence/Screenshots/" in report
    assert 'href="/' not in report and 'src="/' not in report
    assert "file://" not in report
    assert "http://127.0.0.1" not in report and "localhost" not in report


def test_the_report_needs_no_network_to_render(packaged):
    """A client opening it offline must see the whole thing, not a broken layout."""
    report = _text(packaged["blobs"], "QA-Report.html")

    assert "<style>" in report
    for remote in ("<script src=", 'href="http', "cdn.", "googleapis", "@import url(http"):
        assert remote not in report, remote


def test_the_readme_explains_what_to_open_first(packaged):
    readme = _text(packaged["blobs"], "00-README.html")

    assert "QA-Report.html" in readme
    assert "Findings.csv" in readme


def test_findings_csv_opens_in_a_spreadsheet(packaged):
    key = next(n for n in packaged["blobs"] if n.endswith("Findings.csv"))
    blob = packaged["blobs"][key]
    # Excel on Windows reads a BOM-less UTF-8 CSV in the system codepage and mojibakes every
    # accented character, so the BOM is deliberate. Decode it the way a consumer would.
    assert blob.startswith(b"\xef\xbb\xbf"), "no UTF-8 BOM: Excel would mangle non-ASCII text"
    assert b"\r\n" in blob, "CSV rows must be CRLF-terminated for Excel"
    rows = list(csv.reader(io.StringIO(blob.decode("utf-8-sig"))))

    assert rows[0] == ["Severity", "Category", "Title", "Impact", "Page", "How to reproduce",
                       "Evidence", "Confidence"]
    assert any("Checkout button does nothing on mobile" in row[2] for row in rows[1:])


def test_no_absolute_local_path_escapes_into_the_package(packaged):
    joined = " ".join(
        blob.decode("utf-8", "ignore") for name, blob in packaged["blobs"].items()
        if name.endswith((".html", ".json", ".csv", ".txt")))

    assert "C:\\" not in joined and "C:/" not in joined
    assert "/Users/" not in joined and "AppData" not in joined


def test_member_names_are_safe_for_windows(packaged):
    for name in packaged["names"]:
        assert ".." not in name.split("/")
        assert not name.startswith("/")
        for part in name.split("/"):
            assert not set(part) & set('<>:"|?*\\'), name
            assert not part.endswith((" ", "."))


# --- the manifest ---------------------------------------------------------------------------------

def test_the_manifest_lets_either_side_prove_nothing_changed(packaged):
    root = _root(packaged["names"])
    manifest = json.loads(_text(packaged["blobs"], "manifest.json"))
    by_path = {entry["path"]: entry for entry in manifest["entries"]}

    assert by_path, "the manifest lists no files"
    for path, entry in by_path.items():
        member = packaged["blobs"][f"{root}/{path}"]
        assert entry["sha256"] == hashlib.sha256(member).hexdigest(), path
        assert entry["bytes"] == len(member), path
        assert entry["mime"], path


def test_the_manifest_records_where_the_package_came_from(packaged):
    manifest = json.loads(_text(packaged["blobs"], "manifest.json"))

    assert manifest["domain"] == DOMAIN
    assert manifest["target_id"] == DOMAIN
    assert manifest["run_id"] == RUN
    assert manifest["generated_at"]
    assert manifest["build"]
    # Our internal prospect numbering identifies us, not the client's site, and this file leaves
    # the building.
    assert "prospect_id" not in manifest


def test_screenshot_entries_name_the_page_they_show(packaged):
    manifest = json.loads(_text(packaged["blobs"], "manifest.json"))
    shots = [e for e in manifest["entries"] if e["path"].startswith("Evidence/Screenshots/")]

    assert shots
    assert all(e.get("page_url") for e in shots)


def test_findings_are_referenced_from_the_manifest(packaged):
    manifest = json.loads(_text(packaged["blobs"], "manifest.json"))

    assert manifest["findings"]
    assert manifest["findings"][0]["title"] == "Checkout button does nothing on mobile"


# --- the line between the client's package and the operator's notes ------------------------------

def test_no_other_company_appears_anywhere_in_the_package(packaged):
    joined = " ".join(blob.decode("utf-8", "ignore") for blob in packaged["blobs"].values())

    assert "SECRET-OTHER-COMPANY-FINDING" not in joined
    assert OTHER not in joined


def test_the_operators_own_notes_stay_out_of_it(packaged):
    """Talking points, the draft and contact provenance are operator text, not client deliverables."""
    joined = " ".join(
        blob.decode("utf-8", "ignore") for name, blob in packaged["blobs"].items()
        if name.endswith((".html", ".json", ".csv", ".txt")))

    for internal in ("Talking points", "hello@plausible.io", "Hi,", "no obligation",
                     "Public mailto link", "happy to share the evidence"):
        assert internal.lower() not in joined.lower(), internal


def test_the_package_is_never_marked_approved_to_send(packaged):
    manifest = json.loads(_text(packaged["blobs"], "manifest.json"))

    assert manifest.get("approved_for_client_delivery") is False
    assert manifest.get("review_before_sending") is True

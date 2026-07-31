"""M3 part A — a client-facing finding must carry the basis for its own verdict.

The store records what was expected, what was actually observed, the honest limit of the automated
check, and the environment it ran in. ``_public_finding()`` then dropped all four, so a delivered
package asserted a severity with no observed/expected pair, no threshold behind a performance
judgement, and no statement of what the check does not cover. The store was honest; the deliverable
was not.

Measured over all 433 stored findings before writing this: ``environment`` is populated in 433,
``actual`` in 316, ``expected`` in 286, ``coverage_limitation`` in 117. So this is not a theoretical
gap — two thirds of findings really do carry an expected/actual pair that the client never saw.

What is deliberately NOT asserted here: ``evidence_refs``. Every one of those 433 findings points at
the same generic ``prospects/<id>/evidence.json``, so carrying it through would fill the CSV's
Evidence column with one identical path per row — populated and still meaningless. That is a product
decision, raised separately, and this file must not pre-empt it.

The last two tests are the guards that make the change safe: nothing the client receives may carry a
run id, an internal path or an operator reference, and a field that is empty in the store must not
appear as an empty key in the projection.
"""
from __future__ import annotations

import csv as _csv
import io as _io
import json as _json
import zipfile as _zipfile

import pytest

from core.scout.campaign_service import CampaignService
from core.scout.client_evidence import _public_finding
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.store import RunStore

# A finding shaped exactly like the ones on disk, with every dropped field populated.
STORED = {
    "finding_id": "f-3ad7fee96821",
    "signature": "broken_link:https://example.com/booking",
    "severity": "medium",
    "category": "Navigation",
    "title": "Broken link",
    "business_impact": "Visitors reach a dead end.",
    "url": "https://example.com/booking",
    "confidence": "high",
    "reproduction_steps": ["Open https://example.com/", "Click Booking"],
    "kind": "actionable",
    "expected": "Link resolves (2xx/3xx)",
    "actual": "Link returned no response",
    "coverage_limitation": "automated checks are not full accessibility coverage",
    "environment": {"backend": "playwright", "status": 200},
    "evidence_refs": ["prospects/01-example-com/evidence.json"],
    "run_id": "campaign-real-20260720t100000z-abc123",
    "prospect_ref": "prospects/01-example-com",
    "verification_state": "verified",
    "notes": "internal operator note",
    "sanitized": True,
    "is_client_safe": True,
    "check_family": "links",
}


def test_the_client_sees_what_was_expected_and_what_happened():
    """A severity without an observed/expected pair is an assertion, not a finding."""
    public = _public_finding(STORED)
    assert public.get("expected") == "Link resolves (2xx/3xx)", (
        "the client receives a medium-severity verdict with no statement of what was expected"
    )
    assert public.get("actual") == "Link returned no response", (
        "the client receives a verdict with no statement of what was actually observed"
    )


def test_the_client_sees_the_limit_of_the_automated_check():
    """The one sentence that tells a client not to read the scan as full coverage."""
    public = _public_finding(STORED)
    assert public.get("coverage_limitation") == (
        "automated checks are not full accessibility coverage"
    ), "the honest limitation is recorded in the store and deleted from the deliverable"


def test_the_client_sees_the_environment_the_observation_came_from():
    """"On what" is part of any QA report; it is populated on every stored finding."""
    public = _public_finding(STORED)
    assert public.get("environment") == {"backend": "playwright", "status": 200}, (
        "the client cannot tell which browser and response the observation came from"
    )


def test_nothing_internal_leaks_into_the_client_projection():
    """The guard that keeps the fix safe: the projection is still a projection."""
    public = _public_finding(STORED)
    forbidden = {"run_id", "prospect_ref", "signature", "notes", "verification_state",
                 "sanitized", "is_client_safe", "check_family"}
    leaked = forbidden & set(public)
    assert not leaked, f"internal fields reached the client projection: {sorted(leaked)}"
    blob = repr(public)
    for marker in ("campaign-real-", "prospects/", "internal operator note"):
        assert marker not in blob, f"{marker!r} reached the client projection"


def test_an_empty_field_is_still_omitted_rather_than_shipped_blank():
    """Two thirds of findings carry an expected/actual pair; the rest must not ship empty keys."""
    sparse = dict(STORED, expected="", actual="", coverage_limitation="", environment={})
    public = _public_finding(sparse)
    for key in ("expected", "actual", "coverage_limitation", "environment"):
        assert key not in public, (
            f"{key!r} is empty in the store and would ship as a blank field, which reads as "
            "'we checked and there was nothing' rather than 'we did not record this'"
        )


def test_evidence_refs_is_still_not_carried():
    """Deliberate, and pinned so a later change is a decision rather than a drift.

    All 433 stored findings point at the same generic per-prospect evidence.json, so carrying this
    through would fill the client's Evidence column with one identical path per row. Whether that
    column should exist at all is a product decision raised with the reviewer; until it is answered,
    this file must not smuggle in an answer.
    """
    public = _public_finding(STORED)
    assert "evidence_refs" not in public, (
        "evidence_refs entered the client projection while the Evidence-column decision is still "
        "open; per-finding evidence linkage does not exist in the product, and a column that "
        "repeats one path on every row is not evidence"
    )


# --- M3 parts 2-4: the package a client actually receives -----------------------------------------
#
# The tests above pin the projection. These build a REAL package through the production exporter and
# read the delivered bytes, because the contract is about what four surfaces say to a client, not
# about what one function returns.

_RUN = "campaign-basis-20260730t120000z-aa11bb"
_DOMAIN = "example-client.test"


@pytest.fixture()
def delivered(tmp_path):
    """A package built by the production exporter, opened as a client would open it."""
    out = str(tmp_path)
    store = RunStore(out, _RUN)
    store.write_config({"campaign_name": "operator-scan", "browser_mode": "playwright"})
    store.save_state({"status": "COMPLETED",
                      "prospects": {"01": {"status": "DONE", "url": f"https://{_DOMAIN}/"}}})
    store.save_prospect_artifact("01", "findings.json", {"verified": [
        {"finding_id": "f-basis-01", "severity": "high", "category": "Navigation",
         "title": "Broken link on the booking page",
         "business_impact": "Visitors reach a dead end.",
         "url": f"https://{_DOMAIN}/booking", "confidence": "verified",
         "reproduction_steps": ["Open /booking", "Click Reserve"],
         "expected": "Link resolves (2xx/3xx)", "actual": "Link returned no response",
         "environment": {"backend": "playwright", "status": 200},
         "coverage_limitation": "automated checks are not full accessibility coverage",
         "evidence_refs": ["prospects/01/evidence.json"]},
        {"finding_id": "f-basis-02", "severity": "info", "category": "Coverage",
         "title": "Heuristic a11y checks yielded to axe-core",
         "business_impact": "", "url": f"https://{_DOMAIN}/",
         "confidence": "verified", "reproduction_steps": [],
         "coverage_limitation": "axe-core ran; automated checks are not full coverage",
         "evidence_refs": ["prospects/01/evidence.json"]}], "rejected": []})
    store.save_prospect_artifact("01", "observation.json", {
        "status": 200, "final_url": f"https://{_DOMAIN}/", "links": [], "console_errors": [],
        "failed_resources": [], "axe_status": "ok", "axe_violations": [],
        "perf": {"lcp_ms": 1200}, "timing_ms": {"total": 300}})
    pdir = store.prospect_dir("01")
    (pdir / "landing.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(200))
    store.save_prospect_artifact("01", "screenshots.json", {"frames": [
        {"file": "landing.png", "role": "landing", "url": f"https://{_DOMAIN}/"}]})
    AnalyzedSiteRegistry(out).record_analysis(
        _DOMAIN, status=ANALYZED, evidence_ref=f"scout/{_RUN}", campaign_id=_RUN)
    result = CampaignService(out).export_client_evidence(_DOMAIN, run=_RUN)
    with _zipfile.ZipFile(result["path"]) as archive:
        blobs = {name: archive.read(name) for name in archive.namelist()}
    return blobs


def _blob(blobs, suffix: str) -> str:
    return blobs[next(n for n in blobs if n.endswith(suffix))].decode("utf-8")


def test_the_csv_carries_a_finding_id_and_no_evidence_column(delivered):
    """Option 2: the column that could never be filled is replaced by the one handle that is real."""
    rows = list(_csv.reader(_io.StringIO(_blob(delivered, "Findings.csv").lstrip("﻿"))))
    header = rows[0]
    assert "Finding ID" in header, f"no Finding ID column: {header}"
    assert "Evidence" not in header, (
        "the Evidence column is still advertised; it read evidence_refs off the projection and was "
        f"empty in all 21 produced packages: {header}"
    )
    body = [r for r in rows[1:] if r]
    assert body, "no finding rows"
    ids = [r[header.index("Finding ID")] for r in body]
    assert all(ids), f"a finding shipped without its id: {ids}"


def test_the_csv_states_what_was_expected_and_observed(delivered):
    rows = list(_csv.DictReader(_io.StringIO(_blob(delivered, "Findings.csv").lstrip("﻿"))))
    broken = next(r for r in rows if r["Finding ID"] == "f-basis-01")
    assert broken["Expected"] == "Link resolves (2xx/3xx)"
    assert broken["Actual"] == "Link returned no response"


def test_the_human_report_shows_the_basis_not_only_the_json(delivered):
    """A client reads QA-Report.html; the basis living in a sibling JSON is not the same thing."""
    report = _blob(delivered, "QA-Report.html")
    assert "f-basis-01" in report, "the report does not print the Finding ID"
    for fragment in ("Link resolves (2xx/3xx)", "Link returned no response",
                     "playwright", "automated checks are not full"):
        assert fragment in report, f"the report omits {fragment!r} — the verdict is unchecked"


def test_the_same_finding_id_appears_on_every_surface(delivered):
    """One handle, four surfaces: CSV, HTML, technical JSON, manifest."""
    rows = list(_csv.DictReader(_io.StringIO(_blob(delivered, "Findings.csv").lstrip("﻿"))))
    csv_ids = {r["Finding ID"] for r in rows}
    technical = _json.loads(_blob(delivered, "Evidence/Technical/findings.json"))
    items = technical if isinstance(technical, list) else technical.get("findings", [])
    json_ids = {f.get("finding_id") for f in items}
    manifest = _json.loads(_blob(delivered, "manifest.json"))
    manifest_ids = {f.get("finding_id") for f in manifest.get("findings", [])}
    report = _blob(delivered, "QA-Report.html")

    assert csv_ids == json_ids == manifest_ids, (
        f"the surfaces disagree about which findings exist: csv={csv_ids} json={json_ids} "
        f"manifest={manifest_ids}"
    )
    for fid in csv_ids:
        assert fid in report, f"{fid} is missing from the human report"


def test_the_manifest_makes_no_per_finding_evidence_claim(delivered):
    """evidence_refs is one target-wide file, so a per-finding evidence array can only mislead."""
    manifest = _json.loads(_blob(delivered, "manifest.json"))
    for finding in manifest.get("findings", []):
        assert "evidence" not in finding, (
            f"the manifest still claims per-finding evidence: {finding}"
        )


def test_the_readme_does_not_promise_that_a_screenshot_proves_a_finding(delivered):
    readme = _blob(delivered, "00-README.html")
    assert "with the screenshots that show them" not in readme, (
        "the README still promises per-finding screenshots the product cannot link"
    )
    assert "supporting material" in readme, (
        "the README does not say what the Evidence folders actually are"
    )

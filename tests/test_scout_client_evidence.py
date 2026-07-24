"""Client-ready Scout evidence is exact-target, bounded, downloadable, and safe by default."""
from __future__ import annotations

import io
import json
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

import pytest

from core.scout.campaign_service import CampaignService
from core.scout.client_evidence import ClientEvidenceError
from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService
from core.scout.store import RunStore

_RUN = "client-evidence-run"


def _build_run(tmp_path, *, status="DONE", secret_title=""):
    store = RunStore(str(tmp_path), _RUN)
    store.write_config({
        "campaign_name": "curated",
        "browser_mode": "playwright",
        "video_mode": "qualified_auto",
    })
    store.save_state({"status": "COMPLETED", "prospects": {
        "01-alpha-internal": {
            "status": status,
            "url": "https://alpha.example/",
            "verified_findings": 1 if status == "DONE" else 0,
            "verified_defects": 1 if status == "DONE" else 0,
        },
        "02-beta-internal": {
            "status": "DONE",
            "url": "https://beta.example/",
            "verified_findings": 1,
            "verified_defects": 1,
        },
    }})
    for pid, domain in (
        ("01-alpha-internal", "alpha.example"),
        ("02-beta-internal", "beta.example"),
    ):
        title = secret_title if pid.startswith("01-") and secret_title else f"{domain} broken link"
        store.save_prospect_artifact(pid, "findings.json", {"verified": [{
            "finding_id": f"private-{pid}",
            "run_id": _RUN,
            "prospect_ref": pid,
            "severity": "high",
            "category": "functional",
            "title": title,
            "business_impact": "Customers cannot continue.",
            "url": f"https://{domain}/checkout",
            "confidence": "high",
            "reproduction_steps": ["Open checkout", "Select Continue"],
            "evidence_refs": [f"prospects/{pid}/landing.png"],
        }], "rejected": []})
        store.save_prospect_artifact(pid, "coverage.json", {
            "coverage": "adaptive",
            "page_ceiling": 12,
            "meaningful_pages_tested": 3,
            "page_stop_reason": "links_exhausted",
            "private_future_field": f"do-not-export-{pid}",
        })
        store.save_prospect_artifact(pid, "observation.json", {
            "status": 200,
            "final_url": f"https://{domain}/",
            "headers": {"server": "private-raw-header"},
            "raw_headers_stored": False,
            "console_errors": ["TypeError: checkout failed"],
            "failed_resources": [f"https://{domain}/broken.js"],
            "axe_status": "ok",
            "axe_violations": [{"id": "button-name", "impact": "serious"}],
        })
        store.save_prospect_artifact(pid, "browser_trace.json", {
            "schema_version": 1,
            "redaction_applied": True,
            "raw_dom_stored": False,
            "raw_headers_stored": False,
            "future_internal_field": f"do-not-export-{pid}",
            "passes": [{
                "pass": "landing",
                "url": f"https://{domain}/",
                "final_url": f"https://{domain}/",
                "status": 200,
                "ok": True,
                "screenshot_ref": "landing.png",
                "timing_ms": {"load": 410},
                "console_errors": [],
                "failed_resources": [],
                "blocked_requests": [],
                "private": "do-not-export",
            }],
        })
        (store.prospect_dir(pid) / "landing.png").write_bytes(
            b"alpha-image" if pid.startswith("01-") else b"beta-image")
    store.save_prospect_artifact("01-alpha-internal", "reproduction.json", {
        "finding_id": "private-finding-id",
        "signature": "private-signature",
        "start_url": "https://alpha.example/",
        "action_url": "https://alpha.example/checkout",
        "action_log": ["open checkout", "select Continue"],
        "cleanup_ok": True,
        "reproduced": True,
        "reproduction_status": "reproduced",
        "video_ref": "reproduction.webm",
    })
    (store.prospect_dir("01-alpha-internal") / "reproduction.webm").write_bytes(
        b"alpha-video")
    return store


def _zip_files(payload: bytes):
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_client_bundle_is_target_scoped_and_excludes_operator_raw_data(tmp_path):
    _build_run(tmp_path)
    result = CampaignService(str(tmp_path)).export_client_evidence(
        "alpha.example", run=_RUN)
    files = _zip_files(Path(result["path"]).read_bytes())

    assert {
        "QA_Evidence_Summary.html",
        "QA_Evidence_Summary.md",
        "MANIFEST.json",
        "technical/findings.json",
        "technical/coverage.json",
        "technical/network-console-accessibility.json",
        "technical/reproduction.json",
        "technical/browser-event-trace.json",
        "evidence/screenshots/screenshot-01.png",
        "evidence/reproduction/reproduction-01.webm",
    } <= set(files)
    blob = b"\n".join(files.values())
    assert b"alpha-image" in blob and b"alpha-video" in blob
    assert b"beta-image" not in blob and b"beta.example" not in blob
    for forbidden in (
        b"01-alpha-internal",
        b"client-evidence-run",
        b"private-finding-id",
        b"private-signature",
        b"private-raw-header",
        b"do-not-export",
        b"observation.json",
        b"scorecard.json",
        b"evidence_refs",
    ):
        assert forbidden not in blob
    manifest = json.loads(files["MANIFEST.json"])
    assert manifest["domain"] == "alpha.example"
    assert manifest["client_oriented_scope"] is True
    assert manifest["structured_content_secret_scanned"] is True
    assert manifest["visual_review_required"] is True
    assert all(len(row["sha256"]) == 64 for row in manifest["entries"])
    assert result["bytes"] < 20 * 1024 * 1024
    with zipfile.ZipFile(result["path"]) as archive:
        assert sum(item.file_size for item in archive.infolist()) <= 20 * 1024 * 1024


def test_dashboard_download_is_an_attachment_and_target_page_links_it(tmp_path):
    _build_run(tmp_path)
    service = ScoutService(str(tmp_path))
    service.attach(_RUN)
    server, url = start_dashboard(service, operator_home=True)
    try:
        with urllib.request.urlopen(
            f"{url}/scout/target?run={_RUN}&domain=alpha.example", timeout=5
        ) as response:
            page = response.read().decode("utf-8")
        with urllib.request.urlopen(
            f"{url}/scout/client-evidence?run={_RUN}&domain=alpha.example", timeout=5
        ) as response:
            payload = response.read()
            disposition = response.headers.get("Content-Disposition", "")
            cache = response.headers.get("Cache-Control", "")
            content_type = response.headers.get("Content-Type", "")
    finally:
        server.shutdown()
        server.server_close()
    assert "Download client-ready evidence (.zip)" in page
    assert "One target · client-oriented · review required · up to 20 MiB" in page
    assert content_type == "application/zip"
    assert 'attachment; filename="alpha.example-qa-evidence.zip"' == disposition
    assert cache == "no-store"
    files = _zip_files(payload)
    assert "QA_Evidence_Summary.html" in files


def test_incomplete_target_cannot_be_exported_as_client_evidence(tmp_path):
    _build_run(tmp_path, status="MANUAL_ACTION_REQUIRED")
    with pytest.raises(ClientEvidenceError, match="completed analysis"):
        CampaignService(str(tmp_path)).export_client_evidence(
            "alpha.example", run=_RUN)

    service = ScoutService(str(tmp_path))
    service.attach(_RUN)
    server, url = start_dashboard(service, operator_home=True)
    try:
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(
                f"{url}/scout/client-evidence?run={_RUN}&domain=alpha.example",
                timeout=5,
            )
    finally:
        server.shutdown()
        server.server_close()
    assert exc.value.code == 409


def test_secret_bearing_structured_content_blocks_the_export(tmp_path):
    _build_run(tmp_path, secret_title="token ghp_abcdefghijklmnopqrstuvwxyz123456")
    with pytest.raises(ClientEvidenceError, match="secret scan"):
        CampaignService(str(tmp_path)).export_client_evidence(
            "alpha.example", run=_RUN)

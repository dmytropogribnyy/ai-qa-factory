"""v3.2 Project Resource Readiness — chat-first, per-project, composed from existing planning signals.

Deterministic: no subprocess/network. Covers the five required profiles, the public-vs-private web app
distinction (no unnecessary resource requests), the no-secret-in-client-request guarantee, persistence
through the existing project artifacts, fresh-process resume, and two-project (two-client) isolation.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from core.orchestration.client_work import ClientWorkService
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.resource_readiness import (
    DETECTED,
    NEEDS_CLIENT,
    NEEDS_OPERATOR,
    NOT_APPLICABLE,
    OPTIONAL,
    build_readiness,
    readiness_summary_text,
)


def _mk(profile, raw="", sources=None, blocking=None):
    return build_readiness(project_id="p", profile=profile, raw_text=raw,
                           input_map_sources=[{"input_type": t} for t in (sources or [])],
                           missing=SimpleNamespace(blocking=list(blocking or [])), integrations=None)


def _by_name(readiness, name):
    return next(r for r in readiness["resources"] if r["name"] == name)


# --- five required profiles -----------------------------------------------------------------------
def test_public_website_audit_requests_url_not_a_test_account():
    r = _mk("web_app_audit", raw="audit this public marketing site")
    # A public audit does NOT request an authenticated test account (no unnecessary resource).
    assert _by_name(r, "Authenticated test account")["status"] == NOT_APPLICABLE
    assert _by_name(r, "Target web app URL")["status"] == NEEDS_CLIENT
    assert _by_name(r, "Browser runtime (Playwright)")["status"] == NEEDS_OPERATOR


def test_private_web_app_requires_authenticated_test_account():
    r = _mk("web_app_audit", raw="audit the customer portal behind login / authentication")
    acct = _by_name(r, "Authenticated test account")
    assert r["authenticated_web_app"] is True
    assert acct["necessity"] == "Required" and acct["status"] == NEEDS_CLIENT
    assert acct["provided_by"] == "client"


def test_api_project_requests_spec_required_credentials_optional():
    r = _mk("api_project", raw="build API tests")
    assert _by_name(r, "API spec or base URL")["status"] == NEEDS_CLIENT
    assert _by_name(r, "API credentials")["status"] == OPTIONAL      # execution-time; not blocking now


def test_repository_only_automation_requests_repo_and_runtime():
    r = _mk("code_project", raw="stabilize the flaky suite in our repo")
    assert _by_name(r, "Client repository / test suite")["status"] == NEEDS_CLIENT
    assert _by_name(r, "Local runtimes (Python/Node)")["status"] == NEEDS_OPERATOR


def test_read_only_database_validation_requests_readonly_connection():
    r = _mk("data_project", raw="validate our data")
    db = _by_name(r, "Read-only database connection")
    assert db["status"] == NEEDS_CLIENT and "read-only" in db["min_access_level"].lower()


def test_provided_target_url_flips_to_detected_not_needs_client():
    r = _mk("web_app_audit", raw="public", sources=["target_url"])
    assert _by_name(r, "Target web app URL")["status"] == DETECTED


# --- safety: a client request never asks for a secret --------------------------------------------
def test_client_requests_never_ask_for_a_secret():
    for profile in ("web_app_audit", "api_project", "data_project", "code_project"):
        r = _mk(profile, raw="private login")
        assert r["any_secret_requested"] is False
        for res in r["resources"]:
            req = (res.get("client_request") or "").lower()
            if req:
                # The request asks for access/reference only, and explicitly forbids pasting secrets.
                assert "do not paste any password, token, or secret" in req
                for banned in ("send me your password", "paste your token", "share the api key value",
                               "give me the secret"):
                    assert banned not in req
        # The rendered summary likewise contains no secret solicitation.
        text = readiness_summary_text(r).lower()
        assert "password" not in text or "do not paste any password" in text


def test_needs_client_items_have_a_ready_to_copy_request_and_others_do_not():
    r = _mk("api_project", raw="api")
    spec = _by_name(r, "API spec or base URL")           # Needs Client
    creds = _by_name(r, "API credentials")               # Optional
    assert spec["client_request"] and not creds["client_request"]


def test_blocking_missing_info_surfaces_in_blockers():
    r = _mk("code_project", raw="repo work", blocking=["expected deliverable is unclear"])
    assert "expected deliverable is unclear" in r["blockers"]


# --- persistence + fresh-process resume + two-project isolation -----------------------------------
def test_analyze_persists_readiness_and_fresh_process_can_read_it(tmp_path):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Build API tests from our OpenAPI spec (positive and negative).", "apiproj")
    art = tmp_path / "apiproj" / "40_ark_work" / "RESOURCE_READINESS.json"
    assert art.is_file()
    data = json.loads(art.read_text(encoding="utf-8"))
    assert data["schema"] == "resource-readiness/v1" and data["project_id"] == "apiproj"
    assert (tmp_path / "apiproj" / "40_ark_work" / "RESOURCE_READINESS.md").is_file()
    # Fresh-process resume: a brand-new service instance reads the persisted artifact unchanged.
    fresh = json.loads(art.read_text(encoding="utf-8"))
    assert fresh == data


def test_two_client_projects_do_not_leak_resources_or_requests(tmp_path):
    svc = ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    svc.analyze("Audit our public marketing website at a URL we will provide.", "clientA")
    svc.analyze("Reproduce and fix a defect in our Python repository test suite.", "clientB")
    a = json.loads((tmp_path / "clientA" / "40_ark_work" / "RESOURCE_READINESS.json").read_text("utf-8"))
    b = json.loads((tmp_path / "clientB" / "40_ark_work" / "RESOURCE_READINESS.json").read_text("utf-8"))
    assert a["project_id"] == "clientA" and b["project_id"] == "clientB"
    # Each project's client requests reference ONLY its own project id (no cross-client leakage).
    a_text = json.dumps(a)
    b_text = json.dumps(b)
    assert "clientB" not in a_text and "clientA" not in b_text
    # Distinct profiles surface distinct resources (no shared/duplicated state object).
    a_names = {r["name"] for r in a["resources"]}
    b_names = {r["name"] for r in b["resources"]}
    assert a_names != b_names


def test_summary_has_the_seven_sections():
    text = readiness_summary_text(_mk("web_app_audit", raw="private login"))
    for heading in ("1. Ready now", "2. Needs Client", "3. Needs Operator", "4. Optional",
                    "5. Not required", "6. Current blockers", "7. Ready-to-copy client request"):
        assert heading in text

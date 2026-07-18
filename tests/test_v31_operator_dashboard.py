"""v3.1 - operator dashboard routes, shared guard, guarded work mutations (no argv over HTTP).

Extends the single existing dashboard (`core/scout/dashboard.py`). Every state-changing endpoint is
behind the shared guard (loopback Host + Origin + CSRF); no endpoint accepts a command/argv.
"""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request

from core.orchestration.client_work import ClientWorkService
from core.orchestration.operator_executor import OperatorWorkspaceExecutor, ProducedArtifact
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionService
from core.schemas.work_execution import ValidationOutcome
from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService

_BRIEF = "Reproduce and fix a defect in a small Python module and add a regression test."


def _passing(_c):
    return ValidationOutcome(passed=True, tests_run=1, tests_passed=1)


def _seed_ready_for_review(tmp_path, pid="alpha"):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(_BRIEF, pid)
    ws = tmp_path / pid / "40_ark_work"
    (ws / "fix.py").write_text("x = 1\n", encoding="utf-8")
    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    svc.approve(pid, reviewer="op")
    ex = OperatorWorkspaceExecutor([ProducedArtifact("fix.py", "fix")], _passing)
    svc.execute(pid, ex)
    svc.validate(pid, ex)
    return svc


def _dash(tmp_path):
    return start_dashboard(ScoutService(str(tmp_path)), operator_home=True)


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8"), dict(r.headers)


def _post(url, token, body):
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "X-Scout-CSRF": token})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def _post_raw(base, path, headers, body=b"{}"):
    """Raw request so we can spoof the Host header (DNS-rebinding defense)."""
    host, port = base.replace("http://", "").split(":")
    conn = http.client.HTTPConnection(host, int(port), timeout=5)
    conn.request("POST", path, body=body, headers=headers)
    resp = conn.getresponse()
    out = json.loads(resp.read().decode("utf-8"))
    conn.close()
    return resp.status, out


def test_all_primary_pages_render_with_csp(tmp_path):
    _seed_ready_for_review(tmp_path)
    server, url = _dash(tmp_path)
    try:
        # New operator pages use the shared layout (<main>) + design tokens.
        for path in ["/", "/work", "/work/alpha", "/tools", "/activity", "/settings", "/docs"]:
            status, body, headers = _get(url + path)
            assert status == 200 and "<main>" in body, path
            assert "default-src 'self'" in headers.get("Content-Security-Policy", ""), path
        # /scout reuses the existing (preserved) Scout view; it still renders under CSP.
        status, body, headers = _get(url + "/scout")
        assert status == 200 and "Prospect QA Scout" in body
        assert "default-src 'self'" in headers.get("Content-Security-Policy", "")
    finally:
        server.shutdown()


def test_overview_inbox_shows_attention(tmp_path):
    _seed_ready_for_review(tmp_path)
    server, url = _dash(tmp_path)
    try:
        _, ov, _ = _get(url + "/")
        assert "Overview" in ov and "Ready for review" in ov
        _, api, _ = _get(url + "/api/overview")
        data = json.loads(api)
        assert data["schema"].startswith("dashboard-read-model")
        assert any(a["project_id"] == "alpha" for a in data["attention"])
    finally:
        server.shutdown()


def test_work_list_json_and_filters(tmp_path):
    _seed_ready_for_review(tmp_path)
    server, url = _dash(tmp_path)
    try:
        _, api, _ = _get(url + "/api/work?view=ready_for_review")
        data = json.loads(api)
        assert data["view"] == "ready_for_review"
        assert all(p["status"] == "READY_FOR_REVIEW" for p in data["projects"])
        _, detail, _ = _get(url + "/api/work/alpha")
        d = json.loads(detail)
        assert d["header"]["status"] == "READY_FOR_REVIEW"
        assert d["primary_action"]["id"] == "review_approve"
    finally:
        server.shutdown()


def test_guarded_work_mutation_advances_lifecycle(tmp_path):
    _seed_ready_for_review(tmp_path)
    server, url = _dash(tmp_path)
    try:
        status, j = _post(url + "/api/work/review", server.scout_csrf_token,
                          {"project_id": "alpha", "reviewer": "op"})
        assert status == 200 and j["status"] == "READY_FOR_DELIVERY"
        status, j = _post(url + "/api/work/prepare-delivery", server.scout_csrf_token,
                          {"project_id": "alpha"})
        assert status == 200 and j["status"] == "DELIVERY_PREPARED"
    finally:
        server.shutdown()


def test_work_mutation_ignores_any_command_field(tmp_path):
    # A client cannot smuggle a command/argv through a work mutation: only reviewer/note/reason are
    # read, and there is no validate/record-execution endpoint over HTTP.
    _seed_ready_for_review(tmp_path)
    server, url = _dash(tmp_path)
    try:
        status, j = _post(url + "/api/work/review", server.scout_csrf_token,
                          {"project_id": "alpha", "reviewer": "op",
                           "command": ["rm", "-rf", "/"], "argv": ["danger"]})
        assert status == 200 and j["status"] == "READY_FOR_DELIVERY"   # command ignored, review ran
        # There is no argv/command endpoint at all.
        status, _ = _post(url + "/api/work/validate", server.scout_csrf_token,
                          {"project_id": "alpha", "argv": ["python", "-c", "print(1)"]})
        assert status in (404, 409)     # unknown work action; never executes a command
    finally:
        server.shutdown()


def test_work_mutation_requires_csrf(tmp_path):
    _seed_ready_for_review(tmp_path)
    server, url = _dash(tmp_path)
    try:
        req = urllib.request.Request(url + "/api/work/review", method="POST", data=b"{}",
                                     headers={"Content-Type": "application/json"})
        try:
            urllib.request.urlopen(req, timeout=5)
            raise AssertionError("expected 403")
        except urllib.error.HTTPError as e:
            assert e.code == 403 and "CSRF" in e.read().decode("utf-8")
    finally:
        server.shutdown()


def test_work_mutation_refuses_dns_rebinding_and_cross_origin(tmp_path):
    _seed_ready_for_review(tmp_path)
    server, url = _dash(tmp_path)
    token = server.scout_csrf_token
    try:
        # A rebound request carries a non-loopback Host -> refused.
        status, body = _post_raw(url, "/api/work/review",
                                 {"Host": "attacker.example", "X-Scout-CSRF": token,
                                  "Content-Type": "application/json"},
                                 json.dumps({"project_id": "alpha", "reviewer": "op"}).encode())
        assert status == 403 and "loopback" in body["error"]
        # A cross-origin browser POST -> refused.
        host = url.replace("http://", "")
        status, body = _post_raw(url, "/api/work/review",
                                 {"Host": host, "Origin": "http://evil.example",
                                  "X-Scout-CSRF": token, "Content-Type": "application/json"},
                                 json.dumps({"project_id": "alpha", "reviewer": "op"}).encode())
        assert status == 403 and "cross-origin" in body["error"]
    finally:
        server.shutdown()


def test_analyze_creates_a_project_from_pasted_brief(tmp_path):
    server, url = _dash(tmp_path)
    try:
        status, j = _post(url + "/api/work/analyze", server.scout_csrf_token,
                          {"text": _BRIEF, "project_id": "fromdash", "source_platform": "manual"})
        assert status == 200 and j["ok"] and j["project_id"] == "fromdash"
        assert (tmp_path / "fromdash" / "40_ark_work" / "WORK_RUN_STATE.json").exists()
    finally:
        server.shutdown()


def test_unknown_project_detail_is_not_found(tmp_path):
    server, url = _dash(tmp_path)
    try:
        status, body, _ = _get(url + "/work/nope")
        assert status == 200 and "Project not found" in body
    finally:
        server.shutdown()

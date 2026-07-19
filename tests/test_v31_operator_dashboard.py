"""v3.1 - operator dashboard routes, shared guard, guarded work mutations (no argv over HTTP).

Extends the single existing dashboard (`core/scout/dashboard.py`). Every state-changing endpoint is
behind the shared guard (loopback Host + Origin + CSRF); no endpoint accepts a command/argv.
"""
from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request

import pytest

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


def test_analyze_generates_safe_id_when_omitted(tmp_path):
    # P0-1: an omitted/blank project name generates a safe id exactly as the CLI does.
    from core.orchestration.providers import validate_project_id
    server, url = _dash(tmp_path)
    try:
        status, j = _post(url + "/api/work/analyze", server.scout_csrf_token,
                          {"text": _BRIEF, "project_id": "", "source_platform": "direct"})
        assert status == 200 and j["ok"]
        pid = j["project_id"]
        assert validate_project_id(pid) and "/" not in pid and ".." not in pid
        assert (tmp_path / pid / "40_ark_work" / "WORK_RUN_STATE.json").exists()
    finally:
        server.shutdown()


@pytest.mark.parametrize("bad_pid", ["../evil", "a/b", "..", "c\\d", "/abs/path", "x" * 65,
                                     "bad id", "ctrl\x01char", "d:evil"])
def test_analyze_refuses_unsafe_project_ids(tmp_path, bad_pid):
    # P0-1: traversal, separators, absolute paths, invalid chars, oversized, control chars.
    server, url = _dash(tmp_path)
    try:
        status, j = _post(url + "/api/work/analyze", server.scout_csrf_token,
                          {"text": _BRIEF, "project_id": bad_pid})
        assert status == 400 and not j["ok"] and "project id" in j["error"].lower()
        # Nothing escaped the output dir.
        assert not (tmp_path.parent / "evil").exists()
    finally:
        server.shutdown()


def test_analyze_rejects_oversized_brief(tmp_path):
    server, url = _dash(tmp_path)
    try:
        status, j = _post(url + "/api/work/analyze", server.scout_csrf_token,
                          {"text": "x" * 70000, "project_id": "big"})
        # Either the body cap (400 invalid/oversized) or the explicit brief bound rejects it.
        assert status == 400 and not j.get("ok", False)
    finally:
        server.shutdown()


def test_analyze_collision_generates_distinct_ids(tmp_path):
    # P0-1: two omitted-id analyses of the same brief do not collide (distinct generated ids).
    server, url = _dash(tmp_path)
    try:
        _, j1 = _post(url + "/api/work/analyze", server.scout_csrf_token, {"text": _BRIEF})
        _, j2 = _post(url + "/api/work/analyze", server.scout_csrf_token, {"text": _BRIEF})
        assert j1["ok"] and j2["ok"] and j1["project_id"] != j2["project_id"]
    finally:
        server.shutdown()


def test_analyze_same_id_same_fingerprint_is_idempotent(tmp_path):
    # v3.2 5.2: re-analyzing the same explicit id + same input returns the existing project and
    # does NOT rewrite progressed state.
    server, url = _dash(tmp_path)
    try:
        s1, j1 = _post(url + "/api/work/analyze", server.scout_csrf_token,
                       {"text": _BRIEF, "project_id": "same"})
        assert s1 == 200 and j1["ok"] and not j1.get("idempotent")
        # Progress the project past intake so a re-analyze would be destructive if it re-ran.
        WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).approve(
            "same", reviewer="op")
        state_before = json.loads(
            (tmp_path / "same" / "40_ark_work" / "WORK_RUN_STATE.json").read_text(encoding="utf-8"))
        s2, j2 = _post(url + "/api/work/analyze", server.scout_csrf_token,
                       {"text": _BRIEF, "project_id": "same"})
        assert s2 == 200 and j2["ok"] and j2["idempotent"] is True
        state_after = json.loads(
            (tmp_path / "same" / "40_ark_work" / "WORK_RUN_STATE.json").read_text(encoding="utf-8"))
        assert state_after["status"] == state_before["status"] == "READY_TO_EXECUTE"
    finally:
        server.shutdown()


def test_analyze_same_id_different_fingerprint_conflicts(tmp_path):
    server, url = _dash(tmp_path)
    try:
        _post(url + "/api/work/analyze", server.scout_csrf_token,
              {"text": _BRIEF, "project_id": "conf"})
        s, j = _post(url + "/api/work/analyze", server.scout_csrf_token,
                     {"text": "A totally different client brief for API testing.",
                      "project_id": "conf"})
        assert s == 409 and not j["ok"] and "fingerprint" in j["error"]
    finally:
        server.shutdown()


def test_analyze_concurrent_identical_requests_resolve_to_one_project(tmp_path):
    import concurrent.futures
    server, url = _dash(tmp_path)
    try:
        def _go(_):
            return _post(url + "/api/work/analyze", server.scout_csrf_token,
                         {"text": _BRIEF, "project_id": "race"})
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            results = list(ex.map(_go, range(4)))
        codes = [s for s, _ in results]
        assert all(c == 200 for c in codes)               # no conflict/overwrite among identical
        assert all(j["project_id"] == "race" for _, j in results)
        assert sum(1 for _, j in results if not j.get("idempotent")) == 1   # exactly one created it
    finally:
        server.shutdown()


def test_unknown_project_detail_is_not_found(tmp_path):
    server, url = _dash(tmp_path)
    try:
        status, body, _ = _get(url + "/work/nope")
        assert status == 200 and "Project not found" in body
    finally:
        server.shutdown()


def _get_full(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read(), dict(r.headers)


def test_evidence_preview_is_safe(tmp_path):
    _seed_ready_for_review(tmp_path)
    ws = tmp_path / "alpha" / "40_ark_work"
    (ws / "evidence").mkdir(exist_ok=True)
    (ws / "evidence" / "log.txt").write_text("a validation log line\n", encoding="utf-8")
    (ws / "evidence" / "danger.html").write_text("<script>alert(1)</script>", encoding="utf-8")
    server, url = _dash(tmp_path)
    try:
        # Text evidence previews inline as text/plain.
        s, data, h = _get_full(url + "/work-evidence?project=alpha&path=evidence/log.txt")
        assert s == 200 and h["Content-Type"].startswith("text/plain")
        assert h.get("X-Content-Type-Options") == "nosniff" and "validation log" in data.decode()
        # Active content (HTML) is NEVER served inline: text/plain + attachment + sandbox CSP.
        s, data, h = _get_full(url + "/work-evidence?project=alpha&path=evidence/danger.html")
        assert s == 200 and h["Content-Type"].startswith("text/plain")
        assert "attachment" in h.get("Content-Disposition", "")
        assert "sandbox" in h.get("Content-Security-Policy", "")
        # Traversal is refused.
        try:
            urllib.request.urlopen(url + "/work-evidence?project=alpha&path=../../../etc/passwd",
                                   timeout=5)
            raise AssertionError("traversal not refused")
        except urllib.error.HTTPError as e:
            assert e.code in (403, 404)
        # An unsafe project id is refused.
        try:
            urllib.request.urlopen(url + "/work-evidence?project=../evil&path=x", timeout=5)
            raise AssertionError("unsafe project not refused")
        except urllib.error.HTTPError as e:
            assert e.code in (403, 404)
    finally:
        server.shutdown()


def _get_raw(base, path, host):
    conn_host, port = base.replace("http://", "").split(":")
    conn = http.client.HTTPConnection(conn_host, int(port), timeout=5)
    conn.request("GET", path, headers={"Host": host})
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    conn.close()
    return resp.status, body


def test_get_routes_refuse_dns_rebinding(tmp_path):
    # P0-3: a non-loopback Host must not receive tokens, project data, evidence, or artifacts.
    _seed_ready_for_review(tmp_path)
    server, url = _dash(tmp_path)
    real_host = url.replace("http://", "")
    try:
        for path in ["/api/csrf", "/api/work", "/api/overview", "/api/work/alpha",
                     "/work-evidence?project=alpha&path=fix.py", "/company?id=x", "/artifact?path=x"]:
            status, body = _get_raw(url, path, "attacker.example")
            assert status == 403 and "loopback" in body, path
            assert "csrf" not in body.lower() and "alpha" not in body
        # Normal loopback Host variants still work.
        for host in (real_host, f"localhost:{real_host.split(':')[1]}"):
            status, _ = _get_raw(url, "/api/csrf", host)
            assert status == 200
        # IPv6 loopback Host is accepted by the guard.
        status, _ = _get_raw(url, "/api/csrf", f"[::1]:{real_host.split(':')[1]}")
        assert status == 200
    finally:
        server.shutdown()


def test_scout_campaigns_page_renders(tmp_path):
    server, url = _dash(tmp_path)
    try:
        status, body, _ = _get(url + "/scout/campaigns")
        assert status == 200 and "Scout campaigns" in body and "<main>" in body
    finally:
        server.shutdown()


def test_unified_scout_pages_use_shared_layout(tmp_path):
    # P1: /scout, /results, /company, /projects render in the shared layout, preserving the
    # regression-locked Scout phrases.
    server, url = _dash(tmp_path)
    try:
        s, scout, _ = _get(url + "/scout")
        assert s == 200 and "<main>" in scout and "Prospect QA Scout" in scout
        assert "Stop Safely" in scout or "Controls unavailable" in scout
        s, results, _ = _get(url + "/results")
        assert s == 200 and "<main>" in results and "results" in results.lower()
        assert 'role="search"' in results          # Results filters are present
        s, projects, _ = _get(url + "/projects")
        assert s == 200 and "<main>" in projects and "projects" in projects.lower()
        s, company, _ = _get(url + "/company?id=unknown")
        assert s == 200 and "<main>" in company
    finally:
        server.shutdown()

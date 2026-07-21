"""v3.3 — per-run evidence artifact serving (path-confined) + human-in-the-loop rescan.

The artifact route must confine to one run dir (no traversal, no unsafe run id); the rescan
endpoint mutates state so it must be refused without CSRF and only mark an existing target.
No live calls."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from core.scout.dashboard import start_dashboard
from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
from core.scout.service import ScoutService
from core.scout.store import RunStore


def _dash(tmp_path):
    return start_dashboard(ScoutService(str(tmp_path)), operator_home=True)


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _post(url, body, csrf=None):
    headers = {"Content-Type": "application/json"}
    if csrf:
        headers["X-Scout-CSRF"] = csrf
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode("utf-8"),
                                 headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_scout_artifact_serves_confined_run_file(tmp_path):
    st = RunStore(str(tmp_path), "run1")
    rel = st.save_prospect_artifact("p1", "observation.json", {"status": 200})
    server, url = _dash(tmp_path)
    try:
        status, data = _get(f"{url}/scout/artifact?run=run1&rel={rel}")
        assert status == 200
        assert json.loads(data.decode("utf-8"))["status"] == 200
    finally:
        server.shutdown()


def test_scout_artifact_blocks_traversal_and_bad_run(tmp_path):
    RunStore(str(tmp_path), "run1").save_prospect_artifact("p1", "observation.json", {"ok": True})
    server, url = _dash(tmp_path)
    try:
        # unsafe run id (contains ..) is rejected by the RunStore constructor
        code, _ = _get(f"{url}/scout/artifact?run=..&rel=state.json")
        assert code == 403
        # traversal in the relative path escapes the run dir -> refused
        code, _ = _get(f"{url}/scout/artifact?run=run1&rel=../../secret.txt")
        assert code == 403
        # missing params -> 404
        code, _ = _get(f"{url}/scout/artifact?run=run1")
        assert code == 404
    finally:
        server.shutdown()


def test_rescan_refused_without_csrf(tmp_path):
    server, url = _dash(tmp_path)
    try:
        code, body = _post(f"{url}/api/scout/rescan?domain=example.com", {})
        assert code == 403 and body["ok"] is False
    finally:
        server.shutdown()


def test_start_client_work_refused_without_csrf(tmp_path):
    server, url = _dash(tmp_path)
    try:
        code, body = _post(f"{url}/api/scout/start-client-work?domain=example.com", {})
        assert code == 403 and body["ok"] is False       # mutation guard blocks it
    finally:
        server.shutdown()


def test_replay_refused_without_csrf(tmp_path):
    server, url = _dash(tmp_path)
    try:
        code, body = _post(f"{url}/api/scout/replay?domain=example.com", {})
        assert code == 403 and body["ok"] is False        # CSRF guard blocks it (no browser opened)
    finally:
        server.shutdown()


def test_replay_requires_domain(tmp_path):
    server, url = _dash(tmp_path)
    try:
        # CSRF ok but no domain -> 400 BEFORE any engine/browser starts (safe in CI)
        code, body = _post(f"{url}/api/scout/replay", {}, csrf=server.scout_csrf_token)
        assert code == 400 and body["ok"] is False
    finally:
        server.shutdown()


def test_set_engagement_updates_known_target_only(tmp_path):
    reg = AnalyzedSiteRegistry(str(tmp_path))
    reg.observe("http://example.com", campaign_id="c1", provider="tavily")
    assert reg.set_engagement("example.com", "contacted", work_id="w-1") is True
    got = AnalyzedSiteRegistry(str(tmp_path)).get("example.com")
    assert got.engagement_status == "contacted" and got.work_id == "w-1"
    assert reg.set_engagement("example.com", "bogus") is False        # unknown status rejected
    assert reg.set_engagement("nope.invalid", "won") is False         # unknown target rejected


def test_engagement_endpoint_requires_csrf(tmp_path):
    server, url = _dash(tmp_path)
    try:
        code, body = _post(f"{url}/api/scout/engagement?domain=example.com&status=contacted", {})
        assert code == 403 and body["ok"] is False
    finally:
        server.shutdown()


def test_engagement_endpoint_sets_status_with_csrf(tmp_path):
    AnalyzedSiteRegistry(str(tmp_path)).observe("http://example.com", campaign_id="c1",
                                                provider="tavily")
    server, url = _dash(tmp_path)
    try:
        # A free operator transition (contacted) is set one-click with CSRF.
        code, body = _post(f"{url}/api/scout/engagement?domain=example.com&status=contacted", {},
                           csrf=server.scout_csrf_token)
        assert code == 200 and body["ok"] is True
        assert AnalyzedSiteRegistry(str(tmp_path)).get("example.com").engagement_status == "contacted"
        # Won is a commitment: refused without explicit confirmation (funnel correctness).
        code, body = _post(f"{url}/api/scout/engagement?domain=example.com&status=won", {},
                           csrf=server.scout_csrf_token)
        assert code == 400 and body["ok"] is False and body["needs_confirmation"] is True
        assert AnalyzedSiteRegistry(str(tmp_path)).get("example.com").engagement_status == "contacted"
        # an unknown status is rejected (400), not silently accepted
        code, body = _post(f"{url}/api/scout/engagement?domain=example.com&status=bogus", {},
                           csrf=server.scout_csrf_token)
        assert code == 400 and body["ok"] is False
    finally:
        server.shutdown()


def test_rescan_with_csrf_marks_existing_target(tmp_path):
    reg = AnalyzedSiteRegistry(str(tmp_path))
    reg.observe("http://example.com", campaign_id="c1", provider="tavily")
    reg.record_analysis("http://example.com")               # status -> analyzed
    server, url = _dash(tmp_path)
    try:
        code, body = _post(f"{url}/api/scout/rescan?domain=example.com", {},
                           csrf=server.scout_csrf_token)
        assert code == 200 and body["ok"] is True
        # the target is eligible again (DISCOVERED), so a future run re-analyzes it
        assert AnalyzedSiteRegistry(str(tmp_path)).get("example.com").analysis_status == "discovered"
        # an unknown target is a clean 404, not a crash
        code, body = _post(f"{url}/api/scout/rescan?domain=nope.invalid", {},
                           csrf=server.scout_csrf_token)
        assert code == 404 and body["ok"] is False
    finally:
        server.shutdown()

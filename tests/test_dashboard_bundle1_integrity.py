"""Bundle 1 — Dashboard/Scout production-integrity fixes (three confirmed defects).

Covers, deterministically and with no live calls:

  Fix 1 (P9) Zero-cost reads     — CampaignService.target_detail() (a READ) must never construct or
                                   invoke the LLM router; the deterministic outreach draft stays
                                   available; AI polish is an EXPLICIT mutation (polish_draft()).
  Fix 2 (P10) Funnel correctness — Start client work links a work item but must NOT set Won; Won and
                                   Delivered require explicit confirmation; contacted/replied/lost
                                   remain free operator transitions.
  Fix 3 (P0-B) Build identity     — a running vs HEAD commit surface that flags a stale build and
                                   never leaks secrets or absolute paths.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from core.scout.campaign_service import CampaignService
from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry, ENG_PROSPECT
from core.scout.service import ScoutService
from core.scout.dashboard import start_dashboard


# --------------------------------------------------------------------------------------------------
# Fix 1 — zero-cost reads
# --------------------------------------------------------------------------------------------------
def test_target_detail_read_makes_zero_llm_calls(tmp_path):
    """Opening AND refreshing a target card must never build/call the LLM router (a paid request)."""
    calls: list = []

    class _Svc(CampaignService):
        def _llm_router(self):                       # record any attempt to obtain the router
            calls.append(1)
            return None

    svc = _Svc(output_dir=str(tmp_path))
    svc.target_detail("example.com")
    svc.target_detail("example.com")                 # re-open / refresh
    assert calls == []                               # a read is $0 by construction


def test_target_detail_read_passes_no_router_to_draft(tmp_path, monkeypatch):
    """The read path must hand build_review_draft router=None (deterministic, never billed)."""
    import core.scout.outreach.qa_draft as qa
    seen: list = []
    real = qa.build_review_draft

    def _spy(**kw):
        seen.append(kw.get("router"))
        return real(**kw)

    monkeypatch.setattr(qa, "build_review_draft", _spy)
    monkeypatch.setattr(CampaignService, "_llm_router", lambda self: object())  # a live-looking router
    CampaignService(output_dir=str(tmp_path)).target_detail("example.com")
    assert seen and seen[0] is None                  # read never forwards a router


def test_target_detail_still_returns_deterministic_draft(tmp_path):
    """The deterministic, copy-only draft remains available on a read (guard against removal)."""
    det = CampaignService(output_dir=str(tmp_path)).target_detail("example.com")
    assert det["draft"]["generated_by"] == "deterministic"
    assert det["draft"]["sent"] is False


def test_polish_draft_is_the_explicit_llm_path(tmp_path, monkeypatch):
    """AI polish is opt-in: polish_draft() (an explicit action) forwards the live router."""
    import core.scout.outreach.qa_draft as qa
    seen: list = []
    real = qa.build_review_draft

    def _spy(**kw):
        seen.append(kw.get("router"))
        return real(**kw)

    monkeypatch.setattr(qa, "build_review_draft", _spy)
    sentinel = object()
    monkeypatch.setattr(CampaignService, "_llm_router", lambda self: sentinel)
    CampaignService(output_dir=str(tmp_path)).polish_draft("example.com")
    assert seen and seen[-1] is sentinel             # explicit path forwards the router


# --------------------------------------------------------------------------------------------------
# Fix 2 — funnel correctness
# --------------------------------------------------------------------------------------------------
def _reg_with_target(tmp_path, domain="acme.com"):
    reg = AnalyzedSiteRegistry(str(tmp_path))
    reg.record_analysis(domain, evidence_ref=f"scout/{domain}/qa")
    return reg, domain


def test_link_work_does_not_mark_won(tmp_path):
    """Start client work links a work item but leaves the sales stage untouched (not Won)."""
    reg, dom = _reg_with_target(tmp_path)
    assert reg.link_work(dom, "scout-acme-123") is True
    e = reg.get(dom)
    assert e.work_id == "scout-acme-123"
    assert e.engagement_status == ENG_PROSPECT       # NOT promoted to won


def test_set_engagement_refuses_won_without_confirmation(tmp_path):
    reg, dom = _reg_with_target(tmp_path)
    assert reg.set_engagement(dom, "won") is False
    assert reg.get(dom).engagement_status == ENG_PROSPECT


def test_set_engagement_refuses_delivered_without_confirmation(tmp_path):
    reg, dom = _reg_with_target(tmp_path)
    assert reg.set_engagement(dom, "delivered") is False
    assert reg.get(dom).engagement_status == ENG_PROSPECT


def test_set_engagement_allows_won_with_confirmation(tmp_path):
    reg, dom = _reg_with_target(tmp_path)
    assert reg.set_engagement(dom, "won", confirm=True) is True
    assert reg.get(dom).engagement_status == "won"


def test_set_engagement_allows_free_transitions_without_confirmation(tmp_path):
    """Contacted/Replied/Lost stay ordinary one-click operator transitions."""
    reg, dom = _reg_with_target(tmp_path)
    for status in ("contacted", "replied", "lost"):
        assert reg.set_engagement(dom, status) is True
        assert reg.get(dom).engagement_status == status


# --------------------------------------------------------------------------------------------------
# Fix 3 — build identity / stale-process detection
# --------------------------------------------------------------------------------------------------
def test_compute_identity_flags_stale_when_running_differs_from_head():
    from core.build_identity import compute_identity
    ident = compute_identity(running_sha="a" * 40, head_sha="b" * 40,
                             product_version="x", started_at="2026-01-01T00:00:00+00:00")
    assert ident["stale"] is True
    assert "Restart" in ident["warning"]


def test_compute_identity_not_stale_when_equal():
    from core.build_identity import compute_identity
    ident = compute_identity(running_sha="a" * 40, head_sha="a" * 40,
                             product_version="x", started_at="t")
    assert ident["stale"] is False
    assert ident["warning"] == ""


def test_compute_identity_not_stale_when_head_unknown():
    """No resolvable HEAD (e.g. git absent) must not raise a false stale alarm."""
    from core.build_identity import compute_identity
    ident = compute_identity(running_sha="a" * 40, head_sha="",
                             product_version="x", started_at="t")
    assert ident["stale"] is False


def test_current_identity_exposes_no_secrets_or_abs_paths():
    from core.build_identity import current_identity
    ident = current_identity()
    required = {"product_version", "running_sha", "head_sha", "process_started_at", "stale",
                "warning"}
    assert required <= set(ident)
    blob = json.dumps(ident)
    assert ":\\" not in blob and "/home/" not in blob and "/Users/" not in blob
    for k in ident:
        assert not any(s in k.lower() for s in ("key", "token", "secret", "password"))


# --------------------------------------------------------------------------------------------------
# Dashboard wiring (loopback HTTP) — the three fixes at the endpoint surface
# --------------------------------------------------------------------------------------------------
def _dash(tmp_path):
    return start_dashboard(ScoutService(str(tmp_path)), operator_home=True)


def _get_json(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def _post_json(url, token, body=None):
    req = urllib.request.Request(url, method="POST",
                                 data=json.dumps(body or {}).encode("utf-8"),
                                 headers={"Content-Type": "application/json", "X-Scout-CSRF": token})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_api_build_reports_identity_over_http(tmp_path):
    server, url = _dash(tmp_path)
    try:
        status, j = _get_json(url + "/api/build")
        assert status == 200 and isinstance(j, dict)
        assert {"product_version", "running_sha", "head_sha", "stale", "warning"} <= set(j)
        blob = json.dumps(j)
        assert ":\\" not in blob and "/Users/" not in blob and "/home/" not in blob
    finally:
        server.shutdown()


def test_engagement_won_over_http_requires_confirm(tmp_path):
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis("acme.com", evidence_ref="scout/acme.com/qa")
    server, url = _dash(tmp_path)
    token = server.scout_csrf_token
    try:
        # Won WITHOUT confirmation → refused; stage unchanged.
        _, j = _post_json(url + "/api/scout/engagement?domain=acme.com&status=won", token)
        assert j["ok"] is False
        assert AnalyzedSiteRegistry(str(tmp_path)).get("acme.com").engagement_status == ENG_PROSPECT
        # Won WITH confirmation → allowed.
        _, j = _post_json(url + "/api/scout/engagement?domain=acme.com&status=won&confirm=1", token)
        assert j["ok"] is True
        assert AnalyzedSiteRegistry(str(tmp_path)).get("acme.com").engagement_status == "won"
    finally:
        server.shutdown()


def test_polish_draft_endpoint_returns_draft(tmp_path):
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis("acme.com", evidence_ref="scout/acme.com/qa")
    server, url = _dash(tmp_path)
    token = server.scout_csrf_token
    try:
        status, j = _post_json(url + "/api/scout/polish-draft?domain=acme.com", token)
        assert status == 200 and j.get("ok") is True
        assert j["draft"]["sent"] is False
        assert j["draft"]["generated_by"] == "deterministic"   # $0 in mock/test env
    finally:
        server.shutdown()


def test_polish_draft_endpoint_refused_without_csrf(tmp_path):
    server, url = _dash(tmp_path)
    try:
        req = urllib.request.Request(url + "/api/scout/polish-draft?domain=acme.com", method="POST",
                                     data=b"{}", headers={"Content-Type": "application/json"})
        try:
            code = urllib.request.urlopen(req, timeout=5).status
        except urllib.error.HTTPError as e:
            code = e.code
        assert code == 403                                     # CSRF/origin guard blocks it
    finally:
        server.shutdown()

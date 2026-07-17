"""Final Phase I — adaptive deep-QA session against defect fixtures (deterministic, no browser)."""
from __future__ import annotations

import itertools

from core.scout.demo_site import serve_demo_site
from core.scout.discovery.fixtures import HostMappedStaticBackend
from core.scout.pipeline.engine import DeepQaSession
from core.scout.store import RunStore
from core.scout.url_safety import UrlPolicy

_c = itertools.count()


def _clock():
    return f"2026-07-17T08:00:{next(_c):02d}+00:00"


def _session(tmp, hostport, sid):
    backend = HostMappedStaticBackend(UrlPolicy(resolve_dns=False),
                                      {"defectsite.example": hostport})
    return DeepQaSession(RunStore(str(tmp), sid), campaign_id="c", company_id="co-1",
                         session_id=sid, policy=UrlPolicy(resolve_dns=False), backend=backend,
                         clock=_clock)


def test_deepqa_produces_verified_client_safe_findings(tmp_path):
    with serve_demo_site() as (_base, hostport):
        sess = _session(tmp_path, hostport, "01-defect")
        result = sess.run("http://defectsite.example/accessibility/index.html",
                          hints={"business_type_hint": "agency", "language_hint": "en"})
    assert result.verified, "expected verified findings on a defect page"
    assert all(f.is_client_safe for f in result.verified)
    # Accessibility defects were detected and normalized.
    caps = {f.capability for f in result.verified}
    assert "accessibility" in caps
    # Deep SEO ran (robots/sitemap absent on the fixture).
    seo_sigs = {f.signature for f in result.verified if f.capability == "seo"}
    assert "no_robots_txt" in seo_sigs or "no_sitemap" in seo_sigs

    store = RunStore(str(tmp_path), "01-defect")
    for name in ("CAPABILITY_PLAN.json", "SITE_PROFILE.json", "BUSINESS_CONTEXT.json",
                 "INTERACTION_BOUNDARY.json", "COVERAGE_MAP.json", "NORMALIZED_FINDINGS.json",
                 "VERIFICATION_RESULT.json"):
        assert store.load_prospect_artifact("01-defect", name) is not None, name
    # Per-finding artifacts exist for a verified finding.
    fid = result.verified[0].finding_id
    assert store.load_prospect_artifact("01-defect", f"FINDING_{fid}.json") is not None
    assert store.load_prospect_artifact("01-defect", f"VERIFICATION_RESULT_{fid}.json") is not None


def test_deepqa_clean_page_has_no_defect_findings(tmp_path):
    with serve_demo_site() as (_base, hostport):
        sess = _session(tmp_path, hostport, "02-clean")
        result = sess.run("http://defectsite.example/clean/index.html",
                          hints={"business_type_hint": "saas", "language_hint": "en"})
    # The clean control page has valid metadata; only bounded SEO/coverage notes may appear,
    # never an accessibility/mobile defect.
    defects = [f for f in result.verified if f.capability in ("accessibility", "mobile")
               and f.severity in ("medium", "high")]
    assert not defects


def test_deepqa_no_secret_leak(tmp_path):
    with serve_demo_site() as (_base, hostport):
        _session(tmp_path, hostport, "03-leak").run(
            "http://defectsite.example/accessibility/index.html",
            hints={"business_type_hint": "agency"})
    for p in tmp_path.rglob("*"):
        if p.is_file():
            assert b"secretcookievalue" not in p.read_bytes()

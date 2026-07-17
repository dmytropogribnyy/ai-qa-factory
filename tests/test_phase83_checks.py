"""Phase 8.3 — findings model + check families against deterministic fixtures."""
from __future__ import annotations

import pytest

from core.scout.url_safety import UrlPolicy
from core.scout.backends import StaticHttpBackend
from core.scout.checks import CheckContext, run_checks
from core.scout.findings import ScoutFinding, VERIFY_VERIFIED
from tests.scout_fixtures import serve_fixtures

_ALL = ["seo", "accessibility", "structured_data", "mobile", "performance",
        "presubmit_validation", "links", "console_resources", "business_flow"]


def _observe(base, host, path):
    b = StaticHttpBackend(policy=UrlPolicy(allowed_local_hosts=frozenset({host})))
    return b.observe(f"{base}{path}", 10, 2_000_000)


def _families(findings):
    return {f.signature for f in findings}


class TestChecks:
    def test_clean_control_has_no_defects(self):
        with serve_fixtures() as (base, host):
            obs = _observe(base, host, "/clean/index.html")
        ctx = CheckContext(run_id="r", prospect_ref="p", link_status={})
        findings = run_checks(obs, ctx, _ALL)
        # Only info/coverage-limitation findings are allowed for the clean control.
        defects = [f for f in findings if f.severity != "info"]
        assert defects == [], f"clean control produced defects: {[d.title for d in defects]}"

    def test_seo_gaps(self):
        with serve_fixtures() as (base, host):
            obs = _observe(base, host, "/seo/index.html")
        sigs = _families(run_checks(obs, CheckContext(), ["seo"]))
        assert {"missing_title", "missing_meta_description", "missing_canonical"} <= sigs

    def test_accessibility_violations(self):
        with serve_fixtures() as (base, host):
            obs = _observe(base, host, "/accessibility/index.html")
        sigs = _families(run_checks(obs, CheckContext(), ["accessibility"]))
        assert "img_missing_alt" in sigs and "unlabeled_input" in sigs

    def test_structured_data_malformed(self):
        with serve_fixtures() as (base, host):
            obs = _observe(base, host, "/structured_data/index.html")
        assert "malformed_jsonld" in _families(run_checks(obs, CheckContext(), ["structured_data"]))

    def test_mobile_missing_viewport(self):
        with serve_fixtures() as (base, host):
            obs = _observe(base, host, "/mobile/index.html")
        assert "missing_viewport" in _families(run_checks(obs, CheckContext(), ["mobile"]))

    def test_presubmit_validation(self):
        with serve_fixtures() as (base, host):
            obs = _observe(base, host, "/presubmit/index.html")
        sigs = _families(run_checks(obs, CheckContext(), ["presubmit_validation"]))
        assert any(s.startswith("weak_form_validation") for s in sigs)

    def test_broken_link(self):
        with serve_fixtures() as (base, host):
            obs = _observe(base, host, "/broken_link/index.html")
            link_status = {f"{base}/broken_link/missing.html": 404,
                           f"{base}/clean/about.html": 200}
        ctx = CheckContext(run_id="r", prospect_ref="p", link_status=link_status)
        sigs = _families(run_checks(obs, ctx, ["links"]))
        assert any(s.startswith("broken_link:") for s in sigs)

    def test_deterministic_finding_ids(self):
        with serve_fixtures() as (base, host):
            obs = _observe(base, host, "/seo/index.html")
        ctx = CheckContext(run_id="run-1", prospect_ref="p1")
        a = run_checks(obs, ctx, ["seo"])
        b = run_checks(obs, ctx, ["seo"])
        assert [f.finding_id for f in a] == [f.finding_id for f in b]


class TestFindingSafety:
    def test_unknown_enums_rejected(self):
        with pytest.raises(ValueError):
            ScoutFinding(severity="critical")
        with pytest.raises(ValueError):
            ScoutFinding(category="marketing")

    def test_from_dict_resets_verified_and_sanitized(self):
        f = ScoutFinding(title="x", verification_state=VERIFY_VERIFIED, sanitized=True)
        back = ScoutFinding.from_dict(f.to_dict())
        assert back.sanitized is False
        assert back.verification_state == "UNVERIFIED"
        assert back.is_client_safe is False

    def test_client_safe_requires_verified_and_sanitized(self):
        f = ScoutFinding(title="x")
        assert f.is_client_safe is False
        f.verification_state = VERIFY_VERIFIED
        assert f.is_client_safe is False   # not sanitized
        f.sanitized = True
        assert f.is_client_safe is True

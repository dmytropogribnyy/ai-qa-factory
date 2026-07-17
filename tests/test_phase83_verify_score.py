"""Phase 8.3 — sanitization, independent verification, and scoring."""
from __future__ import annotations

from core.scout.backends import PageObservation
from core.scout.findings import ScoutFinding, VERIFY_VERIFIED
from core.scout.sanitize import Sanitizer
from core.scout.verification import IndependentVerifier
from core.scout.scoring import build_scorecard


def _f(sig, sev="medium", **kw):
    return ScoutFinding(finding_id=f"f-{sig}", signature=sig, title=kw.pop("title", sig),
                        severity=sev, check_family=kw.pop("family", "seo"),
                        category=kw.pop("category", "seo"), **kw)


class TestSanitizer:
    def test_redacts_secret_and_pii(self):
        s = Sanitizer()
        red = s.redact("token sk_live_0123456789ABCDEFGHIJ email a@b.com phone 0123456789")
        assert "sk_live_0123456789ABCDEFGHIJ" not in red
        assert "a@b.com" not in red and "[REDACTED_EMAIL]" in red
        assert "0123456789" not in red

    def test_evidence_has_no_cookie_or_body(self):
        s = Sanitizer()
        obs = PageObservation(url="https://x/", final_url="https://x/", status=200,
                              title="Hi", headers={"content-type": "text/html"})
        ev = s.build_evidence(obs)
        blob = str(ev)
        assert "set-cookie" not in blob.lower() and "secret" not in blob.lower()
        assert "safe_headers" in ev
        assert "body" not in ev and "raw_html" not in ev and "cookies" not in ev

    def test_sanitize_finding_marks_clean(self):
        s = Sanitizer()
        f = _f("x", actual="token sk_live_0123456789ABCDEFGHIJ leaked")
        s.sanitize_finding(f)
        assert f.sanitized is True
        assert "sk_live_0123456789ABCDEFGHIJ" not in f.actual


class TestVerification:
    def test_reproduced_becomes_verified(self):
        v = IndependentVerifier(Sanitizer())
        first = [_f("a"), _f("b")]
        verified, rejected = v.verify(first, {"a", "b"}, evidence_ref="EV-1")
        assert len(verified) == 2 and not rejected
        assert all(f.verification_state == VERIFY_VERIFIED and f.is_client_safe for f in verified)
        assert verified[0].evidence_refs == ["EV-1"]

    def test_unreproduced_is_rejected(self):
        v = IndependentVerifier(Sanitizer())
        first = [_f("a"), _f("transient")]
        verified, rejected = v.verify(first, {"a"})  # 'transient' not in second pass
        assert {f.signature for f in verified} == {"a"}
        assert {f.signature for f in rejected} == {"transient"}
        assert rejected[0].verification_state == "REJECTED"

    def test_verified_finding_secret_is_redacted(self):
        v = IndependentVerifier(Sanitizer())
        f = _f("s", actual="leak sk_live_0123456789ABCDEFGHIJ")
        verified, _ = v.verify([f], {"s"})
        assert verified and "sk_live_0123456789ABCDEFGHIJ" not in verified[0].actual


class TestScoring:
    def test_no_defects_low_priority_no_outreach(self):
        sc = build_scorecard("p1", [])
        assert sc.priority == "D"
        assert sc.outreach_eligible is False

    def test_defects_raise_priority_but_never_authorize_outreach(self):
        findings = [_f("a", sev="high"), _f("b", sev="high", family="mobile", category="mobile"),
                    _f("c", sev="medium", family="links", category="functional")]
        sc = build_scorecard("p1", findings)
        assert sc.priority in ("A", "B")
        assert sc.outreach_eligible is False  # scoring never authorizes outreach
        assert any(d.name == "audit_opportunity" for d in sc.dimensions)

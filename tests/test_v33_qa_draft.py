"""v3.3 - copy-only QA-review draft + public-contact extraction. The system never sends."""
from __future__ import annotations

from core.scout.outreach.qa_draft import (
    build_review_draft,
    extract_public_emails,
    problem_bullets,
)


def test_extract_public_emails_prefers_same_domain_and_generic():
    obs = {"title": "Acme", "links": ["mailto:sales@acme.com", "mailto:john.doe@acme.com",
                                      "https://acme.com/x"],
           "meta_description": "reach us at info@acme.com or noise@other.com"}
    emails = extract_public_emails(obs, domain="acme.com")
    assert "info@acme.com" in emails and "sales@acme.com" in emails
    assert "noise@other.com" not in emails            # other domain dropped when same-domain exists
    assert emails[0].split("@")[0] in ("info", "sales")  # generic mailbox first


def test_extract_public_emails_empty_when_none():
    assert extract_public_emails({"title": "no contacts here"}, domain="x.com") == []


def test_problem_bullets_highest_severity_first_and_bounded():
    findings = [
        {"severity": "low", "title": "Small SEO gap", "business_impact": "minor"},
        {"severity": "high", "title": "Cart total wrong", "business_impact": "lost sales"},
        {"severity": "info", "title": "ignored"},
        {"severity": "medium", "title": "Slow load"},
    ]
    bullets = problem_bullets(findings)
    assert bullets[0].startswith("[HIGH] Cart total wrong")
    assert "lost sales" in bullets[0]
    assert not any("ignored" in b for b in bullets)   # info severity excluded


class _Resp:
    def __init__(self, text, model="anthropic/claude-haiku-4-5", used_fallback=False):
        self.text, self.model, self.used_fallback = text, model, used_fallback


class _Settings:
    def __init__(self, mock):
        self.is_mock = mock


class _Router:
    """Minimal stand-in for LLMRouter: records the call and returns a canned response."""
    def __init__(self, resp, mock=False):
        self.settings, self._resp, self.calls = _Settings(mock), resp, []

    def complete(self, **kw):
        self.calls.append(kw)
        return self._resp


_FINDINGS = [{"severity": "high", "title": "Broken checkout button",
              "business_impact": "blocks purchases", "evidence_refs": ["e1"]}]


def test_llm_polish_used_when_router_live_and_output_safe():
    router = _Router(_Resp("Hi,\nI reviewed your public shop and found a broken checkout button."))
    d = build_review_draft(domain="shop.example.com", findings=_FINDINGS, router=router)
    assert d["generated_by"] == "anthropic/claude-haiku-4-5"
    assert "broken checkout button" in d["body"].lower()
    assert router.calls and router.calls[0]["task_type"] == "proposal"   # cheap 'fast' alias
    assert d["sent"] is False


def test_llm_polish_falls_back_when_output_leaks_secret():
    router = _Router(_Resp("Hi, use my key sk-abc123 to view the report"))
    d = build_review_draft(domain="shop.example.com", findings=_FINDINGS, router=router)
    assert d["generated_by"] == "deterministic"          # unsafe output rejected
    assert "sk-" not in d["body"]


def test_llm_polish_skipped_in_mock_mode():
    router = _Router(_Resp("should not be used"), mock=True)
    d = build_review_draft(domain="shop.example.com", findings=_FINDINGS, router=router)
    assert d["generated_by"] == "deterministic"
    assert not router.calls                               # mock router never called ($0)


def test_llm_polish_absent_router_is_deterministic():
    d = build_review_draft(domain="shop.example.com", findings=_FINDINGS)
    assert d["generated_by"] == "deterministic"


def test_build_review_draft_is_copy_only_and_never_sends():
    findings = [{"severity": "high", "title": "Broken checkout button",
                 "business_impact": "blocks purchases", "evidence_refs": ["e1"]}]
    d = build_review_draft(domain="shop.example.com", business_name="Shop",
                           understanding={"archetype": "ecommerce"}, findings=findings,
                           contact="info@shop.example.com")
    assert d["sent"] is False                          # the system NEVER sends
    assert "DRAFT only" in d["disclaimer"]
    assert d["problem_bullets"] and "Broken checkout button" in d["body"]
    assert d["subject"].startswith("Quick QA review of Shop")
    assert d["contact"] == "info@shop.example.com"
    # the primary call-to-action is an explicit, low-pressure PAID QA audit offer
    assert "paid QA audit" in d["body"] and d["offer"]
    assert "checkout" in d["offer"]                     # tailored to the ecommerce archetype
    # no secrets/keys leak into a draft body
    assert "tvly-" not in d["body"] and "sk-" not in d["body"]

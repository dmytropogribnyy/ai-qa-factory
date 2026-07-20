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
    # no secrets/keys leak into a draft body
    assert "tvly-" not in d["body"] and "sk-" not in d["body"]

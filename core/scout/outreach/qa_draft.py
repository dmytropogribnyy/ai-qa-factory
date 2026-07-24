"""Copy-only QA-review outreach draft + public-contact extraction (v3.3).

Turns a target's verified QA findings into a concise, prioritized DRAFT letter and surfaces any
PUBLIC contact email found during the bounded scan. The system NEVER sends anything: the draft is
`sent=False`, copy-only, for the operator to review and send manually (project rule: no external
communication without explicit approval). Public emails are read-only, same-domain-preferred, and
governed by the existing outreach contact policy.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List
from urllib.parse import urlsplit, urlunsplit

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_GENERIC = ("info", "contact", "hello", "support", "sales", "office", "admin", "team")
_SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "info": 3}


def extract_public_emails(observation: Dict[str, Any], *, domain: str = "") -> List[str]:
    """Extract public contact emails from a bounded scan observation (mailto links + visible text).

    Read-only. Prefers same-domain and generic mailboxes (info@/contact@). Never triggers a send."""
    obs = observation or {}
    links = [str(x) for x in obs.get("links", [])]
    found = {m.split("?")[0][len("mailto:"):].strip()
             for m in links if m.lower().startswith("mailto:")}
    parts = [str(obs.get("title", "")), str(obs.get("meta_description", ""))] + links
    for h in obs.get("headings", []):
        parts.append(str(h.get("text", "")) if isinstance(h, dict) else str(h))
    found |= set(_EMAIL_RE.findall(" ".join(parts)))
    emails = sorted(e for e in found if _EMAIL_RE.fullmatch(e))
    if domain:
        d = domain.lower().lstrip("www.")
        same = []
        for email in emails:
            host = email.lower().split("@")[-1]
            if host == d or host.endswith("." + d):
                same.append(email)
        if same:
            emails = same
    # generic mailboxes first (better for cold outreach than a personal address)
    emails.sort(key=lambda e: (0 if any(g in e.lower().split("@")[0] for g in _GENERIC) else 1, e))
    return emails[:5]


def extract_public_contact_records(
    observation: Dict[str, Any], *, domain: str = ""
) -> List[Dict[str, Any]]:
    """Return public email contacts with a reviewable source, never inferred/private addresses."""
    obs = observation or {}
    emails = extract_public_emails(obs, domain=domain)
    mailto_emails = {
        str(item).split("?", 1)[0][len("mailto:"):].strip().lower()
        for item in obs.get("links", [])
        if str(item).lower().startswith("mailto:")
    }
    raw_url = str(obs.get("final_url") or obs.get("url") or "")
    try:
        parsed = urlsplit(raw_url)
        source_url = urlunsplit((
            parsed.scheme if parsed.scheme in ("http", "https") else "",
            parsed.hostname or "",
            parsed.path or "/",
            "",
            "",
        ))
    except ValueError:
        source_url = ""
    return [{
        "email": email,
        "source": ("Public mailto link"
                   if email.lower() in mailto_emails else "Public page text"),
        "source_url": source_url,
        "public": True,
    } for email in emails]


def problem_bullets(findings: List[Dict[str, Any]], *, limit: int = 8) -> List[str]:
    """Concise, highest-impact-first problem bullets from verified findings (no secrets/PII)."""
    items = [f for f in (findings or []) if f.get("severity") in ("high", "medium", "low")]
    items.sort(key=lambda f: _SEVERITY_ORDER.get(f.get("severity"), 9))
    bullets: List[str] = []
    for f in items[:limit]:
        title = str(f.get("title", "")).strip()
        if not title:
            continue
        sev = str(f.get("severity", "")).upper()
        impact = str(f.get("business_impact", "")).strip()
        bullet = f"[{sev}] {title}" + (f" - {impact}" if impact else "")
        bullets.append(bullet[:200])
    return bullets


def _looks_unsafe(text: str) -> bool:
    """Reject an LLM draft that is empty, a mock warning, or leaks a secret-looking token."""
    t = (text or "").strip()
    return (not t) or ("MOCK MODE" in t) or ("sk-" in t) or ("tvly-" in t)


def _llm_polish_body(router: Any, *, domain: str, name: str, archetype: str,
                     bullets: List[str], deterministic_body: str,
                     required_offer: str) -> tuple[str, str]:
    """Optionally rewrite the draft prose with a cheap model. Returns (body, generated_by).

    The model may ONLY reword using the exact `bullets` supplied - it must not invent findings.
    Any failure, mock mode, or unsafe output falls back to the deterministic template ($0)."""
    if router is None or getattr(getattr(router, "settings", None), "is_mock", True):
        return deterministic_body, "deterministic"
    if not bullets:
        return deterministic_body, "deterministic"
    system = (
        "You write a short, warm, professional cold outreach email offering a website QA review. "
        "Use ONLY the issues provided - never invent, exaggerate, or add findings. Public pages "
        "only: no logins/forms/orders were used, and you must say so. End with a clear but "
        "low-pressure offer of a deeper PAID QA audit (reproducible evidence + a prioritized fix "
        "list); do NOT quote a specific price or fee amount. Plain text, no markdown, no salutation "
        "placeholder names, under 170 words. Do not include secrets or links.")
    user = (
        f"Business: {name} ({domain}). Type: {archetype or 'website'}.\n"
        f"Issues found (verbatim, keep as a short bulleted list):\n" +
        "\n".join(f"- {b}" for b in bullets) +
        "\n\nWrite the email body only (start with 'Hi,'). Make the primary call-to-action a "
        "deeper PAID QA audit (reproducible evidence + prioritized fix list); offer to share the "
        "evidence either way. Keep it honest and low-pressure. No specific price.")
    # Scout uses its OWN cheap model, decoupled from the main Factory's premium profile.
    # Default Haiku; never Opus. Override with SCOUT_LLM_MODEL if desired.
    scout_model = os.environ.get("SCOUT_LLM_MODEL", "anthropic/claude-haiku-4-5").strip()
    try:
        resp = router.complete(task_type="proposal", system_prompt=system, user_prompt=user,
                               temperature=0.3, max_tokens=500, model=scout_model)
    except Exception:
        return deterministic_body, "deterministic"
    text = (getattr(resp, "text", "") or "").strip()
    model = getattr(resp, "model", "") or ""
    if getattr(resp, "used_fallback", False) or model == "mock" or _looks_unsafe(text):
        return deterministic_body, "deterministic"
    if required_offer and required_offer.lower() not in text.lower():
        text = text.rstrip() + "\n\n" + required_offer
    return text, model


def _offer_line(archetype: str = "") -> str:
    """The primary call-to-action: a clear but low-pressure offer of a deeper PAID QA audit,
    tailored to the site type. This is what a positive reply is agreeing to explore."""
    a = (archetype or "").lower()
    focus = (
        ("ecommerce", "your checkout, product, and conversion flows"),
        ("shop", "your checkout, product, and conversion flows"),
        ("saas", "your signup, onboarding, and core app flows"),
        ("marketplace", "your search, listing, and booking flows"),
        ("booking", "your search, availability, and booking flows"),
        ("lead", "your forms, conversion paths, and trust signals"),
    )
    for key, scope in focus:
        if key in a:
            return ("If useful, I offer a deeper, paid QA audit focused on " + scope +
                    " — with reproducible evidence, severity, and a prioritized fix list.")
    return ("If useful, I offer a deeper, paid QA audit of your key user journeys — with "
            "reproducible evidence, severity, and a prioritized fix list.")


def _fix_offer(findings: List[Dict[str, Any]]) -> tuple[str, Dict[str, Any]]:
    from core.scout.outreach.fixability import classify_fixability
    fixability = classify_fixability(findings, access_available=False)
    count = int(fixability.get("offerable") or 0)
    if count:
        noun = "issue" if count == 1 else "issues"
        line = (
            f"I can also implement fixes for {count} of these {noun} after we agree the scope "
            "and you provide repo/staging access; I would confirm any out-of-scope item separately."
        )
    else:
        line = (
            "I can share the evidence and prioritized recommendations, but I would not promise "
            "implementation before reviewing the scope and required access."
        )
    return line, fixability


def build_review_draft(*, domain: str, business_name: str = "",
                       understanding: Dict[str, Any] = None,
                       findings: List[Dict[str, Any]] = None,
                       contact: str = "", router: Any = None) -> Dict[str, Any]:
    """Build a COPY-ONLY QA-review outreach draft. `sent` is always False; the system never sends.

    If `router` is a live (non-mock) LLMRouter, a cheap model (Haiku by default) rewrites the prose
    for tone only, using the exact factual bullets; it can never send, invent findings, or break the
    pipeline (deterministic template is the fallback). Bullets stay deterministic."""
    name = (business_name or domain).strip()
    bullets = problem_bullets(findings or [])
    archetype = (understanding or {}).get("archetype")
    if not bullets:
        return {
            "schema": "qa-review-draft/v1", "domain": domain, "business_name": name,
            "archetype": archetype,
            "subject": f"QA review of {name} — no confirmed actionable issue",
            "problem_bullets": [],
            "body": (
                "No outreach draft is available because this bounded pass did not confirm an "
                "actionable issue. This is not a conclusion that the site is defect-free."
            ),
            "offer": "", "fix_offer": "", "fixability": _fix_offer([])[1],
            "generated_by": "deterministic", "contact": contact, "sent": False,
            "available": False,
            "disclaimer": (
                "DRAFT unavailable - the system never sends outreach without a confirmed issue."
            ),
        }
    issue_word = "issue" if len(bullets) == 1 else "issues"
    subject = f"Quick QA review of {name} — {len(bullets)} confirmed {issue_word}"
    intro = (
        f"I ran a bounded, read-only QA check of your public website ({domain}) and confirmed "
        f"the following {issue_word} that may affect conversion, accessibility, or user trust:"
    )
    offer = _offer_line(archetype)
    fix_offer, fixability = _fix_offer(findings or [])
    required_offer = offer + " " + fix_offer
    closing = ("These are from public pages only - no logins, form submissions, or orders. " +
               required_offer + " No obligation - happy to share the evidence either way.")
    deterministic_body = "\n".join(["Hi,", "", intro, ""] + [f"- {b}" for b in bullets] +
                                   ["", closing])
    body, generated_by = _llm_polish_body(router, domain=domain, name=name, archetype=archetype,
                                          bullets=bullets, deterministic_body=deterministic_body,
                                          required_offer=required_offer)
    return {
        "schema": "qa-review-draft/v1", "domain": domain, "business_name": name,
        "archetype": archetype,
        "subject": subject, "problem_bullets": bullets, "body": body, "offer": offer,
        "fix_offer": fix_offer, "fixability": fixability,
        "generated_by": generated_by,
        "contact": contact, "sent": False, "available": True,
        "disclaimer": ("DRAFT only - the system does not send this. Copy and send it yourself after "
                       "review. Public info only; nothing was submitted to the site."),
    }

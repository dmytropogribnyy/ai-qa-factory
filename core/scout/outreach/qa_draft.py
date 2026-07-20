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
        same = [e for e in emails if e.lower().split("@")[-1].endswith(d)]
        if same:
            emails = same
    # generic mailboxes first (better for cold outreach than a personal address)
    emails.sort(key=lambda e: (0 if any(g in e.lower().split("@")[0] for g in _GENERIC) else 1, e))
    return emails[:5]


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
                     bullets: List[str], deterministic_body: str) -> tuple[str, str]:
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
        "only: no logins/forms/orders were used, and you must say so. Plain text, no markdown, no "
        "salutation placeholder names, under 160 words. Do not include secrets, prices, or links.")
    user = (
        f"Business: {name} ({domain}). Type: {archetype or 'website'}.\n"
        f"Issues found (verbatim, keep as a short bulleted list):\n" +
        "\n".join(f"- {b}" for b in bullets) +
        "\n\nWrite the email body only (start with 'Hi,'). Offer to share evidence and a "
        "prioritized fix list. Keep it honest and low-pressure.")
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
    return text, model


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
    subject = f"Quick QA review of {name} - {len(bullets)} public issue(s) I found"
    intro = (f"I ran a bounded, read-only QA check of your public website ({domain}) and noticed a "
             f"few issues that may affect conversion, accessibility, or user trust:")
    closing = ("These come from public pages only - no logins, form submissions, or orders. If "
               "useful, I can share the evidence and a prioritized fix list. Happy to help.")
    deterministic_body = "\n".join(["Hi,", "", intro, ""] + [f"- {b}" for b in bullets] +
                                   ["", closing])
    body, generated_by = _llm_polish_body(router, domain=domain, name=name, archetype=archetype,
                                          bullets=bullets, deterministic_body=deterministic_body)
    return {
        "schema": "qa-review-draft/v1", "domain": domain, "business_name": name,
        "archetype": archetype,
        "subject": subject, "problem_bullets": bullets, "body": body,
        "generated_by": generated_by,
        "contact": contact, "sent": False,
        "disclaimer": ("DRAFT only - the system does not send this. Copy and send it yourself after "
                       "review. Public info only; nothing was submitted to the site."),
    }

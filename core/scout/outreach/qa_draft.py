"""Copy-only QA-review outreach draft + public-contact extraction (v3.3).

Turns a target's verified QA findings into a concise, prioritized DRAFT letter and surfaces any
PUBLIC contact email found during the bounded scan. The system NEVER sends anything: the draft is
`sent=False`, copy-only, for the operator to review and send manually (project rule: no external
communication without explicit approval). Public emails are read-only, same-domain-preferred, and
governed by the existing outreach contact policy.
"""
from __future__ import annotations

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


def build_review_draft(*, domain: str, business_name: str = "",
                       understanding: Dict[str, Any] = None,
                       findings: List[Dict[str, Any]] = None,
                       contact: str = "") -> Dict[str, Any]:
    """Build a COPY-ONLY QA-review outreach draft. `sent` is always False; the system never sends."""
    name = (business_name or domain).strip()
    bullets = problem_bullets(findings or [])
    subject = f"Quick QA review of {name} - {len(bullets)} public issue(s) I found"
    intro = (f"I ran a bounded, read-only QA check of your public website ({domain}) and noticed a "
             f"few issues that may affect conversion, accessibility, or user trust:")
    closing = ("These come from public pages only - no logins, form submissions, or orders. If "
               "useful, I can share the evidence and a prioritized fix list. Happy to help.")
    body = "\n".join(["Hi,", "", intro, ""] + [f"- {b}" for b in bullets] + ["", closing])
    return {
        "schema": "qa-review-draft/v1", "domain": domain, "business_name": name,
        "archetype": (understanding or {}).get("archetype"),
        "subject": subject, "problem_bullets": bullets, "body": body,
        "contact": contact, "sent": False,
        "disclaimer": ("DRAFT only - the system does not send this. Copy and send it yourself after "
                       "review. Public info only; nothing was submitted to the site."),
    }

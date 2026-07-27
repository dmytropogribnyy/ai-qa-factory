"""Blocking-challenge detection — did the site refuse to serve its content?

A CAPTCHA / Turnstile / reCAPTCHA / hCaptcha widget on a site's OWN signup, newsletter, login or
contact form is part of the page under test, not a wall against us: the site answered with its
content and we can analyse it. Only a challenge that REPLACES the primary content is a blocker.

The predecessor of this module was a substring search over the whole HTML
(``any(m in html.lower() for m in ("captcha", ...))``). It matched a localisation string inside a
hydration ``<script>`` and a ``cf-turnstile`` div belonging to the site's own signup form, so a
fully served 200 page was abandoned as "the site requested a human verification check" and the
operator was offered a manual check with nothing to solve. Most B2B SaaS landing pages carry such a
widget, so the naive test silently dropped much of Scout's own target population.

Rules this module follows:

- marker text inside ``script`` / ``style`` / ``template`` / ``noscript`` (hydration payloads,
  localisation bundles) is never, on its own, evidence of a block;
- the mere presence of a widget element or a sitekey inside an ordinary form is not a block;
- a block needs a marker PLUS structural evidence: a blocking HTTP status, challenge wording in the
  title or H1, a known interstitial shape, or no primary content served at all;
- content density is corroboration only — a small legitimate page is never blocked for being small,
  because low density alone is never a challenge signal;
- a genuinely ambiguous low-content case fails closed as ``suspected``, and the operator surface
  must hedge its wording accordingly rather than assert a challenge it cannot prove.

Detection only. Scout never solves, bypasses, evades or outsources a challenge.

Known limit: whether a challenge visually covers the viewport is a layout question this static
parse cannot answer, so it is not among the signals below.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Sequence

CH_NONE = ""
CH_EMBEDDED = "embedded"        # the site's own anti-spam widget; content was served
CH_BLOCKING = "blocking"        # the challenge stands between us and the content

CONF_CONFIRMED = "confirmed"    # structural evidence; the operator surface may state it as fact
CONF_SUSPECTED = "suspected"    # fail-closed guess; the operator surface must hedge

R_CAPTCHA = "captcha_detected"
R_ACCESS = "access_prohibited"

# A status the site returns INSTEAD of its content.
_BLOCKING_STATUS = (401, 403, 429, 503)

# Titles a challenge interstitial carries. A page whose <title> is one of these is not the site.
_INTERSTITIAL_TITLES = ("just a moment", "attention required", "checking your browser",
                        "verify you are human", "are you a robot", "security check",
                        "access denied", "access to this page has been denied",
                        "you have been blocked", "bot verification", "one moment")

# Challenge wording, matched against VISIBLE text only.
_CAPTCHA_PHRASES = ("captcha", "i'm not a robot", "not a robot", "verify you are human",
                    "are you a robot", "checking your browser", "complete the security check",
                    "verify you are not a robot")
_ACCESS_PHRASES = ("access denied", "403 forbidden", "you have been blocked", "not authorized",
                   "please log in to continue")

# Titles above that indicate prohibition rather than a human check.
_ACCESS_TITLES = ("access denied", "access to this page has been denied", "you have been blocked")


@dataclass
class ChallengeVerdict:
    """What the page actually is, plus the evidence that says so."""
    kind: str = CH_NONE
    confidence: str = ""
    reason: str = ""            # R_CAPTCHA | R_ACCESS | ""
    signal: str = ""            # the concrete evidence, shown to the operator verbatim

    def blocks(self) -> bool:
        return self.kind == CH_BLOCKING

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def _first(hay: str, needles: Sequence[str]) -> str:
    for n in needles:
        if n in hay:
            return n
    return ""


def _primary_content_available(*, visible_text: str, links: Sequence[str],
                               headings: Sequence[Mapping[str, Any]],
                               forms: Sequence[Any]) -> bool:
    """Corroborating signal: did the response carry a page, or only a gate?

    Deliberately generous and satisfied by ANY one of several independent traits — a challenge
    interstitial has none of them, while a thin but legitimate page usually has at least one. It is
    only ever consulted alongside a challenge signal, so a quiet small page is never blocked by it.
    """
    text_len = len(visible_text.strip())
    return (text_len >= 400
            or len(links) >= 3
            or len(headings) >= 3
            or (len(forms) >= 1 and text_len >= 120))


def classify(*, status: int = 200, title: str = "", visible_text: str = "",
             headings: Sequence[Mapping[str, Any]] = (), links: Sequence[str] = (),
             forms: Sequence[Any] = (),
             widgets: Sequence[Mapping[str, Any]] = ()) -> ChallengeVerdict:
    """Classify a page as ``none`` / ``embedded`` / ``blocking``.

    ``visible_text`` must already exclude script/style/template/noscript payloads; ``widgets`` are
    the challenge elements found in the DOM, each ``{"kind": str, "in_form": bool}``.
    """
    low_title = " ".join((title or "").lower().split())
    low_text = " ".join((visible_text or "").lower().split())
    h1_text = " ".join(str(h.get("text", "")) for h in headings
                       if int(h.get("level", 0) or 0) == 1).lower()

    interstitial_title = _first(low_title, _INTERSTITIAL_TITLES)
    captcha_language = _first(low_text, _CAPTCHA_PHRASES)
    access_language = _first(low_text, _ACCESS_PHRASES)
    widget_kinds = [str(w.get("kind", "widget")) for w in widgets]
    widget_outside_form = any(not w.get("in_form") for w in widgets)

    if not (widget_kinds or interstitial_title or captcha_language or access_language):
        return ChallengeVerdict()               # nothing challenge-related on the page

    # A human check is something we are asked to pass; a prohibition is a door closed to us. The
    # operator's next step differs, so the two are never collapsed into one reason.
    human_check = bool(widget_kinds or captcha_language
                       or (interstitial_title and not _first(low_title, _ACCESS_TITLES)))
    reason = R_CAPTCHA if human_check else R_ACCESS

    content = _primary_content_available(visible_text=low_text, links=links,
                                         headings=headings, forms=forms)

    def blocking(confidence: str, signal: str) -> ChallengeVerdict:
        return ChallengeVerdict(kind=CH_BLOCKING, confidence=confidence, reason=reason,
                                signal=signal)

    # The site answered with a refusal instead of its content.
    if status in _BLOCKING_STATUS:
        return blocking(CONF_CONFIRMED, f"HTTP {status} answered instead of the page")
    # The response is titled as an interstitial, so it is not the site's own page.
    if interstitial_title:
        return blocking(CONF_CONFIRMED, f'page title "{(title or "").strip()[:70]}"')
    # The page's own headline is the challenge, and nothing else was served.
    if h1_text and _first(h1_text, _CAPTCHA_PHRASES + _ACCESS_PHRASES) and not content:
        return blocking(CONF_CONFIRMED, f'the page headline is "{h1_text.strip()[:70]}"')
    # A challenge element standing on its own, with no page around it: the interstitial shape.
    if widget_outside_form and not content:
        return blocking(CONF_CONFIRMED,
                        f"a {widget_kinds[0]} challenge was served instead of the page")
    # Ambiguous: challenge wording and nothing recognisable as a page. Fail closed, but say so.
    if not content and (captcha_language or access_language):
        return blocking(CONF_SUSPECTED,
                        f'"{(captcha_language or access_language)}" appears on a page with no '
                        "readable content")
    # Content was served. Any widget here belongs to the site's own form.
    if widget_kinds:
        return ChallengeVerdict(kind=CH_EMBEDDED, reason="", confidence="",
                                signal=f"the page embeds a {widget_kinds[0]} widget on its own form")
    return ChallengeVerdict()


def widget_from_attrs(tag: str, attrs: Mapping[str, str]) -> str:
    """Return the challenge-widget kind for an element, or "" — attribute/DOM evidence only.

    A ``<script src=...recaptcha...>`` is a resource, not a challenge, and is deliberately ignored:
    treating it as evidence is what produced the original false positives.
    """
    ident = f"{attrs.get('class', '')} {attrs.get('id', '')}".lower()
    src = (attrs.get("src", "") or "").lower()
    for kind, needles in (("turnstile", ("cf-turnstile", "turnstile")),
                          ("reCAPTCHA", ("g-recaptcha", "grecaptcha", "recaptcha")),
                          ("hCaptcha", ("h-captcha", "hcaptcha"))):
        if _first(ident, needles):
            return kind
        if tag == "iframe" and _first(src, needles + ("challenges.cloudflare.com",)):
            return kind
    if attrs.get("data-sitekey") and tag != "script":
        return "human-verification"
    return ""


def widgets_to_dicts(found: Sequence[Any]) -> List[Dict[str, Any]]:
    return [{"kind": k, "in_form": bool(f)} for k, f in found]

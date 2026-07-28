"""Browser backends + the normalized PageObservation (Phase 8.3).

A backend turns a URL into a `PageObservation` — a bounded, sanitized snapshot of a public
page. Two backends share the same observation shape:

- `StaticHttpBackend` (stdlib urllib + html.parser): no JavaScript, no browser, offline-safe.
  Follows redirects MANUALLY and re-validates every hop against URL safety (blocks
  redirect-to-internal). Used by the deterministic fixture E2E.
- `PlaywrightBackend` (optional, lazy import): a real browser for the live experience; adds
  console errors, failed resources, timing, and a rendered screenshot. Never required by tests.

Sanitization: response headers are reduced to a safe allowlist (no Set-Cookie / Authorization /
tokens); no raw cookies/credentials are ever stored on the observation.
"""
from __future__ import annotations

import os
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Callable, Dict, List, Optional, Protocol
from urllib.parse import urljoin

from core.scout.challenge_detect import (R_CAPTCHA, classify, widget_from_attrs,
                                         widgets_to_dicts)
from core.scout.url_safety import UrlPolicy, check_url

# Response headers we keep (lowercased). Everything else (cookies, auth, tokens) is dropped.
_SAFE_RESPONSE_HEADERS = frozenset({
    "content-type", "content-length", "cache-control", "server", "x-robots-tag",
    "content-security-policy", "strict-transport-security", "x-frame-options",
    "x-content-type-options", "referrer-policy", "vary", "content-language",
})
_MAX_REDIRECTS = 5
_MAX_EVENT_ITEMS = 200  # bound console-error / failed-resource / blocked-request arrays
_USER_AGENT = "ARK-Prospect-QA-Scout/1.0 (+local, read-only)"


@dataclass
class FormObservation:
    method: str = "get"
    action: str = ""
    field_count: int = 0
    has_required: bool = False
    input_types: List[str] = field(default_factory=list)
    field_names: List[str] = field(default_factory=list)
    submit_labels: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "method": self.method, "action": self.action, "field_count": self.field_count,
            "has_required": self.has_required, "input_types": list(self.input_types),
            "field_names": list(self.field_names), "submit_labels": list(self.submit_labels),
        }


# Bounded so a huge page cannot hold an unbounded string in memory during a run.
_TEXT_SAMPLE_LIMIT = 60_000


@dataclass
class PageObservation:
    """A bounded, sanitized snapshot of one public page."""

    url: str = ""
    final_url: str = ""
    redirect_chain: List[str] = field(default_factory=list)
    status: int = 0
    ok: bool = False
    fetch_error: str = ""
    content_type: str = ""
    html_bytes: int = 0
    truncated: bool = False
    title: str = ""
    meta_description: str = ""
    canonical: str = ""
    robots_meta: str = ""
    x_robots_tag: str = ""
    lang: str = ""
    has_viewport_meta: bool = False
    headers: Dict[str, str] = field(default_factory=dict)
    headings: List[Dict[str, Any]] = field(default_factory=list)   # {level:int, text:str}
    links: List[str] = field(default_factory=list)                 # absolute hrefs
    # A bounded slice of the page's visible text, held IN MEMORY ONLY and dropped at the persistence
    # boundary (Sanitizer.sanitize_observation). It exists for one reason: companies publish their
    # public mailbox as printed text far more often than as a mailto: href — all three live
    # acceptance targets do — so without it the pipeline's "find public contacts" step cannot work.
    # Nothing else reads it, and the page text is never operator evidence: we keep the address, not
    # the prose it was written in.
    text_sample: str = ""
    images: List[Dict[str, str]] = field(default_factory=list)     # {src, alt}
    forms: List[FormObservation] = field(default_factory=list)
    structured_data: List[Dict[str, Any]] = field(default_factory=list)
    landmarks: Dict[str, int] = field(default_factory=dict)        # nav/main/header/... counts
    input_labels_ok: bool = True
    # Challenge detection (core/scout/challenge_detect.py). The two *_marker flags mean the site
    # BLOCKED us, never "the word captcha occurs somewhere in the HTML" — a site's own anti-spam
    # widget leaves captcha_widget_present set and the markers clear, and the page is analysed.
    access_blocked_marker: bool = False
    captcha_marker: bool = False
    challenge_kind: str = ""            # "" | "embedded" | "blocking"
    challenge_confidence: str = ""      # "" | "confirmed" | "suspected"
    challenge_signal: str = ""          # the concrete evidence behind the verdict
    captcha_widget_present: bool = False   # the page carries a widget (blocking or not)
    # Playwright-only (empty for the static backend):
    console_errors: List[str] = field(default_factory=list)
    failed_resources: List[str] = field(default_factory=list)
    blocked_requests: List[str] = field(default_factory=list)   # unsafe requests we aborted
    timing_ms: Dict[str, float] = field(default_factory=dict)
    screenshot_ref: str = ""
    video_ref: str = ""            # rel path (under the prospect dir) to a kept reproduction video
    # Deep-QA (Playwright deep-capture only). axe_status distinguishes the three states so an
    # overlapping heuristic is suppressed ONLY when axe genuinely ran; "" = not attempted (static/off).
    axe_status: str = ""           # "" not attempted | "ok" (ran; violations may be empty) | "unavailable"
    axe_violations: List[Dict[str, Any]] = field(default_factory=list)  # bounded, redacted raw violations
    perf: Dict[str, Any] = field(default_factory=dict)   # raw nav timing (only when captured; {} = none)
    backend: str = "static"

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["forms"] = [f.to_dict() for f in self.forms]
        return d


class BrowserBackend(Protocol):
    name: str

    def observe(self, url: str, timeout_s: float, max_bytes: int, *,
                record_video: bool = False, deep_qa: bool = False) -> PageObservation: ...


# ---------------------------------------------------------------------------
# HTML parsing (stdlib)
# ---------------------------------------------------------------------------

# Tags whose payload is machine data, not page content: hydration state, localisation bundles,
# inert templates. Their text is deliberately excluded from the visible text used for detection.
_NON_VISIBLE_TAGS = frozenset({"script", "style", "template", "noscript"})


class _HtmlExtractor(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.title = ""
        self.meta_description = ""
        self.canonical = ""
        self.robots_meta = ""
        self.lang = ""
        self.has_viewport_meta = False
        self.headings: List[Dict[str, Any]] = []
        self.links: List[str] = []
        self.images: List[Dict[str, str]] = []
        self.landmarks: Dict[str, int] = {}
        self.jsonld_blocks: List[str] = []
        self.forms: List[FormObservation] = []
        # Text a human would actually read, and the challenge elements really present in the DOM.
        # Hydration/localisation payloads live in <script> and are NOT visible text — reading them
        # as page content is what made a site's own i18n string look like a challenge.
        self.visible_text: List[str] = []
        self.widgets: List[Any] = []        # (kind, in_form)
        self._suppress = 0
        self._in_title = False
        self._in_jsonld = False
        self._jsonld_buf: List[str] = []
        self._heading_stack: List[int] = []
        self._heading_buf: List[str] = []
        self._cur_form: Optional[FormObservation] = None
        self._unlabeled_inputs = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        kind = widget_from_attrs(tag, a)
        if kind:
            # Whether it sits inside one of the site's own forms decides embedded vs interstitial.
            self.widgets.append((kind, self._cur_form is not None))
        if tag in _NON_VISIBLE_TAGS:
            self._suppress += 1
        if tag == "html" and a.get("lang"):
            self.lang = a["lang"]
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            name = a.get("name", "").lower()
            if name == "description":
                self.meta_description = a.get("content", "")
            elif name == "robots":
                self.robots_meta = a.get("content", "")
            elif name == "viewport":
                self.has_viewport_meta = True
        elif tag == "link" and a.get("rel", "").lower() == "canonical":
            self.canonical = urljoin(self.base_url, a.get("href", ""))
        elif tag == "a" and a.get("href"):
            href = a["href"].strip()
            if href and not href.lower().startswith(("javascript:", "mailto:", "tel:", "#")):
                self.links.append(urljoin(self.base_url, href))
        elif tag == "img":
            self.images.append({"src": urljoin(self.base_url, a.get("src", "")), "alt": a.get("alt", "")})
        elif tag in ("nav", "main", "header", "footer", "aside"):
            self.landmarks[tag] = self.landmarks.get(tag, 0) + 1
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading_stack.append(int(tag[1]))
            self._heading_buf = []
        elif tag == "script" and a.get("type", "").lower() == "application/ld+json":
            self._in_jsonld = True
            self._jsonld_buf = []
        elif tag == "form":
            self._cur_form = FormObservation(method=(a.get("method", "get") or "get").lower(),
                                             action=urljoin(self.base_url, a.get("action", "")))
        elif tag in ("input", "textarea", "select") and self._cur_form is not None:
            self._cur_form.field_count += 1
            itype = a.get("type", "text").lower() if tag == "input" else tag
            self._cur_form.input_types.append(itype)
            if a.get("name"):
                self._cur_form.field_names.append(a["name"].lower())
            if "required" in a:
                self._cur_form.has_required = True
            has_label = bool(a.get("aria-label") or a.get("aria-labelledby") or a.get("title") or a.get("id"))
            if itype not in ("submit", "button", "hidden") and not has_label:
                self._unlabeled_inputs += 1
        elif tag == "button" and self._cur_form is not None and a.get("type", "submit") == "submit":
            pass  # captured on data

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag in _NON_VISIBLE_TAGS:
            self._suppress = max(0, self._suppress - 1)   # self-closing: no content to skip

    def handle_endtag(self, tag):
        if tag in _NON_VISIBLE_TAGS:
            self._suppress = max(0, self._suppress - 1)
        if tag == "title":
            self._in_title = False
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading_stack:
            level = self._heading_stack.pop()
            self.headings.append({"level": level, "text": " ".join("".join(self._heading_buf).split())})
            self._heading_buf = []
        elif tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            self.jsonld_blocks.append("".join(self._jsonld_buf))
        elif tag == "form" and self._cur_form is not None:
            self.forms.append(self._cur_form)
            self._cur_form = None

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        if self._in_jsonld:
            self._jsonld_buf.append(data)
        if self._heading_stack:
            self._heading_buf.append(data)
        if not self._suppress:
            self.visible_text.append(data)


def _parse_html(base_url: str, html: str, obs: PageObservation) -> None:
    ex = _HtmlExtractor(base_url)
    try:
        ex.feed(html)
    except Exception:  # malformed HTML must never crash the run
        pass
    obs.title = " ".join(ex.title.split())
    obs.meta_description = ex.meta_description
    obs.canonical = ex.canonical
    obs.robots_meta = ex.robots_meta
    obs.lang = ex.lang
    obs.has_viewport_meta = ex.has_viewport_meta
    obs.headings = ex.headings
    obs.links = list(dict.fromkeys(ex.links))
    obs.images = ex.images
    obs.landmarks = ex.landmarks
    obs.forms = ex.forms
    obs.input_labels_ok = ex._unlabeled_inputs == 0
    import json
    for block in ex.jsonld_blocks:
        try:
            obs.structured_data.append({"valid": True, "data": json.loads(block)})
        except Exception as exc:
            obs.structured_data.append({"valid": False, "error": str(exc)[:120]})
    visible_text = " ".join(ex.visible_text)
    # In-memory only; Sanitizer.sanitize_observation drops it before anything is written. The
    # extractor already excludes script/style/template/noscript payloads, so this is page prose.
    obs.text_sample = visible_text[:_TEXT_SAMPLE_LIMIT]
    # Was the page served, or withheld? Structure and visible text decide — never a substring
    # search over the raw HTML, which cannot tell a site's own signup widget from a wall.
    verdict = classify(status=obs.status, title=obs.title,
                       visible_text=visible_text, headings=obs.headings,
                       links=obs.links, forms=obs.forms,
                       widgets=widgets_to_dicts(ex.widgets))
    obs.challenge_kind = verdict.kind
    obs.challenge_confidence = verdict.confidence
    obs.challenge_signal = verdict.signal
    obs.captcha_widget_present = bool(ex.widgets)
    obs.captcha_marker = verdict.blocks() and verdict.reason == R_CAPTCHA
    obs.access_blocked_marker = verdict.blocks() and verdict.reason != R_CAPTCHA


def _safe_headers(raw_headers) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        items = raw_headers.items()
    except AttributeError:
        items = []
    for k, v in items:
        lk = k.lower()
        if lk in _SAFE_RESPONSE_HEADERS:
            out[lk] = v
    return out


# ---------------------------------------------------------------------------
# Static backend
# ---------------------------------------------------------------------------

class StaticHttpBackend:
    name = "static"

    def __init__(self, policy: Optional[UrlPolicy] = None) -> None:
        self.policy = policy or UrlPolicy()
        handler = _NoAutoRedirect()
        self._opener = urllib.request.build_opener(handler)

    def observe(self, url: str, timeout_s: float, max_bytes: int, *,
                record_video: bool = False, deep_qa: bool = False) -> PageObservation:
        obs = PageObservation(url=url, backend=self.name)  # static backend cannot record video
        current = url
        chain: List[str] = []
        for _ in range(_MAX_REDIRECTS + 1):
            elig = check_url(current, policy=self.policy)
            if not elig.eligible:
                obs.fetch_error = f"blocked URL in redirect chain: {elig.reason}"
                obs.final_url = current
                obs.redirect_chain = chain
                return obs
            req = urllib.request.Request(current, headers={"User-Agent": _USER_AGENT})
            try:
                resp = self._opener.open(req, timeout=timeout_s)
                status, headers, reader = resp.status, resp.headers, resp
            except urllib.error.HTTPError as e:
                status, headers, reader = e.code, e.headers, e
            except Exception as exc:  # timeout / connection / etc.
                obs.fetch_error = f"fetch error: {type(exc).__name__}: {str(exc)[:160]}"
                obs.final_url = current
                obs.redirect_chain = chain
                return obs

            if 300 <= status < 400 and headers.get("Location"):
                nxt = urljoin(current, headers["Location"])
                chain.append(current)
                current = nxt
                continue

            obs.status = status
            obs.ok = 200 <= status < 300
            obs.headers = _safe_headers(headers)
            obs.content_type = obs.headers.get("content-type", "")
            obs.x_robots_tag = obs.headers.get("x-robots-tag", "")
            obs.final_url = current
            obs.redirect_chain = chain
            try:
                body = reader.read(max_bytes + 1)
            except Exception as exc:
                obs.fetch_error = f"read error: {str(exc)[:120]}"
                return obs
            if len(body) > max_bytes:
                obs.truncated = True
                body = body[:max_bytes]
            obs.html_bytes = len(body)
            if "html" in obs.content_type or not obs.content_type:
                text = body.decode("utf-8", errors="replace")
                _parse_html(obs.final_url, text, obs)
            return obs

        obs.fetch_error = "too many redirects"
        obs.final_url = current
        obs.redirect_chain = chain
        return obs


class _NoAutoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # never auto-follow; the backend validates each hop itself


# ---------------------------------------------------------------------------
# Optional Playwright backend (lazy; not required by tests)
# ---------------------------------------------------------------------------

class PlaywrightBackend:
    """Optional real-browser backend with SSRF-hardened navigation.

    Every request the page makes is intercepted and validated against the same URL policy
    (blocking redirects/subresources/navigations to loopback / private / link-local / reserved
    addresses and unsupported schemes). The final URL after navigation is re-validated; if it
    is unsafe the page content is NOT read. Rendered HTML is byte-bounded, event arrays are
    bounded, and the browser/context always close. A ``_playwright_factory`` seam lets the
    adversarial tests drive the full flow with fakes (no real browser required).
    """

    name = "playwright"

    def __init__(self, policy: Optional[UrlPolicy] = None, screenshot_dir: Optional[str] = None,
                 _playwright_factory=None, headful: Optional[bool] = None,
                 manual_gate: Optional[Callable[[Any, PageObservation], str]] = None) -> None:
        self.policy = policy or UrlPolicy()
        self.screenshot_dir = screenshot_dir
        self.screenshot_filename = "page.png"
        self._playwright_factory = _playwright_factory
        self.headful = headful          # None -> follow SCOUT_HEADFUL env; True/False -> force
        # Optional human-in-the-loop checkpoint.  It is used only by the explicit Dashboard
        # "Open manual check" action; unattended Scout never waits for or bypasses a challenge.
        self.manual_gate = manual_gate
        # Browser storage state is kept in memory only and reused across this backend's observations.
        # It is never written into evidence, logs, or tracked files.
        self._session_state: Optional[Dict[str, Any]] = None

    def _url_allowed(self, url: str) -> bool:
        return check_url(url, policy=self.policy).eligible

    def observe(self, url: str, timeout_s: float, max_bytes: int, *,
                record_video: bool = False, deep_qa: bool = False) -> PageObservation:
        obs = PageObservation(url=url, backend=self.name)
        elig = check_url(url, policy=self.policy)
        if not elig.eligible:
            obs.fetch_error = f"blocked URL: {elig.reason}"
            return obs
        factory = self._playwright_factory
        if factory is None:
            try:
                from playwright.sync_api import sync_playwright  # lazy: optional dependency
                factory = sync_playwright
            except Exception as exc:  # pragma: no cover - only when playwright missing
                obs.fetch_error = (
                    "playwright is not installed. Run: pip install playwright && "
                    f"python -m playwright install chromium  ({exc})"
                )
                return obs
        with factory() as p:
            # Headless by default (unattended, background-safe). An explicit headful flag (e.g. a
            # headed replay) wins; otherwise SCOUT_HEADFUL=1 opens a visible, slow-mo window to WATCH.
            headful = (self.headful if self.headful is not None
                       else os.getenv("SCOUT_HEADFUL", "").lower() in ("1", "true", "yes", "on"))
            launch_kwargs: Dict[str, Any] = {"headless": not headful}
            if headful:
                launch_kwargs["slow_mo"] = 400
            browser = p.chromium.launch(**launch_kwargs)
            ctx_kwargs: Dict[str, Any] = {}
            vidtmp = None
            # Opt-in reproduction recording: only when asked AND a per-prospect dir is set. The temp
            # clip is qualified and kept-or-deleted later by the engine (never kept unreproduced).
            if record_video and self.screenshot_dir:
                vidtmp = os.path.join(self.screenshot_dir, "_vidtmp")
                os.makedirs(vidtmp, exist_ok=True)
                ctx_kwargs["record_video_dir"] = vidtmp
            if self._session_state:
                ctx_kwargs["storage_state"] = self._session_state
            context = browser.new_context(**ctx_kwargs)
            video = None
            try:
                page = context.new_page()
                self._observe_with_page(page, url, timeout_s, max_bytes, obs)
                # A manual session keeps this exact visible browser/context open while the operator
                # handles Cloudflare/CAPTCHA.  "Continue" rechecks in the same context; unresolved
                # challenges return to the waiting state.  Defer/skip stops without interaction.
                manual_rounds = 0
                while self.manual_gate and self._needs_manual_action(obs) and manual_rounds < 20:
                    action = str(self.manual_gate(page, obs) or "").strip().lower()
                    if action != "continue":
                        obs.fetch_error = ("manual check deferred" if action == "defer"
                                           else "manual check skipped")
                        break
                    manual_rounds += 1
                    refreshed = PageObservation(url=page.url or url, backend=self.name)
                    self._observe_with_page(page, page.url or url, timeout_s, max_bytes, refreshed,
                                            install_handlers=False)
                    obs = refreshed
                if not self._needs_manual_action(obs):
                    try:
                        # Keep cookies/session in process memory for the verification pass and
                        # bounded same-site probes. Never persist them as evidence.
                        self._session_state = context.storage_state()
                    except Exception:
                        self._session_state = None
                if deep_qa and obs.ok:
                    self._collect_deep_qa(page, obs)    # real perf + axe on the already-open page
                if vidtmp is not None:
                    video = page.video          # grab the handle BEFORE close finalizes the file
            except Exception as exc:
                obs.fetch_error = f"browser error: {type(exc).__name__}: {str(exc)[:160]}"
            finally:
                self._safe_close(context, browser)   # closing the context flushes the .webm to disk
            if video is not None:
                try:                             # basename only — never leak an absolute path
                    obs.video_ref = os.path.join("_vidtmp", os.path.basename(video.path()))
                except Exception:
                    pass
        return obs

    @staticmethod
    def _needs_manual_action(obs: PageObservation) -> bool:
        return bool(obs.captcha_marker or obs.access_blocked_marker or obs.status in (401, 403, 429))

    def _observe_with_page(self, page, url: str, timeout_s: float, max_bytes: int,
                           obs: PageObservation, *, install_handlers: bool = True) -> None:
        console_errors: List[str] = []
        failed: List[str] = []
        blocked: List[str] = []

        def _on_route(route):
            req_url = getattr(getattr(route, "request", None), "url", "") or ""
            if self._url_allowed(req_url):
                route.continue_()
            else:
                blocked.append(req_url)
                route.abort()

        if install_handlers:
            page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
            page.on("requestfailed", lambda r: failed.append(r.url))
            page.route("**/*", _on_route)

        start = time.time()
        response = page.goto(url, wait_until="load", timeout=timeout_s * 1000)
        obs.timing_ms["load"] = round((time.time() - start) * 1000, 1)
        obs.blocked_requests = blocked[:_MAX_EVENT_ITEMS]
        obs.console_errors = console_errors[:_MAX_EVENT_ITEMS]
        obs.failed_resources = failed[:_MAX_EVENT_ITEMS]

        # Re-validate the URL we actually ended on (redirects may have moved us).
        final_url = page.url
        obs.final_url = final_url
        if not self._url_allowed(final_url):
            obs.fetch_error = f"final URL blocked after navigation: {final_url}"
            obs.ok = False
            return  # never read/parse content from an unsafe destination

        obs.status = response.status if response else 0
        obs.ok = bool(response and 200 <= response.status < 300)
        obs.headers = _safe_headers(_HeaderShim(response.headers if response else {}))
        obs.content_type = obs.headers.get("content-type", "")

        html = page.content()
        encoded = html.encode("utf-8", errors="replace")
        if len(encoded) > max_bytes:
            obs.truncated = True
            obs.html_bytes = max_bytes
            html = encoded[:max_bytes].decode("utf-8", errors="replace")
        else:
            obs.html_bytes = len(encoded)
        _parse_html(final_url, html, obs)

        if self.screenshot_dir:
            import os
            os.makedirs(self.screenshot_dir, exist_ok=True)
            filename = os.path.basename(str(self.screenshot_filename or "page.png"))
            if not filename.lower().endswith(".png"):
                filename = "page.png"
            shot = os.path.join(self.screenshot_dir, filename)
            page.screenshot(path=shot)
            obs.screenshot_ref = filename  # basename only — never leak an absolute path

    def _collect_deep_qa(self, page, obs: PageObservation) -> None:
        """Deep-QA on the already-open page: real navigation timing (captured BEFORE axe adds CPU
        work) + real axe-core. Each capability failure is ISOLATED as unavailable coverage — it never
        fabricates a clean result and never fails the whole observation."""
        from core.scout.pipeline.browser_qa import PERF_JS, collect_axe_on_page
        try:
            m = page.evaluate(PERF_JS)
            if isinstance(m, dict):
                obs.perf = {k: m.get(k) for k in ("domContentLoaded", "loadEvent", "responseEnd",
                                                  "resourceCount", "transferBytes",
                                                  "largestResourceBytes")}
        except Exception:
            obs.perf = {}                      # timing unavailable -> honest coverage, not a pass
        try:
            obs.axe_violations = collect_axe_on_page(page)
            obs.axe_status = "ok"              # ran (violations may legitimately be empty)
        except Exception:
            obs.axe_status, obs.axe_violations = "unavailable", []

    def reproduce_interaction(self, start_url: str, action_url: str, record_dir: str, *,
                              timeout_s: float = 20.0) -> Dict[str, Any]:
        """Bounded, read-only reproduction: in ONE recorded browser context, load the start URL
        (precondition), follow the exact interaction (navigate to action_url), observe the actual
        result, stop, and verify cleanup. Records a video of the ACTUAL interaction — never a
        page-load-only clip. Never submits a form, logs in, or triggers a side effect. Returns the
        action log, final URL, actual status, cleanup flag, and video_ref (relative to record_dir)."""
        result: Dict[str, Any] = {"start_url": start_url, "action_url": action_url, "action_log": [],
                                  "precondition_ok": False, "final_url": "", "actual_status": None,
                                  "cleanup_ok": False, "video_ref": ""}
        if not self._url_allowed(start_url) or not self._url_allowed(action_url):
            result["action_log"].append("blocked: a URL is not eligible")
            return result
        factory = self._playwright_factory
        if factory is None:
            try:
                from playwright.sync_api import sync_playwright  # lazy: optional dependency
                factory = sync_playwright
            except Exception as exc:  # pragma: no cover - only when playwright missing
                result["action_log"].append(f"playwright unavailable: {type(exc).__name__}")
                return result
        vidtmp = os.path.join(record_dir, "_reprotmp")
        os.makedirs(vidtmp, exist_ok=True)
        with factory() as p:
            headful = (self.headful if self.headful is not None
                       else os.getenv("SCOUT_HEADFUL", "").lower() in ("1", "true", "yes", "on"))
            launch_kwargs: Dict[str, Any] = {"headless": not headful}
            if headful:
                launch_kwargs["slow_mo"] = 400
            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(record_video_dir=vidtmp)
            video = None

            def _on_route(route):
                req_url = getattr(getattr(route, "request", None), "url", "") or ""
                if self._url_allowed(req_url):
                    route.continue_()
                else:
                    route.abort()

            try:
                page = context.new_page()
                page.route("**/*", _on_route)
                # PRECONDITION: establish the start page. If THIS fails, no interaction happened — it is
                # NOT a reproduction and its (precondition-only) clip must never be surfaced.
                try:
                    page.goto(start_url, wait_until="load", timeout=timeout_s * 1000)
                    result["precondition_ok"] = True
                    result["action_log"].append("goto start_url")
                except Exception as exc:
                    result["action_log"].append(f"precondition failed: {type(exc).__name__}")
                if result["precondition_ok"]:
                    # INTERACTION: follow the flow entry. A broken action (404 / unreachable) reproduces
                    # the finding; an action that loads fine does not.
                    try:
                        resp = page.goto(action_url, wait_until="load", timeout=timeout_s * 1000)
                        result["actual_status"] = resp.status if resp else 0
                    except Exception as exc:
                        result["action_log"].append(f"action navigation error: {type(exc).__name__}")
                        result["actual_status"] = 0            # unreachable action = broken
                    result["action_log"].append("follow flow entry")
                    result["final_url"] = page.url
                    video = page.video                        # captured ONLY on the interaction path
                    # Cleanup is by construction: this method performs ONLY read-only navigations (it
                    # never clicks/fills/submits/mutates), so completing the read-only path leaves no
                    # side effect. Reported ONLY here (never blanket-asserted on an unexpected error).
                    result["cleanup_ok"] = True
            except Exception as exc:  # noqa: BLE001 - an unexpected browser error -> keep no clip
                result["action_log"].append(f"reproduction error: {type(exc).__name__}")
                video = None
            finally:
                self._safe_close(context, browser)   # closing the context flushes the .webm
            # NEVER surface a precondition-only clip: a video_ref is set only when the interaction ran.
            if video is not None and result["precondition_ok"]:
                try:
                    result["video_ref"] = os.path.join("_reprotmp", os.path.basename(video.path()))
                except Exception:
                    pass
        return result

    def record_interaction_scenario(self, url: str, record_dir: str, *,
                                    timeout_s: float = 20.0,
                                    settle_s: float = 4.0) -> Dict[str, Any]:
        """Perform ONE bounded reversible interaction on a public page, recorded end to end.

        The page is inspected before anything is touched: the control is found by shape, not by a
        selector written down months ago against a site that has since changed. Everything happens
        in a single recorded context so the clip contains the baseline, the action and the cleanup
        in one continuous sequence — a video assembled from separate contexts would show a state
        transition that never actually occurred.

        Read-only in the sense that matters: no form is submitted, no navigation is followed, and
        whatever was changed is changed back before the recording stops.
        """
        from core.scout.interaction_scenario import (FIND_CANDIDATE_JS, OUTCOME_NOT_APPLICABLE,
                                                     OUTCOME_NOT_RUN, ScenarioResult,
                                                     screen_candidate)
        from core.scout.interaction_scenario import classify as classify_scenario

        result = ScenarioResult(url=url)
        if not self._url_allowed(url):
            result.reason, result.error = "the URL is not eligible", "blocked_url"
            return result.to_dict()
        factory = self._playwright_factory
        if factory is None:
            try:
                from playwright.sync_api import sync_playwright  # lazy: optional dependency
                factory = sync_playwright
            except Exception as exc:  # pragma: no cover - only when playwright missing
                result.reason, result.error = "no browser is available", type(exc).__name__
                return result.to_dict()
        vidtmp = os.path.join(record_dir, "_scenariotmp")
        os.makedirs(vidtmp, exist_ok=True)
        with factory() as p:
            headful = (self.headful if self.headful is not None
                       else os.getenv("SCOUT_HEADFUL", "").lower() in ("1", "true", "yes", "on"))
            launch_kwargs: Dict[str, Any] = {"headless": not headful}
            if headful:
                launch_kwargs["slow_mo"] = 400
            browser = p.chromium.launch(**launch_kwargs)
            context = browser.new_context(record_video_dir=vidtmp)
            video = None
            try:
                page = context.new_page()
                # Fail closed on the WIRE, not only on the control. Whatever a page does in
                # response to a click, it may not write to anybody's server: an allow-listed domain
                # is permission to read it, and same-origin is not an exception to that. A blocked
                # request is recorded so a refusal can never be mistaken for a quiet success.
                page.route("**/*", lambda route: self._route_readonly(route, result))
                page.goto(url, wait_until="load", timeout=timeout_s * 1000)
                result.steps.append(f"open {url}")
                self._settle(page, 1.0)
                candidate = page.evaluate(FIND_CANDIDATE_JS)
                allowed, refusal = screen_candidate(candidate)
                if not allowed:
                    # Something WAS found and declined, or nothing qualified at all. Say which:
                    # "not applicable" carries the refusal, "not_run" means there was nothing here.
                    result.reason = refusal
                    result.outcome = (OUTCOME_NOT_APPLICABLE if isinstance(candidate, dict)
                                      else OUTCOME_NOT_RUN)
                    video = page.video
                    return self._finish_scenario(result, context, browser, vidtmp, video, record_dir)
                result.scenario = str(candidate["kind"])
                result.control_label = str(candidate.get("label") or "")
                result.click_selector = str(candidate.get("click_selector") or "")
                selector = str(candidate["selector"])
                self._wait_interactive(page, result, selector)
                result.baseline = dict(self._measure(page, result, selector))
                result.baseline["control_label"] = result.control_label
                result.steps.append(
                    f"record baseline: {self._describe_state(result.scenario, result.baseline)}")

                if not self._act(page, result, selector, settle_s):
                    result.outcome = OUTCOME_NOT_APPLICABLE
                    video = page.video
                    return self._finish_scenario(result, context, browser, vidtmp, video, record_dir)
                result.observed = dict(self._measure(page, result, selector))
                result.steps.append(
                    f"observe result: {self._describe_state(result.scenario, result.observed)}")

                result.cleanup_ok = self._revert(page, result, selector, settle_s)
                result.after_cleanup = dict(self._measure(page, result, selector))
                result.steps.append("restore the page to its original state"
                                    if result.cleanup_ok else "cleanup could not be verified")
                result.final_url = page.url
                navigated = not _same_page(url, page.url)
                result.outcome, result.reason = classify_scenario(
                    result.scenario, result.baseline, result.observed,
                    action_performed=result.action_performed, cleanup_ok=result.cleanup_ok,
                    navigated_away=navigated, blocked_writes=len(result.blocked_requests))
                self._settle(page, 1.0)          # a beat of the restored page closes the sequence
                video = page.video
            except Exception as exc:  # noqa: BLE001 - a browser failure keeps no clip and no claim
                result.error = f"{type(exc).__name__}: {str(exc)[:120]}"
                result.reason = "the interaction could not be completed"
                result.outcome = "not_run"
                video = None
            finally:
                pass
            return self._finish_scenario(result, context, browser, vidtmp, video, record_dir)

    def _route_readonly(self, route, result) -> None:
        """Let a read through; refuse anything that would change someone else's data."""
        from core.scout.interaction_scenario import SAFE_HTTP_METHODS
        request = getattr(route, "request", None)
        url = str(getattr(request, "url", "") or "")
        method = str(getattr(request, "method", "GET") or "GET").upper()
        if not self._url_allowed(url):
            route.abort()
            return
        if method not in SAFE_HTTP_METHODS:
            # Recorded, not silently dropped: an operator reading the scenario must be able to see
            # that the page tried to write and was stopped, rather than wonder why it looked inert.
            result.blocked_requests.append({"method": method, "url": url[:200]})
            route.abort()
            return
        route.continue_()

    def _act(self, page, result, selector: str, settle_s: float) -> bool:
        """Perform the one action this scenario is about, and wait for the page to answer.

        Returns False when the action was refused on inspection — the option a select was about to
        be switched to is screened HERE, because the select passing its own label check says
        nothing about its contents: a "Plan" dropdown is ordinary until the alternative is
        "Cancel subscription".
        """
        from core.scout.interaction_scenario import (SCENARIO_ADD_REMOVE, SCENARIO_FILTER,
                                                     SCENARIO_SELECT, safe_option)
        target = page.locator(selector).first
        if result.scenario == SCENARIO_FILTER:
            result.action = f"select the {result.control_label or 'filter'} filter"
            self._click_control(page, result, selector)
        elif result.scenario == SCENARIO_ADD_REMOVE:
            result.action = f"click {result.control_label}"
            target.click(timeout=8000)
        elif result.scenario == SCENARIO_SELECT:
            options = result.baseline.get("option_labels") or []
            wanted = next((o for o in options if o != result.baseline.get("selected_label")), None)
            allowed, refusal = safe_option(wanted or "")
            if not allowed:
                result.reason = refusal
                return False
            result.action = f"choose {wanted}"
            target.select_option(label=wanted, timeout=8000)
        result.action_performed = True
        result.steps.append(result.action)
        self._await_change(page, result, selector, result.baseline, settle_s)
        return True

    @staticmethod
    def _measure(page, result, selector: str) -> Dict[str, Any]:
        """One reading of the page. The control's label travels with the selector so a re-rendered
        page can still be measured rather than reported as silent."""
        from core.scout.interaction_scenario import MEASURE_JS
        return page.evaluate(MEASURE_JS, {"selector": selector, "label": result.control_label})

    def _wait_interactive(self, page, result, selector: str, budget_s: float = 10.0) -> None:
        """Wait until the page has finished rendering ITSELF before touching it.

        A single-page app serves its markup and attaches its handlers separately. Clicking in
        between does nothing at all — and "nothing happened" is precisely the observation this
        scenario exists to report, so acting too early would manufacture the defect it is looking
        for. The page is considered ready when two consecutive readings agree.
        """
        try:
            page.wait_for_load_state("networkidle", timeout=int(budget_s * 1000))
        except Exception:  # noqa: BLE001 - a busy page is not an error; the stability check decides
            pass
        deadline = time.monotonic() + budget_s
        previous = None
        while time.monotonic() < deadline:
            try:
                now = self._measure(page, result, selector)
            except Exception:  # noqa: BLE001
                return
            same = previous is not None and all(
                now.get(k) == previous.get(k) for k in ("result_count", "item_signature"))
            if same and (now.get("result_count") is not None or now.get("item_signature")):
                return
            previous = now
            page.wait_for_timeout(400)

    def _click_control(self, page, result, selector: str) -> None:
        """Click the control the way a visitor would.

        A styled filter is an invisible ``<input>`` behind a visible label; Playwright's ``check()``
        refuses to act on it, and forcing the input would bypass the site's own click handler and
        prove nothing about what a person experiences. So the label is the target, and the input's
        state afterwards is the evidence that the click landed.
        """
        clickable = getattr(result, "click_selector", "") or selector
        try:
            page.locator(clickable).first.click(timeout=8000)
        except Exception:
            page.locator(selector).first.check(timeout=8000)   # a plain, visible checkbox

    def _revert(self, page, result, selector: str, settle_s: float) -> bool:
        """Put the page back, and CHECK that it went back — never assume it did."""
        from core.scout.interaction_scenario import (SCENARIO_ADD_REMOVE, SCENARIO_FILTER,
                                                     SCENARIO_SELECT)
        try:
            if result.scenario == SCENARIO_FILTER:
                self._click_control(page, result, selector)
                self._await_change(page, result, selector, result.observed, settle_s)
                return self._measure(page, result, selector).get("control_engaged") is False
            if result.scenario == SCENARIO_SELECT:
                page.locator(selector).first.select_option(
                    label=result.baseline.get("selected_label"), timeout=8000)
                return (self._measure(page, result, selector).get("selected_label")
                        == result.baseline.get("selected_label"))
            if result.scenario == SCENARIO_ADD_REMOVE:
                remover = page.get_by_role("button", name=re.compile("delete|remove", re.I)).first
                remover.click(timeout=8000)
                self._await_change(page, result, selector, result.observed, settle_s)
                return (self._measure(page, result, selector).get("removable_count", 0)
                        <= int(result.baseline.get("removable_count") or 0))
        except Exception:  # noqa: BLE001 - an unverified cleanup is reported, never asserted
            return False
        return False

    def _await_change(self, page, result, selector: str, before: Dict[str, Any],
                      settle_s: float) -> None:
        """Wait for the page to respond, bounded — never a long blind sleep.

        A filter that does nothing is exactly the case being investigated, so this returns after the
        budget rather than failing: "it never changed" is the observation, not an error.
        """
        from core.scout.interaction_scenario import SCENARIO_ADD_REMOVE, SCENARIO_SELECT
        # ONLY the signals this scenario is actually asking about. A checkbox reports itself checked
        # the instant it is clicked, so watching the control's own state would end the wait before
        # the page had rendered anything — and the page would then be recorded as having answered
        # with the results it still had. That reads as "the filter did nothing", which is the exact
        # conclusion this method must never reach by accident.
        keys = {SCENARIO_ADD_REMOVE: ("removable_count",),
                SCENARIO_SELECT: ("selected_label",)}.get(
                    result.scenario, ("result_count", "item_signature"))
        deadline = time.monotonic() + max(0.5, settle_s)
        changed_at = None
        while time.monotonic() < deadline:
            try:
                now = self._measure(page, result, selector)
            except Exception:  # noqa: BLE001 - a transient evaluation error is not an answer
                break
            if any(now.get(k) != before.get(k) for k in keys):
                # Seen a change: let it settle briefly so a half-rendered list is not the reading.
                if changed_at is None:
                    changed_at = time.monotonic()
                elif time.monotonic() - changed_at >= 0.5:
                    break
            page.wait_for_timeout(250)

    @staticmethod
    def _settle(page, seconds: float) -> None:
        page.wait_for_timeout(int(max(0.0, seconds) * 1000))

    @staticmethod
    def _describe_state(scenario: str, state: Dict[str, Any]) -> str:
        from core.scout.interaction_scenario import SCENARIO_ADD_REMOVE, SCENARIO_SELECT
        if scenario == SCENARIO_SELECT:
            return f"selected option {state.get('selected_label')!r}"
        if scenario == SCENARIO_ADD_REMOVE:
            return f"{state.get('removable_count', 0)} removable element(s)"
        count = state.get("result_count")
        # The signature's FIRST element is the size of the collection; the rest is a bounded sample
        # of it. Reporting the sample length said "13 listed" for a page showing 25.
        signature = state.get("item_signature") or []
        listed = signature[0] if signature else "no"
        return (f"{count if count is not None else 'no'} results stated, {listed} listed item(s), "
                f"control engaged={bool(state.get('control_engaged'))}")

    def _finish_scenario(self, result, context, browser, vidtmp: str, video, record_dir: str
                         ) -> Dict[str, Any]:
        """Close the context (which flushes the .webm) and bind the clip only if it earned it."""
        self._safe_close(context, browser)
        if video is not None and result.keeps_video:
            try:
                result.video_ref = os.path.join("_scenariotmp", os.path.basename(video.path()))
            except Exception:  # noqa: BLE001 - an unreadable clip is simply not offered
                result.video_ref = ""
        return result.to_dict()

    @staticmethod
    def _safe_close(*closables) -> None:
        for c in closables:
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass


def _same_page(before: str, after: str) -> bool:
    """Did the interaction stay on the page it started on?

    Path and host only: a filter that rewrites the query string (``?vendor=apple``) has not
    navigated away in any sense that matters, while a click that lands on another document has.
    """
    from urllib.parse import urlsplit
    try:
        first, second = urlsplit(before or ""), urlsplit(after or "")
    except ValueError:
        return False
    return (first.netloc, first.path.rstrip("/")) == (second.netloc, second.path.rstrip("/"))


class _HeaderShim:
    def __init__(self, d: Dict[str, str]) -> None:
        self._d = d

    def items(self):
        return self._d.items()


def make_backend(mode: str, policy: Optional[UrlPolicy] = None, screenshot_dir: Optional[str] = None,
                 headful: Optional[bool] = None):
    if mode == "playwright":
        return PlaywrightBackend(policy=policy, screenshot_dir=screenshot_dir, headful=headful)
    return StaticHttpBackend(policy=policy)

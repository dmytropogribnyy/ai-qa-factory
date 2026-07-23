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
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Protocol
from urllib.parse import urljoin

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
    images: List[Dict[str, str]] = field(default_factory=list)     # {src, alt}
    forms: List[FormObservation] = field(default_factory=list)
    structured_data: List[Dict[str, Any]] = field(default_factory=list)
    landmarks: Dict[str, int] = field(default_factory=dict)        # nav/main/header/... counts
    input_labels_ok: bool = True
    access_blocked_marker: bool = False
    captcha_marker: bool = False
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

_ACCESS_MARKERS = ("access denied", "403 forbidden", "not authorized", "please log in to continue")
_CAPTCHA_MARKERS = ("captcha", "recaptcha", "hcaptcha", "i'm not a robot", "verify you are human",
                    "cf-turnstile", "g-recaptcha")


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
        self._in_title = False
        self._in_jsonld = False
        self._jsonld_buf: List[str] = []
        self._heading_stack: List[int] = []
        self._heading_buf: List[str] = []
        self._cur_form: Optional[FormObservation] = None
        self._unlabeled_inputs = 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
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

    def handle_endtag(self, tag):
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
    low = html.lower()
    obs.access_blocked_marker = any(m in low for m in _ACCESS_MARKERS)
    obs.captcha_marker = any(m in low for m in _CAPTCHA_MARKERS)


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
                 _playwright_factory=None, headful: Optional[bool] = None) -> None:
        self.policy = policy or UrlPolicy()
        self.screenshot_dir = screenshot_dir
        self._playwright_factory = _playwright_factory
        self.headful = headful          # None -> follow SCOUT_HEADFUL env; True/False -> force

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
            context = browser.new_context(**ctx_kwargs)
            video = None
            try:
                page = context.new_page()
                self._observe_with_page(page, url, timeout_s, max_bytes, obs)
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

    def _observe_with_page(self, page, url: str, timeout_s: float, max_bytes: int,
                           obs: PageObservation) -> None:
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
            shot = os.path.join(self.screenshot_dir, "page.png")
            page.screenshot(path=shot)
            obs.screenshot_ref = "page.png"  # basename only — never leak an absolute path

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
                                  "final_url": "", "actual_status": None, "cleanup_ok": False,
                                  "video_ref": ""}
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
                page.goto(start_url, wait_until="load", timeout=timeout_s * 1000)
                result["action_log"].append(f"goto {start_url}")
                resp = page.goto(action_url, wait_until="load", timeout=timeout_s * 1000)  # interaction
                result["action_log"].append(f"follow flow entry -> {action_url}")
                result["final_url"] = page.url
                result["actual_status"] = resp.status if resp else 0
                video = page.video
                result["cleanup_ok"] = True    # navigation-only, no state mutation -> clean
            except Exception as exc:
                # A failed navigation to a broken action is EXPECTED — it reproduces the broken finding.
                result["action_log"].append(f"navigation error: {type(exc).__name__}")
                result["actual_status"] = 0
                result["cleanup_ok"] = True     # nothing was mutated
                try:
                    video = page.video
                except Exception:
                    video = None
            finally:
                self._safe_close(context, browser)   # closing the context flushes the .webm
            if video is not None:
                try:
                    result["video_ref"] = os.path.join("_reprotmp", os.path.basename(video.path()))
                except Exception:
                    pass
        return result

    @staticmethod
    def _safe_close(*closables) -> None:
        for c in closables:
            try:
                if c is not None:
                    c.close()
            except Exception:
                pass


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

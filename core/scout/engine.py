"""Scout run engine (Phase 8.3).

Orchestrates one bounded, read-only run:

campaign/seeds -> URL eligibility -> profiling -> browser checks (first pass) ->
independent second pass -> verification -> sanitized evidence -> scoring -> persistence.

CAPTCHA / explicit-access-prohibition pages become MANUAL_ACTION_REQUIRED (no interaction,
no bypass) and pause that prospect while other safe prospects continue. Control
(pause/resume/cancel/global-kill) is checked cooperatively; a kill stops future work and
interrupts the active loop. Nothing is ever submitted, logged into, or sent.
"""
from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlsplit

from core.scout.backends import PageObservation, make_backend
from core.scout.checks import CheckContext, run_checks
from core.scout.config import ScoutRunConfig
from core.scout.control import RunControl
from core.scout.coverage import make_planner
from core.scout.evidence_policy import EvidenceSettings, VIDEO_QUALIFIED_AUTO, video_qualified
from core.scout.findings import ScoutFinding
from core.scout.sanitize import Sanitizer
from core.scout.scoring import build_scorecard
from core.scout.store import RunStore, StoreError
from core.scout.url_safety import dedupe_eligible
from core.scout.verification import IndependentVerifier

_SEV_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3}


def _finding_reproduced(finding: ScoutFinding, rep: dict) -> bool:
    """Did the reproduction run genuinely re-exhibit the finding? The start-page PRECONDITION must have
    been established (else the interaction never happened and a precondition-only clip is meaningless),
    AND for a broken primary flow entry the followed action must be ACTUALLY broken (HTTP >= 400 or an
    unreachable/zero status). A clip where the precondition failed or the action loaded fine is never
    kept as reproduction evidence."""
    if not rep.get("precondition_ok"):
        return False
    if finding.signature == "flow_entry_broken":
        st = rep.get("actual_status")
        return st is not None and (st == 0 or st >= 400)
    return False


def _rmtree(path) -> None:
    shutil.rmtree(path, ignore_errors=True)

# Run statuses.
RUN_PENDING, RUN_RUNNING, RUN_PAUSED = "PENDING", "RUNNING", "PAUSED"
RUN_COMPLETED, RUN_CANCELLED, RUN_KILLED, RUN_FAILED = "COMPLETED", "CANCELLED", "KILLED", "FAILED"

# Prospect statuses.
P_PENDING, P_DONE, P_MANUAL, P_FAILED, P_SKIPPED = (
    "PENDING", "DONE", "MANUAL_ACTION_REQUIRED", "FAILED", "SKIPPED",
)
# A target this run left blocked, which a later operator-driven manual check carried to a result.
# The result lives in that attempt's own run, so this status is deliberately NOT `DONE`: this run
# still holds no findings for the target and must not pretend otherwise. It exists so the target
# stops asking for help it has already received.
P_RESOLVED = "RESOLVED_BY_MANUAL_CHECK"

# Safe operator next-step per fail-closed reason (persisted; never invented in the UI).
_MANUAL_RECOMMENDED_ACTION = {
    "captcha_detected": "Scout never solves CAPTCHAs. Solve it yourself in a browser, then rescan "
                        "this target.",
    "access_prohibited": "The site blocked automated access. Confirm you are authorized, open it in "
                         "your browser, then rescan this target.",
}

# Visual evidence budget: the landing frame plus at most two more MEANINGFUL pages the coverage pass
# actually visited. It is a ceiling, never a quota — a site with one meaningful page yields one frame,
# and a page the planner judged a structural near-duplicate has its frame discarded rather than
# padding the count.
_MAX_EVIDENCE_SHOTS = 3

# Path words that name what a page IS, so a client sees "pricing" rather than "screenshot-02".
_PAGE_ROLES = (
    ("pricing", ("pricing", "prices", "price", "cennik", "cenník", "tarif", "plans", "plany")),
    ("booking-flow", ("book", "booking", "reserve", "rezerv", "appointment", "objednat", "termin")),
    ("signup", ("signup", "sign-up", "register", "registracia", "trial", "join")),
    ("contact", ("contact", "kontakt", "contacts")),
    ("features", ("features", "product", "produkt", "funkcie", "solutions")),
    ("faq", ("faq", "help", "support", "pomoc")),
    ("about", ("about", "o-nas", "company")),
)


def _page_role(url: str, taken: Optional[set] = None) -> str:
    """Name a captured page by what it is. Falls back to its first path segment, then to "page"."""
    segments = [s for s in urlsplit(url).path.split("/") if s]
    haystack = " ".join(segments).lower()
    role = ""
    for name, hints in _PAGE_ROLES:
        if any(hint in haystack for hint in hints):
            role = name
            break
    if not role:
        first = segments[0] if segments else ""
        cleaned = "".join(ch if ch.isalnum() or ch == "-" else "-" for ch in first.lower()).strip("-")
        role = cleaned[:24] or "page"
    if taken is None:
        return role
    unique, suffix = role, 2
    while unique in taken:
        unique, suffix = f"{role}-{suffix}", suffix + 1
    taken.add(unique)
    return unique


_FLOW_HINTS = ("book", "buy", "cart", "checkout", "signup", "sign-up", "subscribe",
               "contact", "start", "appointment", "reserve", "order", "quote", "demo")

# Paths that plainly ARE the page a company puts its public address on. Matched on the final path
# segment only, so /contact and /en/kontakt qualify while /contact-center-software (a product page)
# does not — a substring match here would spend the page budget on marketing pages.
_CONTACT_TEXT_LIMIT = 40_000     # bounded: enough for a contact page, never a whole site's prose
_CONTACT_PATH_NAMES = frozenset({
    "contact", "contacts", "contact-us", "contactus", "kontakt", "contacto", "contatti",
    "support", "help", "impressum", "about", "about-us", "team",
})


def _contact_first(links: List[str], host: Optional[str]) -> List[str]:
    """Same links, same count — but offer the contact page before the twenty-fifth feature page.

    The live plausible.io run walked its full twelve-page budget and never reached /contact, which
    was the twenty-sixth link on the landing page. Finding a public address is one of the pipeline's
    stated outputs, so a page that plainly is the contact page is worth one of the budgeted slots.

    This is a REORDERING and nothing more: the planner's ceiling, its noise skipping and its
    stop-early rule all still apply unchanged, so no extra page is ever fetched.
    """
    same_host = [link for link in links if urlsplit(link).hostname == host]
    contact = [link for link in same_host if ScoutEngine._looks_like_contact_page(link)]
    if not contact:
        return links
    rest = [link for link in links if link not in set(contact)]
    return contact + rest


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _prospect_id(index: int, url: str) -> str:
    host = urlsplit(url).hostname or "site"
    slug = "".join(c if c.isalnum() else "-" for c in host)[:24].strip("-") or "site"
    return f"{index:02d}-{slug}"


class ScoutEngine:
    def __init__(
        self,
        config: ScoutRunConfig,
        store: RunStore,
        control: Optional[RunControl] = None,
        clock: Callable[[], str] = _now,
        backend=None,
        progress: Optional[Callable[[Dict], None]] = None,
    ) -> None:
        self.config = config
        self.store = store
        self.control = control or RunControl()
        self.clock = clock
        self.backend = backend or make_backend(config.browser_mode, policy=config.url_policy())
        self.sanitizer = Sanitizer()
        self.verifier = IndependentVerifier(self.sanitizer)
        self.progress = progress
        self._evidence = EvidenceSettings(video_mode=getattr(config, "video_mode", "manual"))
        self._videos_recorded = 0        # bounded per-run counter (max_videos_per_campaign)

    # ------------------------------------------------------------------
    def run(self) -> Dict:
        cfg = self.config
        self._guard_run_preconditions()
        self.store.write_config(cfg.to_dict())
        state = self._load_or_init_state()
        state["status"] = RUN_RUNNING
        state["updated_at"] = self.clock()
        self.store.save_state(state)

        eligible, rejected = dedupe_eligible(cfg.seeds, policy=cfg.url_policy())
        for r in rejected:
            self._event("seed_rejected", url=r.raw, reason=r.reason)
        eligible = eligible[: cfg.max_sites]

        prospects = state.setdefault("prospects", {})
        for idx, elig in enumerate(eligible, start=1):
            pid = _prospect_id(idx, elig.normalized)
            prospects.setdefault(
                pid, {"url": self.sanitizer.safe_url(elig.normalized), "status": P_PENDING})

        for idx, elig in enumerate(eligible, start=1):
            pid = _prospect_id(idx, elig.normalized)
            self.control.wait_while_paused()
            if self.control.should_stop():
                break
            # A Dashboard bulk "Skip queued" request is persisted separately from state.json so it
            # cannot race with the engine's own state writes.  It is checked immediately before a
            # new target starts; the currently-running page is never interrupted mid-operation.
            try:
                operator_actions = self.store.load_artifact("operator_actions.json") or {}
            except StoreError:
                operator_actions = {}
            if pid in set(operator_actions.get("skip_prospects") or []):
                prospects[pid]["status"] = P_SKIPPED
                prospects[pid]["reason"] = "skipped_by_operator"
                self.store.save_state(state)
                self._event("prospect_skipped_by_operator", prospect=pid)
                continue
            if cfg.resume and prospects[pid].get("status") == P_DONE:
                self._event("prospect_skipped_done", prospect=pid)
                continue
            # Record that this target has STARTED, and persist it before any work begins. Until this
            # existed the run could not distinguish "queued" from "being analyzed right now": both
            # read PENDING on disk, because the compact state was only written after the target
            # finished. That made the operator surfaces claim a target the browser was already
            # loading would "not start", and let a skip request be accepted for it even though the
            # skip check above has by then already been passed and cannot interrupt it.
            prospects[pid]["started_at"] = self.clock()
            self.store.save_state(state)
            try:
                self._process_prospect(pid, elig.normalized, prospects)
            except Exception as exc:  # a single prospect failure must not sink the run
                prospects[pid]["status"] = P_FAILED
                prospects[pid]["error"] = f"{type(exc).__name__}: {str(exc)[:160]}"
                self._event("prospect_failed", prospect=pid, error=prospects[pid]["error"])
            state["updated_at"] = self.clock()
            self.store.save_state(state)
            if self.progress:
                self.progress({"event": "prospect_progress", "prospect": pid,
                               "status": prospects[pid]["status"]})

        state["status"] = self._final_status(prospects)
        state["finished_at"] = self.clock()
        self.store.save_state(state)
        self._event("run_finished", status=state["status"])
        return state

    # ------------------------------------------------------------------
    def _process_prospect(self, pid: str, url: str, prospects: Dict) -> None:
        cfg = self.config
        self._event("prospect_started", prospect=pid, url=self.sanitizer.safe_url(url))
        # Deep capture: point the browser backend at THIS prospect's dir so the landing and
        # verification screenshots land under the run, servable via /scout/artifact. Static
        # backend has no screenshot_dir attribute, so this is a no-op for it.
        if hasattr(self.backend, "screenshot_dir"):
            try:
                self.backend.screenshot_dir = str(self.store.prospect_dir(pid))
                if hasattr(self.backend, "screenshot_filename"):
                    self.backend.screenshot_filename = "landing.png"
            except Exception:
                pass
        obs: Optional[PageObservation] = None
        obs2: Optional[PageObservation] = None
        try:
            # The recording-capable observe is INSIDE the guarded block: if it creates _vidtmp and
            # then raises (e.g. a browser launch/context failure), the finally still cleans it up.
            deep_qa = cfg.browser_mode == "playwright"   # real axe + perf on BOTH passes (two-pass verify)
            # The first-pass observe is a page LOAD — never recorded as reproduction. A true
            # reproduction video is captured later, in the SAME context that performs the interaction.
            obs = self.backend.observe(url, cfg.request_timeout_s, cfg.max_response_bytes,
                                       record_video=False, deep_qa=deep_qa)
            self.store.save_prospect_artifact(
                pid, "observation.json", self.sanitizer.sanitize_observation(obs))
            # Probe/flow observations are supporting checks, not evidence frames. Disable screenshots
            # until the independent verification pass so they cannot overwrite the landing frame.
            if hasattr(self.backend, "screenshot_dir"):
                self.backend.screenshot_dir = None

            # CAPTCHA / access prohibition -> manual action, no interaction, continue others.
            if obs.captcha_marker or obs.access_blocked_marker:
                reason = "captcha_detected" if obs.captcha_marker else "access_prohibited"
                record = self._manual_action_record(reason, obs)
                record["final_url"] = self.sanitizer.safe_url(record.get("final_url", ""))
                self.store.save_prospect_artifact(pid, "manual_action.json", record)
                prospects[pid].update({"status": P_MANUAL, "reason": reason,
                                       "stage": record["stage"], "analysis_complete": False})
                self._event("manual_action_required", prospect=pid, reason=reason)
                return

            if not obs.ok and not obs.forms and not obs.headings:
                prospects[pid].update({"status": P_FAILED,
                                       "reason": obs.fetch_error or f"status {obs.status}"})
                self._event("prospect_unreachable", prospect=pid, reason=prospects[pid]["reason"])
                return

            planner = make_planner(cfg.coverage, cfg.max_pages_per_site)
            planner.seed(obs)                     # the landing page is page #1 (always meaningful)
            # Visual evidence of the pages we actually walked, not the landing page twice. The list
            # holds only the EXTRA frames here; the landing frame is prepended below, so the budget
            # arithmetic and the page-NN numbering stay in one place.
            extra_shots: List[Dict[str, str]] = []
            landing_shot = self._landing_frame(pid, obs, url)
            # Seed the digest set with the landing frame so a nav link back to the page we have
            # already photographed cannot contribute a second copy of the same picture.
            seen_digests = {landing_shot["sha256"]} if landing_shot.get("sha256") else set()
            walked_contacts: List[Dict[str, str]] = []
            if "links" in cfg.check_families:
                link_status = self._probe_links(
                    obs, planner, shot_dir=str(self.store.prospect_dir(pid)), shots=extra_shots,
                    seen_digests=seen_digests, contacts=walked_contacts)
            else:
                link_status = {}
                planner.stop("links_check_disabled")
            if walked_contacts:
                self.store.save_prospect_artifact(pid, "contacts.json", {
                    "schema": "scout-contacts/v1",
                    "public": walked_contacts,
                })
            shots = ([landing_shot] if landing_shot else []) + extra_shots
            if shots:
                self.store.save_prospect_artifact(pid, "screenshots.json", {
                    "schema": "scout-screenshots/v1",
                    "captured": len(shots),
                    "max_frames": _MAX_EVIDENCE_SHOTS,
                    "frames": [{**s, "url": self.sanitizer.safe_url(s["url"])} for s in shots],
                })
            flow_result = self._explore_flow(obs) if "business_flow" in cfg.check_families else None
            ctx = CheckContext(run_id=self.store.root.name, prospect_ref=pid,
                               backend=obs.backend, link_status=link_status, flow_result=flow_result,
                               max_response_bytes=cfg.max_response_bytes)

            first_pass = run_checks(obs, ctx, cfg.check_families)

            # Independent second pass: a fresh observation + re-run of the same checks.
            self.control.wait_while_paused()
            if self.control.should_stop():
                return
            if hasattr(self.backend, "screenshot_dir"):
                self.backend.screenshot_dir = str(self.store.prospect_dir(pid))
                if hasattr(self.backend, "screenshot_filename"):
                    self.backend.screenshot_filename = "verification.png"
            obs2 = self.backend.observe(url, cfg.request_timeout_s, cfg.max_response_bytes,
                                        deep_qa=deep_qa)
            if hasattr(self.backend, "screenshot_dir"):
                self.backend.screenshot_dir = None
            link_status2 = self._probe_links(obs2) if "links" in cfg.check_families else {}
            flow2 = self._explore_flow(obs2) if "business_flow" in cfg.check_families else None
            ctx2 = CheckContext(run_id=self.store.root.name, prospect_ref=pid, backend=obs2.backend,
                                link_status=link_status2, flow_result=flow2,
                                max_response_bytes=cfg.max_response_bytes)
            second_sigs = {f.signature for f in run_checks(obs2, ctx2, cfg.check_families)}

            evidence = self.sanitizer.build_evidence(obs)
            evidence_ref = self.store.save_prospect_artifact(pid, "evidence.json", evidence)

            verified, rejected = self.verifier.verify(first_pass, second_sigs,
                                                      evidence_ref=evidence_ref)
            self.store.save_prospect_artifact(
                pid, "findings.json",
                {"verified": [f.to_dict() for f in verified],
                 "rejected": [f.to_dict() for f in rejected]},
            )
            scorecard = build_scorecard(pid, verified)
            self.store.save_prospect_artifact(pid, "scorecard.json", scorecard.to_dict())
            # Technical confidence is the scorecard dimension that measures how strongly the finding
            # is evidenced, which is exactly what the video policy's quality floor is asking about.
            qa_score = next((int(d.value) for d in scorecard.dimensions
                             if d.name == "technical_confidence"), 100)
            video_ref = self._reproduce_prospect_findings(pid, url, verified, flow_result, qa_score)

            coverage_record = dict(planner.summary())
            coverage_record.update(self._flow_coverage(flow_result, "business_flow" in cfg.check_families))
            self.store.save_prospect_artifact(pid, "coverage.json", coverage_record)

            defects = [f for f in verified if f.severity != "info"]
            prospects[pid].update({
                "status": P_DONE, "priority": scorecard.priority,
                "verified_findings": len(verified), "verified_defects": len(defects),
                "rejected_findings": len(rejected), "evidence_ref": evidence_ref,
                "video_ref": video_ref,
                "coverage": coverage_record["coverage"],
                "meaningful_pages_tested": coverage_record["meaningful_pages_tested"],
                "page_stop_reason": coverage_record["page_stop_reason"],
            })
            self._event("prospect_done", prospect=pid, verified=len(verified),
                        defects=len(defects), rejected=len(rejected), priority=scorecard.priority)
        finally:
            # Guarantee no temp recording is ever left behind — on an early manual/unreachable/stop
            # return, an exception, or normal completion (a kept clip was already moved out of _vidtmp).
            _rmtree(Path(self.store.prospect_dir(pid)) / "_vidtmp")
            _rmtree(Path(self.store.prospect_dir(pid)) / "_reprotmp")
            # Manual/unreachable paths still get an honest one-pass trace; completed paths get both.
            try:
                if obs is not None:
                    self._save_browser_trace(pid, obs, obs2)
                self._write_evidence_manifest(pid)
            except Exception:  # evidence finalization must never mask the prospect's real outcome
                # Keep the failure visible to the operator without persisting exception text, which
                # may contain a target URL, local path, or other unredacted diagnostic detail.
                try:
                    self._event("evidence_finalization_failed", prospect=pid)
                except Exception:
                    pass  # a broken event sink still must not replace the prospect's real outcome

    def _save_browser_trace(self, pid: str, first: PageObservation,
                            second: Optional[PageObservation]) -> str:
        """Write a bounded, redacted browser timeline (never raw DOM/body/cookies/full HAR)."""
        passes = []
        for name, observation in (("landing", first), ("verification", second)):
            if observation is None:
                continue
            safe = self.sanitizer.sanitize_observation(observation)
            passes.append({
                "pass": name,
                "url": safe.get("url", ""),
                "final_url": safe.get("final_url", ""),
                "status": safe.get("status", 0),
                "ok": safe.get("ok", False),
                "screenshot_ref": safe.get("screenshot_ref", ""),
                "timing_ms": safe.get("timing_ms", {}),
                "console_errors": safe.get("console_errors", []),
                "failed_resources": safe.get("failed_resources", []),
                "blocked_requests": safe.get("blocked_requests", []),
            })
        return self.store.save_prospect_artifact(pid, "browser_trace.json", {
            "schema_version": 1,
            "backend": first.backend,
            "redaction_applied": True,
            "raw_dom_stored": False,
            "raw_headers_stored": False,
            "capture_policy": {
                "screenshots": "landing_and_independent_verification",
                "video": self._evidence.video_mode,
                "video_requires_sequential_reproduction": True,
            },
            "passes": passes,
        })

    def _write_evidence_manifest(self, pid: str) -> str:
        """Inventory durable evidence after temp cleanup, with confined refs and integrity hashes."""
        pdir = Path(self.store.prospect_dir(pid))
        entries = []
        allowed_suffixes = {".json", ".png", ".webm"}
        paths = sorted(pdir.iterdir()) if pdir.exists() else []
        for path in paths:
            if (not path.is_file() or path.name == "evidence_manifest.json"
                    or path.suffix.lower() not in allowed_suffixes):
                continue
            digest = hashlib.sha256()
            with path.open("rb") as fh:
                for chunk in iter(lambda: fh.read(64 * 1024), b""):
                    digest.update(chunk)
            entries.append({
                "ref": path.name,
                "kind": {
                    ".json": "structured",
                    ".png": "screenshot",
                    ".webm": "reproduction_video",
                }[path.suffix.lower()],
                "bytes": path.stat().st_size,
                "sha256": digest.hexdigest(),
            })
        return self.store.save_prospect_artifact(pid, "evidence_manifest.json", {
            "schema_version": 1,
            "redaction_applied_to_structured_evidence": True,
            "temporary_recordings_present": any(
                (pdir / name).exists() for name in ("_vidtmp", "_reprotmp")),
            "video_policy": self._evidence.video_mode,
            "entries": entries,
        })

    def _reproduce_prospect_findings(self, pid: str, start_url: str,
                                     verified: List[ScoutFinding], flow_result,
                                     qa_score: int = 100) -> str:
        """Capture a TRUE reproduction video — in the SAME bounded browser context that performs the
        exact safe steps producing a verified INTERACTION finding — and bind the reproduction evidence.
        A page-load-only clip is NEVER kept. If the finding cannot be genuinely replayed (or the backend
        has no browser / video is off / the cap is reached), keep no video and record the honest
        reproduction status. Returns the kept servable path "reproduction.webm" or "".
        """
        pdir = Path(self.store.prospect_dir(pid))
        kept = ""
        try:
            picked = self._pick_reproducible(verified, flow_result)
            if picked is None:
                return ""
            finding, action_url = picked
            if (self._evidence.video_mode != VIDEO_QUALIFIED_AUTO
                    or self._videos_recorded >= self._evidence.max_videos_per_campaign
                    or not hasattr(self.backend, "reproduce_interaction")):
                return ""                          # opt-out / cap reached / no browser: no video
            rep = self.backend.reproduce_interaction(start_url, action_url, str(pdir))
            reproduced = _finding_reproduced(finding, rep)
            # The keep/discard decision belongs to the evidence policy, not to this method. It
            # already encodes every rule that matters -- severity floor, confidence floor, genuinely
            # reproduced, an interaction a still frame cannot show, a safe deterministic path, and
            # the per-campaign cap -- and it returns the REASON, which is what makes an absent video
            # explainable instead of merely absent.
            allowed, decision = video_qualified(
                self._evidence,
                severity=finding.severity,
                qa_score=qa_score,
                reproduced=reproduced,
                visual_or_interaction=True,      # only interaction findings are picked at all
                screenshots_sufficient=False,    # a still cannot show that an action leads nowhere
                safe_deterministic_path=bool(rep.get("precondition_ok") and rep.get("cleanup_ok")),
                videos_recorded=self._videos_recorded,
            )
            record = {
                "finding_id": finding.finding_id, "signature": finding.signature,
                "start_url": self.sanitizer.safe_url(start_url),
                "action_url": self.sanitizer.safe_url(action_url),
                "action_log": [
                    self.sanitizer.redact(str(v)) for v in rep.get("action_log", [])[:20]
                ],
                "precondition_ok": bool(rep.get("precondition_ok")),
                "final_url": self.sanitizer.safe_url(rep.get("final_url", "")),
                "actual_status": rep.get("actual_status"), "expected": finding.expected,
                "actual": finding.actual, "cleanup_ok": bool(rep.get("cleanup_ok")),
                "reproduced": reproduced,
                "reproduction_status": "reproduced" if reproduced else "not_reproduced",
                "video_decision": decision,
                "video_ref": "",
            }
            clip = pdir / str(rep.get("video_ref") or "_nope_")
            # Keep the video ONLY when the policy allowed it for THIS finding.
            if allowed and rep.get("video_ref") and clip.exists():
                clip.replace(pdir / "reproduction.webm")
                record["video_ref"] = "reproduction.webm"
                self._videos_recorded += 1
                kept = "reproduction.webm"
            self.store.save_prospect_artifact(pid, "reproduction.json", record)
        except Exception:  # noqa: BLE001 - reproduction must never crash a completed prospect
            pass
        finally:
            _rmtree(pdir / "_reprotmp")            # temp reproduction recording dir
            _rmtree(pdir / "_vidtmp")              # never keep a page-load clip
        return kept

    def _pick_reproducible(self, verified: List[ScoutFinding], flow_result):
        """The best qualifying INTERACTION finding that has a genuinely replayable safe action, plus
        that action URL, or None.

        A finding belongs here only when the proof is an ACTION rather than a page: no still frame
        can show that a control leads nowhere. Everything else Scout confirms today -- accessibility,
        structure, metadata, console, performance -- is fully evidenced by the page capture and the
        structured records, and replaying it would produce a clip of a page that merely loads.

        The set is deliberately small because the flow explorer follows exactly ONE public step, so
        a broken primary entry is the only interaction defect the engine can currently confirm.
        Widening it is a one-line change once multi-step flows land; inventing entries for defects
        the engine cannot produce would be fiction.
        """
        min_sev = _SEV_ORDER.get(self._evidence.min_video_severity, 2)
        entry = (flow_result or {}).get("entry_url", "") if isinstance(flow_result, dict) else ""
        action_for = {"flow_entry_broken": entry}
        for f in verified:
            if f.severity == "info" or _SEV_ORDER.get(f.severity, 0) < min_sev:
                continue
            action_url = action_for.get(f.signature, "")
            if action_url:
                return f, action_url
        return None

    # ------------------------------------------------------------------
    def _landing_frame(self, pid: str, obs: PageObservation, url: str) -> Dict[str, str]:
        """The landing capture as an evidence frame, digest included, or {} when none was taken."""
        if not obs.screenshot_ref:
            return {}
        path = self.store.prospect_dir(pid) / obs.screenshot_ref
        try:
            digest = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else ""
        except OSError:
            digest = ""
        return {"file": obs.screenshot_ref, "url": obs.final_url or url, "role": "landing",
                "sha256": digest}

    @staticmethod
    def _keep_or_drop_frame(shot_dir: str, frame: str, url: str, probe: PageObservation,
                            verdict: str, shots: List[Dict[str, str]],
                            seen_digests: set) -> None:
        """Keep a captured frame only if the page it shows earned its place in the evidence.

        Three ways a frame fails to earn it: the page did not load, the planner judged it a
        structural near-duplicate, or -- the one a live easybooking.sk run exposed -- the capture is
        byte-identical to a frame we already hold, because a nav link led straight back to the page
        we had already photographed. All three produce another file and no further fact, so the file
        is deleted here rather than being counted downstream. Recording the digest is what makes the
        screenshot record honest at the source instead of relying on the export to hide the repeat.
        """
        path = Path(shot_dir) / frame
        usable = verdict == "meaningful" and probe.ok and not probe.fetch_error
        digest = ""
        if usable and path.is_file() and path.stat().st_size:
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if not digest or digest in seen_digests:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
            return
        seen_digests.add(digest)
        shots.append({"file": frame, "url": probe.final_url or url, "sha256": digest,
                      "role": _page_role(probe.final_url or url,
                                         {s["role"] for s in shots} | {"landing"})})

    def _probe_links(self, obs: PageObservation, planner=None, *, shot_dir: Optional[str] = None,
                     shots: Optional[List[Dict[str, str]]] = None,
                     seen_digests: Optional[set] = None,
                     contacts: Optional[List[Dict[str, str]]] = None) -> Dict[str, int]:
        """Fetch a bounded set of same-host links once (read-only) and record status.

        When a ``CoveragePlanner`` is supplied (the first, measured pass) it governs the crawl: it
        skips obvious noise before fetch, suppresses structural near-duplicates, and stops early when
        no new meaningful coverage appears. With no planner (a verification re-probe) the legacy raw
        ``max_pages_per_site`` cap applies, so that path is behaviourally unchanged."""
        cfg = self.config
        host = urlsplit(obs.final_url or obs.url).hostname
        seen: Dict[str, int] = {}
        count = 0
        exhausted = True
        for link in _contact_first(obs.links, host) if contacts is not None else obs.links:
            if urlsplit(link).hostname != host:
                continue
            if link in seen:
                continue
            if self.control.should_stop():
                if planner is not None:
                    planner.stop("stopped_by_control")
                exhausted = False
                break
            if planner is not None:
                if planner.should_stop():
                    exhausted = False
                    break
                if planner.pre_fetch_skip(link):
                    continue                       # obvious noise: not fetched, not counted
            elif count >= cfg.max_pages_per_site:
                exhausted = False
                break
            # Capture a frame for this page only on the measured pass, only while the evidence budget
            # has room, and only into its OWN file — the landing frame is never overwritten. The
            # verification re-probe (planner is None) still captures nothing.
            frame = ""
            wants_frame = (planner is not None and shot_dir and shots is not None
                           and len(shots) < _MAX_EVIDENCE_SHOTS - 1
                           and hasattr(self.backend, "screenshot_dir"))
            if wants_frame:
                frame = f"page-{len(shots) + 2:02d}.png"
                self.backend.screenshot_dir = shot_dir
                if hasattr(self.backend, "screenshot_filename"):
                    self.backend.screenshot_filename = frame
            probe = self.backend.observe(link, cfg.request_timeout_s, min(cfg.max_response_bytes, 200_000))
            if wants_frame:
                self.backend.screenshot_dir = None
            seen[link] = probe.status if not probe.fetch_error else 0
            count += 1
            # A page we actually opened may carry the company's public address — a contact page
            # usually does. Reading only the landing observation threw that away and reported
            # "Email not found" for a site whose mailbox Scout had just walked past.
            if contacts is not None and not probe.fetch_error:
                self._collect_contacts(probe, contacts)
            if planner is not None:
                verdict = planner.record(link, probe)
                if frame:
                    self._keep_or_drop_frame(shot_dir, frame, link, probe, verdict, shots,
                                             seen_digests if seen_digests is not None else set())
        if planner is not None:
            planner.should_stop()                  # capture a ceiling/no-coverage stop from the last page
            if exhausted:
                planner.finalize_links_exhausted()
        return seen

    @staticmethod
    def _looks_like_contact_page(url: str) -> bool:
        path = (urlsplit(url).path or "/").lower().rstrip("/")
        tail = path.rsplit("/", 1)[-1]
        return tail in _CONTACT_PATH_NAMES or path.endswith(tuple(
            "/" + name for name in _CONTACT_PATH_NAMES))

    def _collect_contacts(self, probe: PageObservation, into: List[Dict[str, str]]) -> None:
        """Record public addresses from one walked page, bound to the page they were found on.

        Same rules as everywhere else: only genuinely public addresses, only same-company ones (a
        walked page may link to a third party, and their mailbox is not this target's contact), and
        every address keeps the exact URL it came from so provenance survives to the operator.
        """
        from core.scout.discovery.domain_intel import canonical_domain
        from core.scout.outreach.qa_draft import extract_public_contact_records

        page_url = probe.final_url or probe.url
        domain = canonical_domain(page_url)
        # Visible text is read ONLY on a page that plainly is the contact page. A feature page's
        # prose is not a contact source — it quotes customers, shows example addresses and embeds
        # support snippets, and scanning it would invent contacts out of marketing copy.
        text = (probe.text_sample or "")[:_CONTACT_TEXT_LIMIT] if self._looks_like_contact_page(
            page_url) else ""
        for record in extract_public_contact_records(
                {"links": list(probe.links or []), "title": probe.title or "",
                 "meta_description": probe.meta_description or "",
                 "headings": list(probe.headings or []),
                 "text": text,
                 "final_url": page_url, "url": probe.url},
                domain=domain):
            email = str(record.get("email") or "").strip().lower()
            if not email or any(existing["email"] == email for existing in into):
                continue
            # Same company only, and strictly. extract_public_emails prefers same-domain addresses
            # but falls back to returning everything when none exist — reasonable for a landing
            # page an operator is reading, wrong here: a walked page can link a partner, an agency
            # or a support vendor, and mailing them would be contacting the wrong company entirely.
            host = email.rsplit("@", 1)[-1]
            if domain and host != domain and not host.endswith("." + domain):
                continue
            into.append({"email": email, "source": str(record.get("source") or ""),
                         "source_url": self.sanitizer.safe_url(
                             str(record.get("source_url") or page_url)),
                         "public": True})

    def _explore_flow(self, obs: PageObservation) -> Optional[Dict]:
        """Follow one primary public flow link a single step and STOP before any side effect."""
        host = urlsplit(obs.final_url or obs.url).hostname
        entry = None
        for link in obs.links:
            if urlsplit(link).hostname != host:
                continue
            if any(h in link.lower() for h in _FLOW_HINTS):
                entry = link
                break
        if not entry:
            return None
        nxt = self.backend.observe(entry, self.config.request_timeout_s, self.config.max_response_bytes)
        if not nxt.ok:
            return {"entry_url": entry, "entry_broken": True, "steps": 1,
                    "stopped_before_side_effect": True}
        return {"entry_url": entry, "entry_broken": False, "steps": 1,
                "reached_form": bool(nxt.forms), "stopped_before_side_effect": True}

    @staticmethod
    def _manual_action_record(reason: str, obs: PageObservation) -> Dict[str, Any]:
        """Canonical, persisted MANUAL_ACTION_REQUIRED contract (rendered as-is by the operator UI —
        never guessed there). We fail closed right after the landing observation and before any
        interaction, so the stage/boundary are known; whether a browser started and whether the
        landing loaded are read from the actual observation, not assumed."""
        return {
            "reason": reason,
            "stage": "post_landing_precheck",
            "stop_boundary": "stopped_before_interaction",
            "chromium_started": (obs.backend == "playwright"),
            "landing_loaded": bool(obs.ok),
            "landing_status": obs.status,
            "final_url": obs.final_url or obs.url,
            "screenshot_ref": obs.screenshot_ref or "",
            "analysis_complete": False,
            # How sure the detector is, and of what. "confirmed" earns a categorical sentence in the
            # operator UI; "suspected" is a fail-closed guess and must be worded as one. The signal
            # is the actual evidence, so the operator can judge it instead of trusting the label.
            "challenge_confidence": obs.challenge_confidence or "confirmed",
            "challenge_signal": obs.challenge_signal,
            "recommended_action": _MANUAL_RECOMMENDED_ACTION.get(
                reason, "Review this target yourself in a browser, then rescan it."),
        }

    @staticmethod
    def _flow_coverage(flow_result, flow_enabled: bool) -> Dict[str, Any]:
        """Honest flow-coverage metadata. The engine follows ONE bounded flow step today, so we report
        exactly that (flow_steps_supported == 1) and never advertise a multi-step ceiling. The stop
        reason distinguishes a disabled flow check from a genuine 'looked, found no entry' — reporting
        'no_flow_entry_detected' when the check never ran would be a false claim of having looked."""
        fr = flow_result if isinstance(flow_result, dict) else None
        detected = 1 if (fr and fr.get("entry_url")) else 0
        if not flow_enabled:
            stop_reason = "flow_check_disabled"
        elif detected:
            stop_reason = "single_step_supported"
        else:
            stop_reason = "no_flow_entry_detected"
        return {
            "flows_detected": detected,
            "flow_entries_checked": detected,          # the single detected entry, observed once
            "flow_steps_supported": 1,                 # engine supports one bounded read-only step
            "flow_steps_used": int(fr.get("steps", 0)) if fr else 0,
            "flow_stop_reason": stop_reason,
        }

    # ------------------------------------------------------------------
    def _guard_run_preconditions(self) -> None:
        """Fail closed on run-id reuse and resume/config mismatch (no stale-artifact mixing).

        - A fresh run must never silently reuse an existing run directory.
        - Resume requires that run to already exist AND its immutable config to match, so a
          changed campaign/seeds/budget cannot resume (and pollute) a different run.
        """
        from core.scout.config import ScoutRunConfig
        cfg = self.config
        if cfg.resume:
            if not self.store.exists():
                raise StoreError(
                    f"resume requested but no existing run found for run_id "
                    f"{self.store.root.name!r}")
            try:
                prior = ScoutRunConfig.from_dict(self.store.load_config())
            except StoreError:
                raise
            except Exception as exc:  # a corrupt/incompatible prior config fails closed
                raise StoreError(f"cannot resume: prior config is unreadable ({exc})") from exc
            if prior.material_signature() != cfg.material_signature():
                raise StoreError(
                    "cannot resume: the run configuration (campaign/seeds/budgets) differs "
                    "from the original run; start a fresh run instead")
        elif self.store.exists():
            raise StoreError(
                f"run_id {self.store.root.name!r} already exists; refusing to overwrite it. "
                "Use --resume to continue it, or choose a new run id")

    def _load_or_init_state(self) -> Dict:
        if self.config.resume and self.store.exists():
            state = self.store.load_state()
            self._event("run_resumed", run_id=self.store.root.name)
            return state
        state = {
            "run_id": self.store.root.name, "status": RUN_PENDING,
            "started_at": self.clock(), "updated_at": self.clock(),
            "config": self.config.to_dict(), "prospects": {},
        }
        self.store.save_state(state)
        self._event("run_started", run_id=self.store.root.name)
        return state

    def _final_status(self, prospects: Dict) -> str:
        if self.control.is_killed:
            return RUN_KILLED
        if self.control.is_cancelled:
            return RUN_CANCELLED
        return RUN_COMPLETED

    def _event(self, kind: str, **fields) -> None:
        event = {"at": self.clock(), "event": kind, **fields}
        self.store.append_event(event)
        if self.progress:
            self.progress(event)


def verified_findings_for_run(store: RunStore, prospect_ids: List[str]) -> List[ScoutFinding]:
    out: List[ScoutFinding] = []
    for pid in prospect_ids:
        data = store.load_prospect_artifact(pid, "findings.json")
        if not data:
            continue
        for fd in data.get("verified", []):
            f = ScoutFinding.from_dict(fd)
            # Rehydrate the persisted verified/sanitized state for reporting (trusted store).
            f.verification_state = fd.get("verification_state", f.verification_state)
            f.sanitized = fd.get("sanitized", f.sanitized)
            out.append(f)
    return out

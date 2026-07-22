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

import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import urlsplit

from core.scout.backends import PageObservation, make_backend
from core.scout.checks import CheckContext, run_checks
from core.scout.config import ScoutRunConfig
from core.scout.control import RunControl
from core.scout.evidence_policy import EvidenceSettings, VIDEO_QUALIFIED_AUTO, video_qualified
from core.scout.findings import ScoutFinding
from core.scout.sanitize import Sanitizer
from core.scout.scoring import build_scorecard
from core.scout.store import RunStore, StoreError
from core.scout.url_safety import dedupe_eligible
from core.scout.verification import IndependentVerifier

# Verified-defect categories where motion/behaviour matters and a static screenshot is insufficient —
# the only cases a reproduction video is worth keeping.
_INTERACTION_CATEGORIES = frozenset({"business_flow", "functional"})
_SEV_ORDER = {"info": 0, "low": 1, "medium": 2, "high": 3}


def _audit_opportunity(scorecard) -> int:
    for d in getattr(scorecard, "dimensions", []):
        if getattr(d, "name", "") == "audit_opportunity":
            return int(getattr(d, "value", 0) or 0)
    return 0


def _rmtree(path) -> None:
    shutil.rmtree(path, ignore_errors=True)

# Run statuses.
RUN_PENDING, RUN_RUNNING, RUN_PAUSED = "PENDING", "RUNNING", "PAUSED"
RUN_COMPLETED, RUN_CANCELLED, RUN_KILLED, RUN_FAILED = "COMPLETED", "CANCELLED", "KILLED", "FAILED"

# Prospect statuses.
P_PENDING, P_DONE, P_MANUAL, P_FAILED, P_SKIPPED = (
    "PENDING", "DONE", "MANUAL_ACTION_REQUIRED", "FAILED", "SKIPPED",
)

_FLOW_HINTS = ("book", "buy", "cart", "checkout", "signup", "sign-up", "subscribe",
               "contact", "start", "appointment", "reserve", "order", "quote", "demo")


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
            prospects.setdefault(pid, {"url": elig.normalized, "status": P_PENDING})

        for idx, elig in enumerate(eligible, start=1):
            pid = _prospect_id(idx, elig.normalized)
            self.control.wait_while_paused()
            if self.control.should_stop():
                break
            if cfg.resume and prospects[pid].get("status") == P_DONE:
                self._event("prospect_skipped_done", prospect=pid)
                continue
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
        self._event("prospect_started", prospect=pid, url=url)
        # Deep capture: point the browser backend at THIS prospect's dir so page.png (and any
        # future media) lands under the run, servable via /scout/artifact. Static backend has no
        # screenshot_dir attribute, so this is a no-op for it.
        if hasattr(self.backend, "screenshot_dir"):
            try:
                self.backend.screenshot_dir = str(self.store.prospect_dir(pid))
            except Exception:
                pass
        try:
            # The recording-capable observe is INSIDE the guarded block: if it creates _vidtmp and
            # then raises (e.g. a browser launch/context failure), the finally still cleans it up.
            deep_qa = cfg.browser_mode == "playwright"   # real axe + perf on BOTH passes (two-pass verify)
            obs = self.backend.observe(url, cfg.request_timeout_s, cfg.max_response_bytes,
                                       record_video=(self._evidence.video_mode == VIDEO_QUALIFIED_AUTO),
                                       deep_qa=deep_qa)
            self.store.save_prospect_artifact(pid, "observation.json", obs.to_dict())

            # CAPTCHA / access prohibition -> manual action, no interaction, continue others.
            if obs.captcha_marker or obs.access_blocked_marker:
                reason = "captcha_detected" if obs.captcha_marker else "access_prohibited"
                prospects[pid].update({"status": P_MANUAL, "reason": reason})
                self._event("manual_action_required", prospect=pid, reason=reason)
                return

            if not obs.ok and not obs.forms and not obs.headings:
                prospects[pid].update({"status": P_FAILED,
                                       "reason": obs.fetch_error or f"status {obs.status}"})
                self._event("prospect_unreachable", prospect=pid, reason=prospects[pid]["reason"])
                return

            link_status = self._probe_links(obs) if "links" in cfg.check_families else {}
            flow_result = self._explore_flow(obs) if "business_flow" in cfg.check_families else None
            ctx = CheckContext(run_id=self.store.root.name, prospect_ref=pid,
                               backend=obs.backend, link_status=link_status, flow_result=flow_result,
                               max_response_bytes=cfg.max_response_bytes)

            first_pass = run_checks(obs, ctx, cfg.check_families)

            # Independent second pass: a fresh observation + re-run of the same checks.
            self.control.wait_while_paused()
            if self.control.should_stop():
                return
            obs2 = self.backend.observe(url, cfg.request_timeout_s, cfg.max_response_bytes,
                                        deep_qa=deep_qa)
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
            video_ref = self._finalize_prospect_video(pid, obs.video_ref, verified)

            defects = [f for f in verified if f.severity != "info"]
            prospects[pid].update({
                "status": P_DONE, "priority": scorecard.priority,
                "verified_findings": len(verified), "verified_defects": len(defects),
                "rejected_findings": len(rejected), "evidence_ref": evidence_ref,
                "video_ref": video_ref,
            })
            self._event("prospect_done", prospect=pid, verified=len(verified),
                        defects=len(defects), rejected=len(rejected), priority=scorecard.priority)
        finally:
            # Guarantee no temp recording is ever left behind — on an early manual/unreachable/stop
            # return, an exception, or normal completion (a kept clip was already moved out of _vidtmp).
            _rmtree(Path(self.store.prospect_dir(pid)) / "_vidtmp")

    def _finalize_prospect_video(self, pid: str, video_ref: str,
                                 verified: List[ScoutFinding]) -> str:
        """Keep a qualified reproduction clip or delete the unqualified temp recording.

        A short video is kept ONLY for a reproduced INTERACTION defect (business_flow / functional)
        of sufficient severity and QA value; otherwise the temp recording is removed — Scout never
        keeps an unreproduced video. Two-pass verification IS the reproduction. Qualification is
        anchored strictly on the interaction defects themselves: an unrelated static defect (e.g. a
        high-severity SEO issue) must never lend its severity or QA value to a trivial interaction
        finding. Returns the kept servable path "reproduction.webm" or "".
        """
        pdir = Path(self.store.prospect_dir(pid))
        vidtmp = pdir / "_vidtmp"
        kept = ""
        try:
            if video_ref:
                interaction = [f for f in verified
                               if f.severity != "info" and f.category in _INTERACTION_CATEGORIES]
                if interaction:
                    severity = max((f.severity for f in interaction),
                                   key=lambda s: _SEV_ORDER.get(s, 0))
                    # QA value from the interaction defects ONLY (not the prospect-wide scorecard).
                    qa_score = _audit_opportunity(build_scorecard(pid, interaction))
                    allowed, _reason = video_qualified(
                        self._evidence, severity=severity, qa_score=qa_score, reproduced=True,
                        visual_or_interaction=True, screenshots_sufficient=False,
                        safe_deterministic_path=True, videos_recorded=self._videos_recorded)
                    clip = pdir / video_ref
                    if allowed and clip.exists():
                        clip.replace(pdir / "reproduction.webm")   # promote to a servable top-level file
                        self._videos_recorded += 1
                        kept = "reproduction.webm"
        finally:
            _rmtree(vidtmp)          # always clean the temp dir (an unqualified clip is never kept)
        return kept

    # ------------------------------------------------------------------
    def _probe_links(self, obs: PageObservation) -> Dict[str, int]:
        """Fetch a bounded set of same-host links once (read-only) and record status."""
        cfg = self.config
        host = urlsplit(obs.final_url or obs.url).hostname
        seen: Dict[str, int] = {}
        count = 0
        for link in obs.links:
            if count >= cfg.max_pages_per_site:
                break
            if urlsplit(link).hostname != host:
                continue
            if link in seen:
                continue
            if self.control.should_stop():
                break
            probe = self.backend.observe(link, cfg.request_timeout_s, min(cfg.max_response_bytes, 200_000))
            seen[link] = probe.status if not probe.fetch_error else 0
            count += 1
        return seen

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

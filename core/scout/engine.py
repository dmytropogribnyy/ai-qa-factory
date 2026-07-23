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
from core.scout.evidence_policy import EvidenceSettings, VIDEO_QUALIFIED_AUTO
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

# Safe operator next-step per fail-closed reason (persisted; never invented in the UI).
_MANUAL_RECOMMENDED_ACTION = {
    "captcha_detected": "Scout never solves CAPTCHAs. Solve it yourself in a browser, then rescan "
                        "this target.",
    "access_prohibited": "The site blocked automated access. Confirm you are authorized, open it in "
                         "your browser, then rescan this target.",
}

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
            prospects.setdefault(
                pid, {"url": self.sanitizer.safe_url(elig.normalized), "status": P_PENDING})

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
            if "links" in cfg.check_families:
                link_status = self._probe_links(obs, planner)
            else:
                link_status = {}
                planner.stop("links_check_disabled")
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
            video_ref = self._reproduce_prospect_findings(pid, url, verified, flow_result)

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
                pass

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
                                     verified: List[ScoutFinding], flow_result) -> str:
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
                "video_ref": "",
            }
            clip = pdir / str(rep.get("video_ref") or "_nope_")
            # Keep the video ONLY when the finding genuinely replayed AND cleanup was verified.
            if reproduced and record["cleanup_ok"] and rep.get("video_ref") and clip.exists():
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
        that action URL. Currently: a broken primary business-flow entry -> navigate to the flow entry
        (a bounded, read-only step). Returns (finding, action_url) or None."""
        min_sev = _SEV_ORDER.get(self._evidence.min_video_severity, 2)
        entry = (flow_result or {}).get("entry_url", "") if isinstance(flow_result, dict) else ""
        for f in verified:
            if f.severity == "info":
                continue
            if (f.signature == "flow_entry_broken" and entry
                    and _SEV_ORDER.get(f.severity, 0) >= min_sev):
                return f, entry
        return None

    # ------------------------------------------------------------------
    def _probe_links(self, obs: PageObservation, planner=None) -> Dict[str, int]:
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
        for link in obs.links:
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
            probe = self.backend.observe(link, cfg.request_timeout_s, min(cfg.max_response_bytes, 200_000))
            seen[link] = probe.status if not probe.fetch_error else 0
            count += 1
            if planner is not None:
                planner.record(link, probe)
        if planner is not None:
            planner.should_stop()                  # capture a ceiling/no-coverage stop from the last page
            if exhausted:
                planner.finalize_links_exhausted()
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

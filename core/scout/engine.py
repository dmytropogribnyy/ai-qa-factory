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

from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional
from urllib.parse import urlsplit

from core.scout.backends import PageObservation, make_backend
from core.scout.checks import CheckContext, run_checks
from core.scout.config import ScoutRunConfig
from core.scout.control import RunControl
from core.scout.findings import ScoutFinding
from core.scout.sanitize import Sanitizer
from core.scout.scoring import build_scorecard
from core.scout.store import RunStore
from core.scout.url_safety import dedupe_eligible
from core.scout.verification import IndependentVerifier

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

    # ------------------------------------------------------------------
    def run(self) -> Dict:
        cfg = self.config
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
        obs = self.backend.observe(url, cfg.request_timeout_s, cfg.max_response_bytes)
        self.store.save_prospect_artifact(pid, "observation.json", obs.to_dict())

        # CAPTCHA / access prohibition -> manual action, no interaction, continue others.
        if obs.captcha_marker or obs.access_blocked_marker:
            reason = "captcha_detected" if obs.captcha_marker else "access_prohibited"
            prospects[pid].update({"status": P_MANUAL, "reason": reason})
            self._event("manual_action_required", prospect=pid, reason=reason)
            return

        if not obs.ok and not obs.forms and not obs.headings:
            prospects[pid].update({"status": P_FAILED, "reason": obs.fetch_error or f"status {obs.status}"})
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
        obs2 = self.backend.observe(url, cfg.request_timeout_s, cfg.max_response_bytes)
        link_status2 = self._probe_links(obs2) if "links" in cfg.check_families else {}
        flow2 = self._explore_flow(obs2) if "business_flow" in cfg.check_families else None
        ctx2 = CheckContext(run_id=self.store.root.name, prospect_ref=pid, backend=obs2.backend,
                            link_status=link_status2, flow_result=flow2,
                            max_response_bytes=cfg.max_response_bytes)
        second_sigs = {f.signature for f in run_checks(obs2, ctx2, cfg.check_families)}

        evidence = self.sanitizer.build_evidence(obs)
        evidence_ref = self.store.save_prospect_artifact(pid, "evidence.json", evidence)

        verified, rejected = self.verifier.verify(first_pass, second_sigs, evidence_ref=evidence_ref)
        self.store.save_prospect_artifact(
            pid, "findings.json",
            {"verified": [f.to_dict() for f in verified], "rejected": [f.to_dict() for f in rejected]},
        )
        scorecard = build_scorecard(pid, verified)
        self.store.save_prospect_artifact(pid, "scorecard.json", scorecard.to_dict())

        defects = [f for f in verified if f.severity != "info"]
        prospects[pid].update({
            "status": P_DONE, "priority": scorecard.priority,
            "verified_findings": len(verified), "verified_defects": len(defects),
            "rejected_findings": len(rejected), "evidence_ref": evidence_ref,
        })
        self._event("prospect_done", prospect=pid, verified=len(verified),
                    defects=len(defects), rejected=len(rejected), priority=scorecard.priority)

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

"""Telling what was asked for apart from what actually happened.

A run reports success and an operator has to decide whether to believe it. Almost everything on the
screen at that moment is a *setting*: ``browser_mode=auto`` says a browser was permitted, not that
Chromium ever launched; ``video=true`` says a clip was allowed, not that one exists; a green
terminal line says the process exited, not that every target was analysed. Each of those has been
read as the stronger claim at least once, and each time the number that followed was wrong.

So every fact here belongs to exactly one of three layers, and they are never merged:

**Requested** — what the operator or harness asked for.
**Effective** — what the system accepted after defaults, profiles, safety policy and budgets.
**Observed** — what execution actually produced, evidenced by a receipt or a file on disk.

Reading order matters as much as the layers. Evidence is gathered bottom-up — persisted config, the
run and target stores, execution receipts, the real files and their hashes, then the derived read
model — and the UI is never a source. A validation computed from the screen it is validating agrees
with itself by construction.

An unproven fact is reported as ``UNKNOWN``, never as ``0``, ``""`` or ``Success``. ``Validated``
requires every applicable check to pass; anything else says so and says why.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PASS = "PASS"
FAIL = "FAIL"
PARTIAL = "PARTIAL"
NOT_APPLICABLE = "NOT_APPLICABLE"
UNKNOWN = "UNKNOWN"

_ORDER = (FAIL, PARTIAL, UNKNOWN, PASS, NOT_APPLICABLE)
SCHEMA = "scout-run-validation/v1"
REPORT_NAME = "run_validation.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Check:
    check_id: str
    status: str
    expected: Any = None
    observed: Any = None
    explanation: str = ""
    evidence_refs: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"check_id": self.check_id, "status": self.status, "expected": self.expected,
                "observed": self.observed, "explanation": self.explanation,
                "evidence_refs": list(self.evidence_refs)}


@dataclass
class RunValidation:
    run_id: str
    generated_at: str
    build: str = ""
    purpose: str = ""
    layers: Dict[str, Any] = field(default_factory=dict)
    checks: List[Check] = field(default_factory=list)

    @property
    def counts(self) -> Dict[str, int]:
        out = {status: 0 for status in _ORDER}
        for check in self.checks:
            out[check.status] = out.get(check.status, 0) + 1
        return out

    @property
    def validated(self) -> bool:
        """Only when every check that APPLIES passed. Partial, unknown and failed all block it."""
        return all(c.status in (PASS, NOT_APPLICABLE) for c in self.checks) and bool(self.checks)

    @property
    def status(self) -> str:
        if self.validated:
            return "VALIDATED"
        for status in (FAIL, PARTIAL, UNKNOWN):
            if any(c.status == status for c in self.checks):
                return {FAIL: "FAILED", PARTIAL: "PARTIAL", UNKNOWN: "INCOMPLETE"}[status]
        return "INCOMPLETE"

    def problems(self) -> List[Check]:
        return [c for c in self.checks if c.status in (FAIL, PARTIAL, UNKNOWN)]

    def to_dict(self) -> Dict[str, Any]:
        return {"schema": SCHEMA, "run_id": self.run_id, "generated_at": self.generated_at,
                "build": self.build, "purpose": self.purpose, "status": self.status,
                "validated": self.validated, "counts": self.counts, "layers": self.layers,
                "checks": [c.to_dict() for c in self.checks]}


class _Evidence:
    """Everything read off disk, once, bottom-up. Nothing here comes from a rendered page."""

    def __init__(self, output_dir: str, run_id: str) -> None:
        self.output_dir = output_dir
        self.run_id = run_id
        self.root = Path(output_dir) / "scout" / run_id
        self.config = self._json("config.json") or {}
        self.state = self._json("state.json") or {}
        self.events = self._events()
        self.prospects: Dict[str, Dict[str, Any]] = {
            pid: rec for pid, rec in (self.state.get("prospects") or {}).items()
            if isinstance(rec, dict)}
        # Where each target's artifacts live. A discovery campaign analyses nothing itself: it
        # promotes candidates into their own Scout runs, so validating only the campaign directory
        # finds no targets and honestly reports UNKNOWN for work that was in fact done one level
        # down. Following the promotion link is what makes the answer useful as well as honest.
        self._homes: Dict[str, Path] = {pid: self.root for pid in self.prospects}
        self.promoted: List[str] = []
        for record in self.state.get("candidates") or []:
            child = str((record or {}).get("promoted_scout_run") or "")
            if not child:
                continue
            self.promoted.append(child)
            child_root = Path(output_dir) / "scout" / child
            try:
                child_state = json.loads((child_root / "state.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for pid, rec in (child_state.get("prospects") or {}).items():
                if isinstance(rec, dict):
                    key = f"{child}/{pid}"
                    self.prospects[key] = rec
                    self._homes[key] = child_root

    @property
    def is_discovery(self) -> bool:
        """A campaign that searched for targets rather than being given them."""
        return "candidates" in self.state

    def _json(self, *parts: str) -> Optional[Dict[str, Any]]:
        try:
            return json.loads(self.root.joinpath(*parts).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _events(self) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        try:
            lines = (self.root / "events.jsonl").read_text(encoding="utf-8").splitlines()
        except OSError:
            return out
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
        return out

    def exists(self) -> bool:
        return bool(self.state) or bool(self.config)

    def artifact(self, pid: str, name: str) -> Optional[Dict[str, Any]]:
        path = self.prospect_dir(pid) / name
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def prospect_dir(self, pid: str) -> Path:
        """Resolve a target to its own run's directory — this run's, or a promoted child's."""
        home = self._homes.get(pid, self.root)
        return home / "prospects" / pid.rsplit("/", 1)[-1]

    def evidence_ref(self, pid: str, name: str) -> str:
        if "/" in pid:
            run, inner = pid.split("/", 1)
            return f"{run}/prospects/{inner}/{name}"
        return f"prospects/{pid}/{name}"


def validate_run(output_dir: str, run_id: str, *, write: bool = False,
                 read_model: Any = None) -> RunValidation:
    """Reconcile one run against its own evidence.

    ``read_model`` is the DERIVED layer (``CampaignService``) and is used only to check that what
    the operator is shown matches what the store holds — never as the source of a fact.
    """
    ev = _Evidence(output_dir, run_id)
    report = RunValidation(run_id=run_id, generated_at=_now(), build=_build_marker(),
                           purpose=str(ev.config.get("run_purpose") or "") or UNKNOWN.lower())
    if not ev.exists():
        report.checks.append(Check("run_exists", FAIL, expected="a persisted run",
                                   observed="no config.json or state.json",
                                   explanation="nothing on disk describes this run id"))
        return report

    report.layers = _layers(ev)
    report.checks.extend([
        _check_lifecycle(ev),
        _check_target_arithmetic(ev),
        _check_intake(ev),
        _check_requested_effective(ev),
        _check_execution_mode(ev),
        _check_modules(ev),
        _check_findings(ev),
        _check_evidence_files(ev),
        _check_video(ev),
        _check_contacts(ev),
        _check_activity(ev),
        _check_purpose(ev),
        _check_cleanup(ev),
    ])
    report.checks.append(_check_client_package(ev))
    if read_model is not None:
        report.checks.append(_check_surface_agreement(ev, read_model))
    if write:
        _write_report(ev, report)
    return report


def _write_report(ev: _Evidence, report: RunValidation) -> None:
    try:
        ev.root.mkdir(parents=True, exist_ok=True)
        (ev.root / REPORT_NAME).write_text(
            json.dumps(report.to_dict(), indent=2, ensure_ascii=False, sort_keys=True),
            encoding="utf-8")
    except OSError:
        pass          # a report that cannot be written is not a reason to lose the one in memory


def _build_marker() -> str:
    try:
        from core.build_identity import current_identity
        return str(current_identity().get("running_sha") or "")
    except Exception:  # noqa: BLE001 - an unknown build is reported as unknown, never invented
        return ""


# --- the three layers -----------------------------------------------------------------------------

def _layers(ev: _Evidence) -> Dict[str, Any]:
    """Requested, effective and observed for the values an operator actually asks about."""
    cfg = ev.config
    requested_pages = (ev.state.get("config") or {}).get("max_pages_per_site")
    observed_pages, observed_modes, observed_video = [], set(), []
    for pid in ev.prospects:
        coverage = ev.artifact(pid, "coverage.json") or {}
        if coverage.get("meaningful_pages_tested") is not None:
            observed_pages.append(int(coverage["meaningful_pages_tested"]))
        trace = ev.artifact(pid, "browser_trace.json") or {}
        if trace.get("backend"):
            observed_modes.add(str(trace["backend"]))
        scenario = ev.artifact(pid, "interaction_scenario.json") or {}
        if scenario:
            observed_video.append(bool(scenario.get("video_ref")))
    return {
        "execution_mode": {
            "requested": cfg.get("browser_mode", UNKNOWN),
            "effective": cfg.get("browser_mode", UNKNOWN),
            "observed": sorted(observed_modes) or UNKNOWN,
        },
        "coverage": {
            "requested": cfg.get("coverage", UNKNOWN),
            "effective": {"profile": cfg.get("coverage"), "page_ceiling": requested_pages},
            "observed": {"meaningful_pages_tested": observed_pages or UNKNOWN},
        },
        "video": {
            "requested": cfg.get("video_mode", UNKNOWN),
            "effective": cfg.get("video_mode", UNKNOWN),
            "observed": ({"clips_kept": sum(1 for kept in observed_video if kept),
                          "scenarios_run": len(observed_video)} if observed_video else UNKNOWN),
        },
        "targets": {
            "requested": list(cfg.get("seeds") or []) or UNKNOWN,
            "effective": {"max_sites": cfg.get("max_sites"), "accepted": len(ev.prospects)},
            "observed": {"analyzed": sum(1 for p in ev.prospects.values()
                                         if p.get("status") == "DONE")},
        },
        "check_families": {
            "requested": list(cfg.get("check_families") or []) or UNKNOWN,
            "effective": list(cfg.get("check_families") or []) or UNKNOWN,
            "observed": _observed_modules(ev),
        },
    }


def _observed_modules(ev: _Evidence) -> Dict[str, Any]:
    """Which QA modules left a receipt. Absence is "not executed", never "0 problems"."""
    out: Dict[str, Any] = {}
    for pid in ev.prospects:
        obs = ev.artifact(pid, "observation.json") or ev.artifact(pid, "evidence.json") or {}
        axe = str(obs.get("axe_status") or "")
        out.setdefault("accessibility", axe or "not_executed")
        out.setdefault("performance", "executed" if obs.get("perf") else "not_executed")
        shots = ev.artifact(pid, "screenshots.json") or {}
        out.setdefault("screenshot",
                       f"captured:{shots.get('captured')}" if shots else "not_executed")
        scenario = ev.artifact(pid, "interaction_scenario.json") or {}
        if scenario:
            out.setdefault("interaction", scenario.get("outcome"))
        else:
            # "Not requested" and "not executed" are different facts. A run whose video policy is
            # manual never asked for an interaction recording, and reporting that as a missing
            # receipt makes a deliberate setting look like a gap.
            mode = str(ev.config.get("video_mode") or "")
            out.setdefault("interaction",
                           "not_executed" if mode == "qualified_auto" else "not_requested")
    return out or UNKNOWN


# --- the checks -----------------------------------------------------------------------------------

def _check_lifecycle(ev: _Evidence) -> Check:
    status_value = str(ev.state.get("status") or "")
    started, finished = ev.state.get("started_at"), ev.state.get("finished_at")
    terminal = status_value in ("COMPLETED", "FAILED", "STOPPED", "CANCELLED")
    if not status_value:
        return Check("lifecycle_consistency", UNKNOWN, expected="a persisted run status",
                     observed=None, explanation="the run recorded no status")
    if terminal and not finished:
        return Check("lifecycle_consistency", FAIL, expected="a terminal run has a finish time",
                     observed={"status": status_value, "finished_at": finished},
                     explanation="the run is terminal but never recorded when it ended")
    if not terminal and finished:
        return Check("lifecycle_consistency", FAIL,
                     expected="a non-terminal run has no finish time",
                     observed={"status": status_value, "finished_at": finished},
                     explanation="the run reports it is still going and also when it ended")
    return Check("lifecycle_consistency", PASS,
                 expected="status, start and finish agree",
                 observed={"status": status_value, "started_at": started, "finished_at": finished},
                 explanation="the lifecycle timestamps match the recorded state")


def _check_target_arithmetic(ev: _Evidence) -> Check:
    if ev.is_discovery:
        counts = ev.state.get("counts") or {}
        discovered = int(counts.get("discovered") or 0)
        accounted = sum(int(counts.get(k) or 0)
                        for k in ("promoted", "rejected", "duplicates", "already_analyzed"))
        promoted, analysed = int(counts.get("promoted") or 0), len(ev.prospects)
        if not counts:
            return Check("target_count_arithmetic", UNKNOWN, expected="discovery counters",
                         observed=None, explanation="the campaign recorded no counters")
        if accounted > discovered:
            return Check("target_count_arithmetic", FAIL, expected=discovered, observed=accounted,
                         explanation="more candidates were dispositioned than were discovered")
        if promoted != analysed:
            return Check("target_count_arithmetic", FAIL,
                         expected={"promoted": promoted}, observed={"analysed_runs": analysed},
                         explanation="a promoted candidate has no analysed run behind it")
        return Check("target_count_arithmetic", PASS,
                     expected={"discovered": discovered},
                     observed={k: counts.get(k) for k in
                               ("discovered", "eligible", "promoted", "rejected", "qa_analyzed",
                                "failed")},
                     explanation=("every discovered candidate has a recorded disposition, and each "
                                  "promotion has an analysed run"))
    total = len(ev.prospects)
    by_status: Dict[str, int] = {}
    for record in ev.prospects.values():
        by_status[str(record.get("status") or "UNKNOWN")] = by_status.get(
            str(record.get("status") or "UNKNOWN"), 0) + 1
    counted = sum(by_status.values())
    seeds = len(ev.config.get("seeds") or [])
    if total == 0:
        return Check("target_count_arithmetic", UNKNOWN, expected=f"{seeds} seed(s) accounted for",
                     observed={"prospects": 0},
                     explanation="the run recorded no targets at all")
    if counted != total:
        return Check("target_count_arithmetic", FAIL, expected=total, observed=counted,
                     explanation="the per-status counts do not add up to the number of targets")
    return Check("target_count_arithmetic", PASS,
                 expected={"seeds": seeds, "targets": total},
                 observed={"by_status": by_status, "total": total},
                 explanation="every target is accounted for by exactly one status")


def _check_intake(ev: _Evidence) -> Check:
    if ev.is_discovery:
        domains = sorted({str((c or {}).get("registrable_domain") or "")
                          for c in (ev.state.get("candidates") or [])} - {""})
        return Check("source_intake_consistency", PASS if domains else UNKNOWN,
                     expected="targets found by search rather than supplied",
                     observed={"candidates": domains,
                               "promoted": ev.promoted},
                     explanation=("a discovery campaign is given a query, not a target list, so "
                                  "its intake is the candidate set it recorded"))
    seeds = list(ev.config.get("seeds") or [])
    if not seeds:
        return Check("source_intake_consistency", UNKNOWN, expected="the requested targets",
                     observed=None, explanation="the run persisted no seed list")
    from core.scout.discovery.domain_intel import canonical_domain
    wanted = {canonical_domain(s) for s in seeds if canonical_domain(s)}
    got = {canonical_domain(str(p.get("url") or "")) for p in ev.prospects.values()}
    got.discard("")
    missing = sorted(wanted - got)
    extra = sorted(got - wanted)
    if missing or extra:
        return Check("source_intake_consistency", FAIL, expected=sorted(wanted), observed=sorted(got),
                     explanation=("targets were requested that the run never held"
                                  if missing else "the run holds targets that were never requested"))
    return Check("source_intake_consistency", PASS, expected=sorted(wanted), observed=sorted(got),
                 explanation="every accepted target traces back to a requested one")


def _check_requested_effective(ev: _Evidence) -> Check:
    """The config the run was given against the config it recorded for itself."""
    persisted = ev.config
    in_state = ev.state.get("config") or {}
    if not in_state:
        return Check("requested_effective_config", UNKNOWN, expected="a config in the run state",
                     observed=None, explanation="the run state carries no configuration copy")
    watched = ("browser_mode", "coverage", "video_mode", "run_purpose", "max_pages_per_site",
               "max_sites", "concurrency", "check_families")
    drift = {k: {"config": persisted.get(k), "state": in_state.get(k)}
             for k in watched if persisted.get(k) != in_state.get(k)}
    if drift:
        return Check("requested_effective_config", FAIL, expected="one configuration",
                     observed=drift,
                     explanation="the run's own two records of its settings disagree")
    return Check("requested_effective_config", PASS,
                 expected={k: persisted.get(k) for k in watched},
                 observed={k: in_state.get(k) for k in watched},
                 explanation="the effective configuration is recorded identically in both places")


def _check_execution_mode(ev: _Evidence) -> Check:
    """A browser RECEIPT per target — never "a browser was available", which proves nothing."""
    requested = str(ev.config.get("browser_mode") or "")
    if requested != "playwright":
        return Check("browser_receipt", NOT_APPLICABLE, expected="static scan",
                     observed=requested or UNKNOWN,
                     explanation="this run did not ask for a browser, so no receipt is expected")
    receipts, missing = {}, []
    for pid in ev.prospects:
        trace = ev.artifact(pid, "browser_trace.json") or {}
        backend = str(trace.get("backend") or "")
        shot = any((ev.prospect_dir(pid) / n).is_file()
                   for n in ("landing.png", "verification.png"))
        if backend == "playwright" and shot:
            receipts[pid] = {"backend": backend, "screenshot": True}
        else:
            missing.append({"prospect": pid, "backend": backend or "none", "screenshot": shot})
    if not receipts and missing:
        return Check("browser_receipt", FAIL, expected="a browser receipt for every target",
                     observed=missing,
                     explanation="deep capture was requested but no target has browser evidence")
    if missing:
        return Check("browser_receipt", PARTIAL, expected=len(ev.prospects), observed=len(receipts),
                     explanation="some targets have browser evidence and some do not",
                     evidence_refs=[ev.evidence_ref(p, "browser_trace.json") for p in receipts])
    return Check("browser_receipt", PASS, expected="a browser receipt for every target",
                 observed=receipts,
                 explanation="every target has a browser trace and a captured screenshot",
                 evidence_refs=[ev.evidence_ref(p, "browser_trace.json") for p in receipts])


def _check_modules(ev: _Evidence) -> Check:
    observed = _observed_modules(ev)
    if observed == UNKNOWN:
        return Check("module_receipts", UNKNOWN, expected="a receipt per QA module", observed=None,
                     explanation="no target recorded any module outcome")
    unexecuted = sorted(k for k, v in observed.items() if str(v) == "not_executed")
    if unexecuted:
        return Check("module_receipts", PARTIAL, expected="every module leaves a receipt",
                     observed=observed,
                     explanation=("these modules left no receipt and are reported as not executed "
                                  "rather than as clean: " + ", ".join(unexecuted)))
    return Check("module_receipts", PASS, expected="every module leaves a receipt",
                 observed=observed, explanation="each QA module recorded what it did")


def _check_findings(ev: _Evidence) -> Check:
    """The counts in the compact state against the finding records they summarise."""
    problems, totals = [], {"verified": 0, "actionable": 0}
    for pid, record in ev.prospects.items():
        data = ev.artifact(pid, "findings.json")
        if data is None:
            if record.get("status") == "DONE":
                problems.append({"prospect": pid, "reason": "completed but no finding records"})
            continue
        verified = list(data.get("verified") or [])
        actionable = [f for f in verified if str(f.get("severity") or "") != "info"]
        totals["verified"] += len(verified)
        totals["actionable"] += len(actionable)
        if record.get("verified_findings") not in (None, len(verified)):
            problems.append({"prospect": pid, "state": record.get("verified_findings"),
                             "records": len(verified)})
        if record.get("verified_defects") not in (None, len(actionable)):
            problems.append({"prospect": pid, "state_defects": record.get("verified_defects"),
                             "records": len(actionable)})
    if problems:
        return Check("finding_count_consistency", FAIL, expected="one set of findings",
                     observed=problems,
                     explanation="the summary counts disagree with the finding records")
    return Check("finding_count_consistency", PASS, expected="one set of findings",
                 observed=totals,
                 explanation="every count is derived from the same confirmed finding records")


def _check_evidence_files(ev: _Evidence) -> Check:
    """Every manifest entry must exist and still hash to what the manifest says."""
    from core.scout.media_probe import sha256_of
    checked, broken = 0, []
    for pid in ev.prospects:
        manifest = ev.artifact(pid, "evidence_manifest.json")
        if not manifest:
            continue
        for entry in manifest.get("entries") or []:
            path = ev.prospect_dir(pid) / str(entry.get("ref") or "")
            if not path.is_file():
                broken.append({"prospect": pid, "ref": entry.get("ref"), "reason": "missing"})
                continue
            if entry.get("sha256") and sha256_of(path) != entry["sha256"]:
                broken.append({"prospect": pid, "ref": entry.get("ref"), "reason": "hash changed"})
                continue
            checked += 1
    if not checked and not broken:
        return Check("evidence_existence_hashes", UNKNOWN, expected="an evidence manifest",
                     observed=None, explanation="no target wrote an evidence manifest")
    if broken:
        return Check("evidence_existence_hashes", FAIL, expected=checked + len(broken),
                     observed={"verified": checked, "broken": broken},
                     explanation="evidence named in a manifest is missing or has changed on disk")
    return Check("evidence_existence_hashes", PASS, expected=checked, observed=checked,
                 explanation="every manifest entry exists and still matches its recorded hash")


def _check_video(ev: _Evidence) -> Check:
    """A clip is only a clip when it decodes, has a size, a duration and frames over time."""
    from core.scout.media_probe import probe_video
    mode = str(ev.config.get("video_mode") or "")
    if mode != "qualified_auto":
        return Check("video_playback", NOT_APPLICABLE, expected="no automatic video",
                     observed=mode or UNKNOWN,
                     explanation=f"video capture is {mode or 'unset'} for this run")
    clips, unplayable, scenarios = [], [], 0
    for pid in ev.prospects:
        scenario = ev.artifact(pid, "interaction_scenario.json")
        if scenario:
            scenarios += 1
        for name in ("interaction.webm", "reproduction.webm"):
            path = ev.prospect_dir(pid) / name
            if not path.is_file():
                continue
            probe = probe_video(path)
            record = {"prospect": pid, "ref": name, "bytes": probe["bytes"],
                      "duration_s": probe["duration_s"], "sha256": probe["sha256"]}
            (clips if probe["playable"] else unplayable).append(
                record if probe["playable"] else {**record, "reason": probe["error"]})
    if unplayable:
        return Check("video_playback", FAIL, expected="every kept clip decodes and plays",
                     observed=unplayable,
                     explanation="a clip was kept that does not decode as a real recording")
    if not clips:
        return Check("video_playback", NOT_APPLICABLE,
                     expected="a clip only when an interaction earned one",
                     observed={"scenarios_run": scenarios, "clips_kept": 0},
                     explanation=("no interaction produced a recording worth keeping; this is a "
                                  "policy outcome, not a failed capture"))
    return Check("video_playback", PASS, expected="every kept clip decodes and plays",
                 observed=clips, explanation="each kept recording has a duration and moving frames",
                 evidence_refs=[ev.evidence_ref(c["prospect"], c["ref"]) for c in clips])


def _check_contacts(ev: _Evidence) -> Check:
    """A contact held in memory during a run is not a contact. Only the file counts."""
    found, missing = [], []
    for pid in ev.prospects:
        contacts = ev.artifact(pid, "contacts.json")
        if contacts is None:
            continue
        # The engine writes ``public``. Reading a key it does not use reported two real addresses
        # as "a contact file that holds no address" -- the same shape as the failure this check
        # exists to catch, produced by the check itself.
        records = (contacts.get("public") or contacts.get("records")
                   or contacts.get("contacts") or [])
        if records:
            found.append({"prospect": pid, "count": len(records)})
        else:
            missing.append(pid)
    if not found and not missing:
        return Check("contact_persistence", NOT_APPLICABLE, expected="a persisted contact record",
                     observed=None,
                     explanation="this run wrote no contact file, so none is claimed")
    if not found:
        return Check("contact_persistence", PARTIAL, expected="a persisted contact",
                     observed={"empty_records": missing},
                     explanation="a contact file exists but holds no address")
    return Check("contact_persistence", PASS, expected="a persisted contact", observed=found,
                 explanation="the contacts a reader would see are the ones written to disk",
                 evidence_refs=[ev.evidence_ref(c["prospect"], "contacts.json") for c in found])


def _check_activity(ev: _Evidence) -> Check:
    """One logical chain: one start, one finish, and no target finished twice."""
    if not ev.events:
        return Check("activity_no_duplicates", UNKNOWN, expected="an activity trail", observed=None,
                     explanation="the run recorded no events")
    names = [str(e.get("event") or "") for e in ev.events]
    starts, finishes = names.count("run_started"), names.count("run_finished")
    done: Dict[str, int] = {}
    for event in ev.events:
        if event.get("event") == "prospect_done":
            key = str(event.get("prospect") or "")
            done[key] = done.get(key, 0) + 1
    duplicates = {k: v for k, v in done.items() if v > 1}
    if starts > 1 or finishes > 1 or duplicates:
        return Check("activity_no_duplicates", FAIL,
                     expected="one start, at most one finish, one completion per target",
                     observed={"run_started": starts, "run_finished": finishes,
                               "duplicate_completions": duplicates},
                     explanation="the activity trail records the same event more than once")
    return Check("activity_no_duplicates", PASS,
                 expected="one start, at most one finish, one completion per target",
                 observed={"events": len(ev.events), "run_started": starts,
                           "run_finished": finishes},
                 explanation="the trail is a single chain with no duplicate terminal events")


def _check_purpose(ev: _Evidence) -> Check:
    from core.scout.run_purpose import KNOWN_PURPOSES, PURPOSE_UNCLASSIFIED, normalise_purpose
    declared = ev.config.get("run_purpose")
    purpose = normalise_purpose(declared)
    if declared is None or str(declared).strip() == "":
        return Check("purpose_isolation", UNKNOWN, expected="a declared purpose", observed=None,
                     explanation=("this run predates the purpose field, so it is treated "
                                  "conservatively as real work and never swept"))
    if purpose == PURPOSE_UNCLASSIFIED:
        return Check("purpose_isolation", FAIL, expected=sorted(KNOWN_PURPOSES), observed=declared,
                     explanation="the run declared a purpose that is not a known value")
    return Check("purpose_isolation", PASS, expected="a declared purpose", observed=purpose,
                 explanation=f"the run was created as {purpose} and is filtered as {purpose}")


def _check_cleanup(ev: _Evidence) -> Check:
    """No temporary recording directory may survive a finished run."""
    leftovers = [ev.evidence_ref(pid, name)
                 for pid in ev.prospects
                 for name in ("_vidtmp", "_reprotmp", "_scenariotmp")
                 if (ev.prospect_dir(pid) / name).exists()]
    scenario_cleanups = [str((ev.artifact(pid, "interaction_scenario.json") or {}).get("cleanup_ok"))
                         for pid in ev.prospects
                         if ev.artifact(pid, "interaction_scenario.json")]
    if leftovers:
        return Check("cleanup_result", FAIL, expected="no temporary recording directories",
                     observed=leftovers,
                     explanation="a temporary capture directory outlived the run")
    return Check("cleanup_result", PASS, expected="no temporary recording directories",
                 observed={"temp_dirs": 0, "interaction_cleanup": scenario_cleanups or "none"},
                 explanation="nothing temporary was left behind")


def _check_client_package(ev: _Evidence) -> Check:
    """"Generated" with no ZIP and "not generated" beside one are equally wrong."""
    export = Path(ev.output_dir) / "scout" / "_client_exports" / ev.run_id
    zips = sorted(export.glob("*.zip")) if export.is_dir() else []
    if not zips:
        return Check("client_package", NOT_APPLICABLE, expected="a package only when exported",
                     observed={"packages": 0},
                     explanation="no client package was built for this run")
    import zipfile
    from core.scout.media_probe import sha256_of
    details = []
    for archive_path in zips:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                names = archive.namelist()
                manifest_name = next((n for n in names if n.endswith("manifest.json")), "")
                manifest = json.loads(archive.read(manifest_name)) if manifest_name else {}
                entries = manifest.get("entries") or []
                root = str(manifest.get("root") or "")
                missing = [e["path"] for e in entries if f"{root}/{e['path']}" not in names]
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            return Check("client_package", FAIL, expected="a readable package",
                         observed={"path": archive_path.name, "error": type(exc).__name__},
                         explanation="the exported package could not be opened")
        if missing:
            return Check("client_package", FAIL, expected="every manifest entry is in the archive",
                         observed={"missing": missing},
                         explanation="the manifest names files the archive does not contain")
        details.append({"path": archive_path.name, "bytes": archive_path.stat().st_size,
                        "sha256": sha256_of(archive_path), "manifest_entries": len(entries)})
    return Check("client_package", PASS, expected="a readable package matching its manifest",
                 observed=details,
                 explanation="every manifest entry exists inside the archive it describes")


def _check_surface_agreement(ev: _Evidence, read_model: Any) -> Check:
    """The derived read model against the store. The UI is checked, never consulted."""
    from core.scout.discovery.domain_intel import canonical_domain
    disagreements = []
    for pid, record in ev.prospects.items():
        domain = canonical_domain(str(record.get("url") or ""))
        if not domain:
            continue
        # Pin the run the target's evidence ACTUALLY lives in. A discovery campaign holds no
        # prospects of its own, so pinning the campaign id asks for evidence that was never there
        # and gets the correct refusal -- which then reads as a disagreement between surfaces.
        home_run = pid.split("/", 1)[0] if "/" in pid else ev.run_id
        try:
            detail = read_model.target_detail(domain, run=home_run)
        except Exception as exc:  # noqa: BLE001
            disagreements.append({"domain": domain, "error": type(exc).__name__})
            continue
        stored = ev.artifact(pid, "findings.json") or {}
        expected_findings = len([f for f in (stored.get("verified") or [])
                                 if str(f.get("severity") or "") != "info"])
        shown = len([f for f in (detail.get("findings") or [])
                     if str(f.get("severity") or "") != "info"])
        if record.get("status") == "DONE" and shown != expected_findings:
            disagreements.append({"domain": domain, "store": expected_findings, "shown": shown})
        if detail.get("evidence_status") == "prospect_not_found":
            disagreements.append({"domain": domain, "reason": "the read model cannot bind evidence"})
    if disagreements:
        return Check("surface_agreement", FAIL, expected="the store and the read model agree",
                     observed=disagreements,
                     explanation="what an operator is shown differs from what the run recorded")
    return Check("surface_agreement", PASS, expected="the store and the read model agree",
                 observed={"targets": len(ev.prospects)},
                 explanation="every target's read model matches its own persisted records")

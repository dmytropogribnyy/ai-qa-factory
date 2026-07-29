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
    build: str = ""              # the build that is VALIDATING (kept: the original key name)
    execution_build: str = ""    # the build that RAN the work; re-validation must never overwrite it
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

    @property
    def validation_build(self) -> str:
        """The build that CHECKED the run. Named explicitly because ``build`` alone cannot say which
        of the two it is, and a machine consumer choosing between them was left guessing."""
        return self.build

    def to_dict(self) -> Dict[str, Any]:
        return {"schema": SCHEMA, "run_id": self.run_id, "generated_at": self.generated_at,
                # Both names for the same value: the explicit one to read, the original one kept so
                # a consumer written against the earlier shape does not break.
                "validation_build": self.validation_build, "build": self.build,
                "execution_build": self.execution_build,
                "purpose": self.purpose, "status": self.status,
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
        # Every candidate the campaign recorded, kept as records rather than as tallies. The
        # persisted counters are OVERLAPPING classifications -- one candidate can be a duplicate and
        # rejected at the same time -- so they can never be summed into a partition. The records can.
        self.candidates: List[Dict[str, Any]] = [
            record for record in (self.state.get("candidates") or []) if isinstance(record, dict)]
        # A promoted child declares its own purpose. Validating only the parent lets an acceptance
        # campaign promote children that land in production counters.
        self.child_configs: Dict[str, Dict[str, Any]] = {}
        # A promotion with no child at all and a promotion whose child is still working are two
        # different facts, and collapsing them into one "analysed runs" number turns a healthy
        # in-flight campaign into a corrupt one.
        self.child_status: Dict[str, str] = {}
        self.promotions_without_child: List[str] = []
        for record in self.candidates:
            child = str(record.get("promoted_scout_run") or "")
            if not child:
                if str(record.get("promotion_decision") or "") == "promoted":
                    self.promotions_without_child.append(
                        str(record.get("candidate_id") or record.get("registrable_domain") or "?"))
                continue
            self.promoted.append(child)
            child_root = Path(output_dir) / "scout" / child
            try:
                child_state = json.loads((child_root / "state.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # The campaign says it promoted into this run and the run is not on disk.
                self.child_status[child] = "missing"
                continue
            self.child_status[child] = str(child_state.get("status") or "") or UNKNOWN
            try:
                self.child_configs[child] = json.loads(
                    (child_root / "config.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self.child_configs[child] = {}
            for pid, rec in (child_state.get("prospects") or {}).items():
                if isinstance(rec, dict):
                    key = f"{child}/{pid}"
                    self.prospects[key] = rec
                    self._homes[key] = child_root

    @property
    def execution_build(self) -> str:
        """The build that RAN the work, which is not the build validating it.

        Re-validating an old run on today's code and stamping today's SHA on the report erases the
        one fact a disputed finding needs: which code produced it. A run that recorded nothing is
        UNKNOWN, and stays UNKNOWN — an absent SHA is never filled in from the environment.
        """
        from core.build_identity import stamped_build
        value = stamped_build((self.state or {}).get("execution_build"))
        if value:
            return value
        for source in (self.state, self.config):
            for key in ("build", "running_sha", "build_sha", "running_build"):
                value = str((source or {}).get(key) or "")
                if value:
                    return value
        return UNKNOWN

    def child_execution_builds(self) -> Dict[str, str]:
        """Each promoted child's own stamp, kept apart from the parent's — and just as honest about
        having been produced by a modified tree."""
        from core.build_identity import stamped_build
        out: Dict[str, str] = {}
        for child in self.promoted:
            try:
                child_state = json.loads(
                    (Path(self.output_dir) / "scout" / child / "state.json").read_text(
                        encoding="utf-8"))
            except (OSError, ValueError):
                continue
            out[child] = stamped_build(child_state.get("execution_build")) or UNKNOWN
        return out

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
                           execution_build=ev.execution_build,
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
        _check_intake_provenance(ev),
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
    report.checks.append(_check_execution_build(ev))
    if read_model is not None:
        report.checks.append(_check_surface_agreement(ev, read_model))
    else:
        # Absent is not the same as passed. Leaving the check OUT let the store and the operator's
        # screen disagree inside a report that still read VALIDATED — and the report a run writes
        # for itself, the one most likely to be read unattended, was exactly the one omitting it.
        report.checks.append(Check(
            "surface_agreement", UNKNOWN,
            expected="the read model agrees with the store",
            observed="no read model was supplied to this validation",
            explanation="what the operator is shown was never compared with what the store holds"))
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
    """The build doing the VALIDATING, under its honest name. A report written from a modified tree
    is not evidence produced by the commit it would otherwise name."""
    try:
        from core.build_identity import current_identity
        ident = current_identity()
        return str(ident.get("running_build") or ident.get("running_sha") or "")
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


def _module_receipts(ev: _Evidence) -> Dict[str, Dict[str, str]]:
    """Which QA modules left a receipt, PER TARGET. Absence is "not executed", never "0 problems".

    This used to collapse into one flat ``{module: outcome}`` map filled with ``setdefault`` inside
    the loop, which meant the FIRST target answered on behalf of all of them: a second target that
    never ran accessibility was not merely unreported, it was unobservable. Keeping the target axis
    is the whole check.
    """
    out: Dict[str, Dict[str, str]] = {}
    mode = str(ev.config.get("video_mode") or "")
    for pid in ev.prospects:
        obs = ev.artifact(pid, "observation.json") or ev.artifact(pid, "evidence.json") or {}
        shots = ev.artifact(pid, "screenshots.json") or {}
        scenario = ev.artifact(pid, "interaction_scenario.json") or {}
        out[pid] = {
            "accessibility": str(obs.get("axe_status") or "") or "not_executed",
            "performance": "executed" if obs.get("perf") else "not_executed",
            "screenshot": f"captured:{shots.get('captured')}" if shots else "not_executed",
            # "Not requested" and "not executed" are different facts. A run whose video policy is
            # manual never asked for an interaction recording, and reporting that as a missing
            # receipt makes a deliberate setting look like a gap.
            "interaction": (str(scenario.get("outcome") or "recorded") if scenario
                            else ("not_executed" if mode == "qualified_auto" else "not_requested")),
        }
    return out


def _observed_modules(ev: _Evidence) -> Any:
    """The per-target receipts as the Observed layer. UNKNOWN when there is no target at all."""
    return _module_receipts(ev) or UNKNOWN


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


def _disposition_partition(ev: _Evidence) -> Dict[str, Any]:
    """Partition the candidates by the ONE explicit decision each of them carries.

    The persisted counters cannot be summed into a total: `duplicates`, `rejected` and
    `already_analyzed` are overlapping labels, so one candidate can legitimately appear in several
    of them and `promoted + rejected + ...` can exceed `discovered` without anything being wrong.
    `promotion_decision` is different — the engine resolves every record to exactly one value before
    it persists, so these buckets are a true partition and their sum is checkable.
    """
    buckets: Dict[str, int] = {}
    unaccounted: List[str] = []
    for record in ev.candidates:
        decision = str(record.get("promotion_decision") or "").strip()
        if not decision or decision == "pending":
            unaccounted.append(str(record.get("candidate_id")
                                   or record.get("registrable_domain") or "?"))
            continue
        buckets[decision] = buckets.get(decision, 0) + 1
    counts = ev.state.get("counts") or {}
    declared_discovered = int(counts.get("discovered") or 0)
    # The overlapping labels cannot be SUMMED against `discovered`, but each one is a subset of it:
    # a campaign cannot reject, duplicate or already-have-analysed more candidates than it found.
    # That is the part of the old arithmetic that was true, kept as its own provable invariant.
    impossible = sorted(
        name for name, value in counts.items()
        if isinstance(value, int) and not isinstance(value, bool)
        and name not in ("discovered", "candidates") and value > declared_discovered)
    terminal = {"COMPLETED", "FAILED", "STOPPED", "CANCELLED"}
    running = sorted(child for child, status in ev.child_status.items()
                     if status not in terminal and status != "missing")
    return {
        "buckets": buckets,
        "unaccounted": unaccounted,
        "records": len(ev.candidates),
        "accounted": sum(buckets.values()),
        "declared_discovered": declared_discovered,
        "declared_promoted": int(counts.get("promoted") or 0),
        "impossible_counters": impossible,
        "analysed_runs": len(ev.prospects),
        # Promotions and their children, told apart rather than summed.
        "promoted_children": sorted(ev.child_status),
        "completed_children": sorted(child for child, status in ev.child_status.items()
                                     if status in terminal),
        "running_children": running,
        "missing_children": (sorted(child for child, status in ev.child_status.items()
                                    if status == "missing")
                             + list(ev.promotions_without_child)),
        "child_status": dict(ev.child_status),
    }


def _disposition_status(partition: Dict[str, Any]) -> str:
    """The POLICY call, decided by the owner: which shapes may still be VALIDATED?

    Precedence is FAIL > UNKNOWN > PARTIAL > PASS, and UNKNOWN means "the data needed to judge is
    absent or unconfirmable" — never a proven disagreement, which is always FAIL.

    1. A candidate a terminal campaign never decided about is an integrity violation, not merely
       unfinished work.
    2. Records that do not add up to the aggregate the campaign published is a contradiction
       between two things it wrote itself.
    3. A promotion is judged by its CHILD, not by a count: a child that is absent or unlinked is a
       FAIL, a child that exists and is still working is a PARTIAL, and only children that reached
       a terminal state satisfy this condition. Sharing one `analysed_runs` number between those
       three cases is what would declare a healthy in-flight campaign corrupt.
    4. `held_for_review` is a decision, so the candidate IS accounted for — but a campaign waiting
       on a human has not finished being validated.
    """
    if partition["unaccounted"]:
        return FAIL
    if partition["missing_children"]:
        return FAIL
    if partition["accounted"] != partition["declared_discovered"]:
        return FAIL
    if partition["impossible_counters"]:
        return FAIL
    if not partition["records"] and not partition["declared_discovered"]:
        return UNKNOWN
    if partition["running_children"]:
        return PARTIAL
    if partition["buckets"].get("held_for_review"):
        return PARTIAL
    # Every promotion is terminal, so the analysed runs behind them must now be there.
    if partition["declared_promoted"] != partition["analysed_runs"]:
        return FAIL
    return PASS


def _check_target_arithmetic(ev: _Evidence) -> Check:
    if ev.is_discovery:
        counts = ev.state.get("counts") or {}
        partition = _disposition_partition(ev)
        if not counts and not ev.candidates:
            return Check("target_count_arithmetic", UNKNOWN, expected="discovery counters",
                         observed=None, explanation="the campaign recorded no counters")
        status = _disposition_status(partition)
        explanation = {
            PASS: ("every candidate carries exactly one disposition, the records add up to the "
                   "published total, and every promotion has a finished run behind it"),
            PARTIAL: ("every candidate is accounted for, but the campaign is still waiting: a "
                      "promoted run is in flight or a candidate is held for human review"),
            FAIL: ("the campaign cannot account for every candidate it discovered, or claims a "
                   "promotion with no run behind it"),
            UNKNOWN: "the campaign recorded neither candidates nor a discovered total",
        }[status]
        return Check("target_count_arithmetic", status,
                     expected={"discovered": partition["declared_discovered"],
                               "every candidate carries exactly one disposition": True},
                     observed=partition, explanation=explanation)
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


def _check_intake_provenance(ev: _Evidence) -> Check:
    """Not what was scanned — where the list of things to scan CAME FROM.

    An uploaded client list and a pasted one produced identical config on disk, so "did we scan the
    file they sent us?" had no answer anybody could check. The record is bounded and its own
    arithmetic has to close: rows read = accepted + rejected + duplicates.
    """
    intake = ev.config.get("intake") or {}
    if not isinstance(intake, dict) or not intake:
        return Check("intake_provenance", UNKNOWN, expected="a recorded intake source",
                     observed=None,
                     explanation=("this run predates intake provenance, so where its targets came "
                                  "from cannot be established from what is on disk"))
    kind = str(intake.get("kind") or "")
    if kind == "upload" and not str(intake.get("source_name") or "").strip():
        return Check("intake_provenance", FAIL, expected="an uploaded list names its file",
                     observed=intake,
                     explanation="the run says a file was uploaded and does not say which file")
    read = intake.get("rows_read")
    parts = [intake.get(k) for k in ("rows_accepted", "rows_rejected", "duplicates", "rows_capped")]
    if read is not None and all(p is not None for p in parts):
        accounted = sum(int(p) for p in parts)
        if int(read) != accounted:
            return Check("intake_provenance", FAIL,
                         expected={"rows_read": read},
                         observed={"accounted": accounted, **intake},
                         explanation="the intake accounting does not add up to the rows it read")
    accepted = intake.get("rows_accepted")
    seeds = len(ev.config.get("seeds") or [])
    if accepted is not None and kind in ("paste", "upload") and int(accepted) != seeds:
        return Check("intake_provenance", FAIL, expected={"rows_accepted": accepted},
                     observed={"seeds_persisted": seeds},
                     explanation=("the run kept a different number of seeds than intake says it "
                                  "accepted"))
    return Check("intake_provenance", PASS, expected="a recorded, self-consistent intake source",
                 observed=intake,
                 explanation=f"the target list arrived by {kind} and its accounting closes")


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
    receipts = _module_receipts(ev)
    if not receipts:
        return Check("module_receipts", UNKNOWN, expected="a receipt per QA module", observed=None,
                     explanation="no target recorded any module outcome")
    gaps = {pid: sorted(name for name, value in modules.items() if value == "not_executed")
            for pid, modules in receipts.items()}
    gaps = {pid: missing for pid, missing in gaps.items() if missing}
    if gaps:
        return Check("module_receipts", PARTIAL,
                     expected="every module leaves a receipt on every target",
                     observed=receipts,
                     explanation=("these targets left no receipt for a module and are reported as "
                                  "not executed rather than as clean: "
                                  + "; ".join(f"{pid}: {', '.join(missing)}"
                                              for pid, missing in sorted(gaps.items()))))
    return Check("module_receipts", PASS, expected="every module leaves a receipt on every target",
                 observed=receipts,
                 explanation=f"each of the {len(receipts)} target(s) recorded what every module did")


def _check_findings(ev: _Evidence) -> Check:
    """The counts in the compact state against the finding records they summarise."""
    problems, totals = [], {"verified": 0, "actionable": 0}
    for pid, record in ev.prospects.items():
        data = ev.artifact(pid, "findings.json")
        if data is None:
            if record.get("status") == "DONE":
                problems.append({"prospect": pid, "reason": "completed but no finding records"})
            continue
        from core.scout.actionable import actionable_set
        # Compared through the canonical split on BOTH sides. The engine writes these numbers from
        # the split, so measuring the records with a raw `len()` counts a suppressed duplicate the
        # state deliberately does not — and reports the agreement as a disagreement.
        canonical = actionable_set(data.get("verified") or [])
        totals["verified"] += canonical.total
        totals["actionable"] += canonical.confirmed_issue_count
        if record.get("verified_findings") not in (None, canonical.total):
            problems.append({"prospect": pid, "state": record.get("verified_findings"),
                             "records": canonical.total})
        if record.get("verified_defects") not in (None, canonical.confirmed_issue_count):
            problems.append({"prospect": pid, "state_defects": record.get("verified_defects"),
                             "records": canonical.confirmed_issue_count})
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
            # An address with no reviewable origin cannot be checked by the person who has to
            # decide whether to write to it, and "we found it somewhere on the site" is not a source.
            without_source = [str(r.get("email") or "?") for r in records
                              if isinstance(r, dict) and not str(r.get("source_url") or "").strip()]
            found.append({"prospect": pid, "count": len(records),
                          "without_provenance": without_source})
        else:
            missing.append(pid)
    unsourced = [entry for entry in found if entry["without_provenance"]]
    if unsourced:
        return Check("contact_persistence", PARTIAL,
                     expected="every persisted contact names the page it came from",
                     observed=unsourced,
                     explanation="a contact was kept without the source URL that justifies it")
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
    # Two vocabularies, one lifecycle: a Scout run writes run_started/run_finished, a discovery
    # campaign writes campaign_started/campaign_finished. Counting only the first pair would have
    # made "exactly one start" fail every campaign ever run.
    starts = names.count("run_started") + names.count("campaign_started")
    finishes = names.count("run_finished") + names.count("campaign_finished")
    done: Dict[str, int] = {}
    for event in ev.events:
        if event.get("event") == "prospect_done":
            key = str(event.get("prospect") or "")
            done[key] = done.get(key, 0) + 1
    duplicates = {k: v for k, v in done.items() if v > 1}
    # Exactly one start, and exactly one terminal event once the run IS terminal. Only counting
    # events that occur too often left the opposite hole wide open: a run whose start or finish was
    # never written passed a check named for the trail being a single complete chain.
    terminal_state = str(ev.state.get("status") or "") in ("COMPLETED", "FAILED", "STOPPED",
                                                           "CANCELLED")
    expected_finishes = 1 if terminal_state else 0
    observed = {"run_started": starts, "run_finished": finishes,
                "duplicate_completions": duplicates, "run_status": ev.state.get("status")}
    if starts != 1 or finishes != expected_finishes or duplicates:
        return Check("activity_no_duplicates", FAIL,
                     expected={"run_started": 1, "run_finished": expected_finishes,
                               "duplicate_completions": {}},
                     observed=observed,
                     explanation=("the activity trail is not one complete chain: a lifecycle event "
                                  "is missing or recorded more than once"))
    return Check("activity_no_duplicates", PASS,
                 expected={"run_started": 1, "run_finished": expected_finishes},
                 observed={"events": len(ev.events), **observed},
                 explanation="exactly one start, one terminal event, and one completion per target")


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
    # A campaign's purpose does not travel to its children by wishing. An acceptance campaign that
    # promotes production children puts test work into the operator's real counters, and validating
    # only the parent reports that as isolated.
    strays = {child: (cfg.get("run_purpose") if cfg.get("run_purpose") not in (None, "") else None)
              for child, cfg in ev.child_configs.items()
              if normalise_purpose(cfg.get("run_purpose")) != purpose}
    if strays:
        return Check("purpose_isolation", FAIL, expected={"every promoted child": purpose},
                     observed=strays,
                     explanation=("a promoted child run declares a different purpose from the "
                                  "campaign that created it"))
    return Check("purpose_isolation", PASS, expected="a declared purpose",
                 observed={"run": purpose, "promoted_children": len(ev.child_configs)},
                 explanation=(f"the run was created as {purpose} and is filtered as {purpose}, "
                              f"and every promoted child declares the same purpose"))


def _check_cleanup(ev: _Evidence) -> Check:
    """No temporary recording directory may survive a finished run."""
    leftovers = [ev.evidence_ref(pid, name)
                 for pid in ev.prospects
                 for name in ("_vidtmp", "_reprotmp", "_scenariotmp")
                 if (ev.prospect_dir(pid) / name).exists()]
    # A scenario that touched a live control and could not put it back is an unresolved change on
    # someone else's site. It was recorded here and reported as an observation beside a PASS.
    not_restored, cleanups = [], {}
    for pid in ev.prospects:
        scenario = ev.artifact(pid, "interaction_scenario.json")
        if not scenario:
            continue
        cleanup_ok = scenario.get("cleanup_ok")
        cleanups[pid] = cleanup_ok
        if scenario.get("action_performed") and cleanup_ok is not True:
            not_restored.append({"prospect": pid, "cleanup_ok": cleanup_ok,
                                 "scenario": scenario.get("scenario")})
    if leftovers:
        return Check("cleanup_result", FAIL, expected="no temporary recording directories",
                     observed=leftovers,
                     explanation="a temporary capture directory outlived the run")
    if not_restored:
        return Check("cleanup_result", FAIL,
                     expected="every performed interaction is undone and the undo is verified",
                     observed=not_restored,
                     explanation=("an interaction changed a control and the run could not verify it "
                                  "was restored"))
    return Check("cleanup_result", PASS,
                 expected="no temporary directories and every performed interaction restored",
                 observed={"temp_dirs": 0, "interaction_cleanup": cleanups or "none"},
                 explanation="nothing temporary was left behind and every interaction was undone")


def _check_client_package(ev: _Evidence) -> Check:
    """"Generated" with no ZIP and "not generated" beside one are equally wrong."""
    # The ONE directory-resolution function the builder uses. A validator that spells the path
    # itself — here it was the raw run id where the builder writes slug-hash12 — audits a folder
    # nothing writes to, and every real deliverable reads "no package" while a tampered one
    # still validates.
    from core.scout.client_evidence import client_export_dir
    export = client_export_dir(ev.output_dir, ev.run_id)
    zips = sorted(export.glob("*.zip")) if export.is_dir() else []
    if not zips:
        return Check("client_package", NOT_APPLICABLE, expected="a package only when exported",
                     observed={"packages": 0},
                     explanation="no client package was built for this run")
    import hashlib
    import zipfile
    from core.scout.media_probe import sha256_of
    details = []
    for archive_path in zips:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                names = [n for n in archive.namelist() if not n.endswith("/")]
                manifest_name = next((n for n in names if n.endswith("manifest.json")), "")
                if not manifest_name:
                    return Check("client_package", FAIL, expected="a manifest inside the archive",
                                 observed={"path": archive_path.name},
                                 explanation="the package carries no manifest to check it against")
                manifest = json.loads(archive.read(manifest_name))
                entries = manifest.get("entries") or []
                root = str(manifest.get("root") or "")
                # ONE root folder, and it is the one the manifest names. A flat archive scatters a
                # dozen loose files across whatever directory the client unpacked it in.
                roots = {n.split("/", 1)[0] for n in names}
                if roots != {root} or not root:
                    return Check("client_package", FAIL, expected={"single root": root},
                                 observed={"roots": sorted(roots)},
                                 explanation="the archive does not unpack into the one folder it declares")
                missing = [e["path"] for e in entries if f"{root}/{e['path']}" not in names]
                if missing:
                    return Check("client_package", FAIL,
                                 expected="every manifest entry is in the archive",
                                 observed={"missing": missing},
                                 explanation="the manifest names files the archive does not contain")
                # A hash nobody recomputes is decoration. Every member, not a sample.
                altered = []
                for entry in entries:
                    declared = str(entry.get("sha256") or "")
                    if not declared:
                        altered.append({"path": entry.get("path"), "reason": "no hash recorded"})
                        continue
                    actual = hashlib.sha256(archive.read(f"{root}/{entry['path']}")).hexdigest()
                    if actual != declared:
                        altered.append({"path": entry.get("path"), "reason": "hash mismatch"})
                if altered:
                    return Check("client_package", FAIL, expected="every member hashes as recorded",
                                 observed=altered,
                                 explanation="a packaged file does not match the hash beside it")
                unlisted = sorted(set(names) - {f"{root}/{e['path']}" for e in entries}
                                  - {manifest_name})
                if unlisted:
                    return Check("client_package", FAIL, expected="the manifest lists every member",
                                 observed={"unlisted": unlisted},
                                 explanation="the archive contains files its manifest does not describe")
                # What must never leave the building, checked in the artifact that leaves it.
                readable = {n: archive.read(n).decode("utf-8", "ignore") for n in names
                            if n.endswith((".html", ".csv", ".json", ".txt", ".md"))}
                leaks = _forbidden_content(readable)
                if leaks:
                    return Check("client_package", FAIL,
                                 expected="no local paths, credentials or operator internals",
                                 observed=leaks,
                                 explanation="the package carries content that must not be sent")
                video_problems = _packaged_video_problems(archive, names)
                if video_problems:
                    return Check("client_package", FAIL, expected="every packaged clip plays",
                                 observed=video_problems,
                                 explanation="a video was packaged that does not decode as a recording")
        except (OSError, ValueError, zipfile.BadZipFile) as exc:
            return Check("client_package", FAIL, expected="a readable package",
                         observed={"path": archive_path.name, "error": type(exc).__name__},
                         explanation="the exported package could not be opened")
        details.append({"path": archive_path.name, "bytes": archive_path.stat().st_size,
                        "sha256": sha256_of(archive_path), "manifest_entries": len(entries),
                        "root": root})
    return Check("client_package", PASS,
                 expected="one root, every member listed and hashed, nothing forbidden inside",
                 observed=details,
                 explanation=("every manifest entry exists, still hashes as recorded, and the "
                              "package carries no local path, credential or unplayable clip"))


def _forbidden_content(readable: Dict[str, str]) -> List[Dict[str, str]]:
    """Local paths, credentials and operator-only internals, found in the thing that gets sent."""
    from core.orchestration.content_safety import ContentSecretScanner
    leaks: List[Dict[str, str]] = []
    for name, text in readable.items():
        for marker, reason in (("C:\\", "absolute local path"), ("C:/", "absolute local path"),
                               ("file://", "local file link"),
                               ("/outputs/scout/", "internal workspace path"),
                               ("Authorization:", "credential header"),
                               ("Set-Cookie", "cookie"), ("Bearer ", "bearer token")):
            if marker in text:
                leaks.append({"file": name, "reason": reason})
        found = ContentSecretScanner().scan_text(name, text)
        if found:
            leaks.append({"file": name, "reason": "secret scanner: " + ", ".join(map(str, found))})
    return leaks


def _packaged_video_problems(archive: Any, names: List[str]) -> List[Dict[str, Any]]:
    """A clip inside a ZIP is only evidence if it still decodes after being unpacked."""
    import tempfile
    from core.scout.media_probe import probe_video
    problems: List[Dict[str, Any]] = []
    clips = [n for n in names if n.lower().endswith((".webm", ".mp4"))]
    if not clips:
        return problems
    with tempfile.TemporaryDirectory() as tmp:
        for name in clips:
            path = Path(tmp) / Path(name).name
            path.write_bytes(archive.read(name))
            probe = probe_video(path)
            if not probe.get("playable"):
                problems.append({"file": name, "reason": probe.get("error") or "does not decode"})
    return problems


def _check_execution_build(ev: _Evidence) -> Check:
    """Which code produced this run, recorded by the run rather than inferred later.

    Kept as its own check because the alternative to knowing is not "assume the current checkout" —
    it is saying so. A run written before the stamp existed is UNKNOWN, which blocks VALIDATED
    honestly rather than being quietly filled in from the environment.
    """
    own = ev.execution_build
    children = ev.child_execution_builds()
    if own == UNKNOWN:
        return Check("execution_build_identity", UNKNOWN,
                     expected="the run records the build that executed it",
                     observed={"execution_build": UNKNOWN, "children": children},
                     explanation=("this run predates execution-build stamping, so which code "
                                  "produced it cannot be established from what is on disk"))
    unstamped = sorted(child for child, sha in children.items() if sha == UNKNOWN)
    if unstamped:
        return Check("execution_build_identity", PARTIAL,
                     expected="every promoted child records its own build",
                     observed={"execution_build": own, "children": children},
                     explanation=("a promoted run does not say which code executed it: "
                                  + ", ".join(unstamped)))
    # Differing builds are not an error. A long campaign can promote a run after the checkout under
    # it has moved, and the useful thing is that both facts are recorded rather than merged.
    return Check("execution_build_identity", PASS,
                 expected="the run records the build that executed it",
                 observed={"execution_build": own, "children": children,
                           "children_match_parent": all(sha == own for sha in children.values())},
                 explanation=("the executing build is recorded by the run itself and is kept "
                              "separate from the build performing this validation"))


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
        from core.scout.actionable import KIND_ACTIONABLE, actionable_set, count_kinds
        stored = ev.artifact(pid, "findings.json") or {}
        # The STORE is split canonically, because it holds complete findings. The SCREEN is counted
        # from the labels it carries, because its findings are projected and splitting them again
        # merges any two the projection can no longer tell apart — which is the product's own
        # projection being reported as a disagreement.
        expected_findings = actionable_set(stored.get("verified") or []).confirmed_issue_count
        shown = count_kinds(detail.get("findings") or [])[KIND_ACTIONABLE]
        if record.get("status") == "DONE" and shown != expected_findings:
            disagreements.append({"domain": domain, "store": expected_findings, "shown": shown})
        # The count the operator reads must be the count the page's own list contains.
        summary = (detail.get("actionable_summary") or {}).get("confirmed_issues")
        if summary is not None and summary != shown:
            disagreements.append({"domain": domain, "reason": "the page's count and its own list "
                                                             "disagree",
                                  "summary": summary, "listed": shown})
        if detail.get("evidence_status") == "prospect_not_found":
            disagreements.append({"domain": domain, "reason": "the read model cannot bind evidence"})
        # The REGISTRY is the surface History reads. A target the run finished while the registry
        # still calls it unanalysed is one row saying done beside another saying it never happened.
        try:
            from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
            entry = AnalyzedSiteRegistry(ev.output_dir).get(domain)
        except Exception:      # noqa: BLE001
            entry = None
        if record.get("status") == "DONE" and entry is not None:
            registry_status = str(getattr(entry, "analysis_status", "") or "").upper()
            if registry_status not in ("ANALYZED", ""):
                disagreements.append({"domain": domain, "reason": "History and the run disagree",
                                      "registry": registry_status, "run": "DONE"})
    # The OBSERVER is a third reader of the same store, and a direct run used to report zero
    # evidence and zero findings there while its own target pages listed both.
    try:
        from core.scout.observer_api import ObserverAPI
        observer = ObserverAPI(ev.output_dir)
        seen_findings = observer.list_findings(ev.run_id)["total"]
        seen_evidence = observer.get_evidence_manifest(ev.run_id)["count"]
    except Exception as exc:      # noqa: BLE001 - reported, never assumed fine
        disagreements.append({"surface": "observer",
                              "reason": f"the observer could not read this run ({type(exc).__name__})"})
        seen_findings = seen_evidence = None
    if seen_findings is not None and not ev.is_discovery:
        # Counted RAW on both sides: the observer lists every finding row, so comparing it against
        # the canonical actionable count would manufacture a disagreement out of the split itself.
        stored_total = sum(len((ev.artifact(pid, "findings.json") or {}).get("verified") or [])
                           for pid in ev.prospects)
        if stored_total and not seen_findings:
            disagreements.append({"surface": "observer", "stored": stored_total, "shown": 0,
                                  "reason": "the observer reports no finding for a run that has some"})
        files = sum(1 for pid in ev.prospects
                    for _f in ev.prospect_dir(pid).glob("*")
                    if _f.is_file() and _f.suffix.lower() in (".json", ".png", ".webm"))
        if files and not seen_evidence:
            disagreements.append({"surface": "observer", "stored_files": files, "shown": 0,
                                  "reason": "the observer reports no evidence for a run that has some"})
    if disagreements:
        return Check("surface_agreement", FAIL, expected="the store and the read model agree",
                     observed=disagreements,
                     explanation="what an operator is shown differs from what the run recorded")
    return Check("surface_agreement", PASS, expected="the store and the read model agree",
                 observed={"targets": len(ev.prospects)},
                 explanation="every target's read model matches its own persisted records")

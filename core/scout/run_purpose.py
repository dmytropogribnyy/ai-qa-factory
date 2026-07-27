"""Why a run exists — declared once at launch, and never inferred afterwards.

An acceptance run and a production run can scan the same company on the same day. They must not
share a fate: the acceptance one is disposable and must stay out of the numbers an operator makes
decisions from, the production one is the work itself. Everything downstream — History, Overview,
Needs attention, Data management — needs the same answer to "what was this run for?", so the answer
lives here rather than being re-derived, differently, by each surface.

Three rules hold the model together:

**Declared at creation, never guessed.** A run records its purpose in ``config.json`` when it
starts. A run that predates the field is ``unclassified`` — not "probably a test" because its id
begins with ``acceptance-``. Guessing from a name is how production history disappears.

**Ordinary runs are production.** The daily operator form does not ask, and the answer it does not
ask for is ``production``. A new run therefore never appears as ``unclassified``; that value now
means only "written before this field existed".

**A test purpose is a deliberate act.** An untrusted request cannot label its own run disposable by
adding a field to a POST body: the HTTP launcher accepts a test purpose only when the server was
started with test purposes enabled. The CLI and the in-process harness are already deliberate, so
they set it directly.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Set

PURPOSE_PRODUCTION = "production"
PURPOSE_DIAGNOSTIC = "diagnostic"
PURPOSE_ACCEPTANCE = "acceptance"
PURPOSE_MANUAL_TEST = "manual_test"
PURPOSE_UNCLASSIFIED = "unclassified"

# Purposes whose data is understood to be disposable. Production and unclassified are not here, and
# that is the whole point.
REMOVABLE_PURPOSES = frozenset({PURPOSE_DIAGNOSTIC, PURPOSE_ACCEPTANCE, PURPOSE_MANUAL_TEST})
# The purposes a launch may declare. "unclassified" is a reading of old data, never a choice.
DECLARABLE_PURPOSES = REMOVABLE_PURPOSES | {PURPOSE_PRODUCTION}
KNOWN_PURPOSES = REMOVABLE_PURPOSES | {PURPOSE_PRODUCTION, PURPOSE_UNCLASSIFIED}

PURPOSE_LABELS = {
    PURPOSE_PRODUCTION: "Production",
    PURPOSE_DIAGNOSTIC: "Diagnostic",
    PURPOSE_ACCEPTANCE: "Acceptance",
    PURPOSE_MANUAL_TEST: "Manual test",
    PURPOSE_UNCLASSIFIED: "Unclassified",
}

# Set on the SERVER (never in a request) to let an acceptance harness drive the real operator
# endpoints while still labelling its runs honestly.
TEST_PURPOSE_ENV = "AIQA_SCOUT_TEST_PURPOSE"
_OPERATOR_STATE_NAME = "data_management.json"


class PurposeNotPermitted(ValueError):
    """A request asked for a test purpose the server is not configured to hand out."""


def normalise_purpose(value: Any) -> str:
    """Map a persisted value onto a known purpose, defaulting to unclassified rather than guessing."""
    text = str(value or "").strip().lower().replace("-", "_")
    return text if text in KNOWN_PURPOSES else PURPOSE_UNCLASSIFIED


def is_removable(purpose: str) -> bool:
    return normalise_purpose(purpose) in REMOVABLE_PURPOSES


def test_purposes_enabled(env: Optional[Mapping[str, str]] = None) -> bool:
    """Whether this server may accept a test purpose over HTTP. Off unless deliberately switched on."""
    source = os.environ if env is None else env
    return str(source.get(TEST_PURPOSE_ENV, "")).strip().lower() in ("1", "true", "yes", "on")


def resolve_requested_purpose(requested: Any, *, allow_test: bool) -> str:
    """The purpose a launch should record, given what an untrusted caller asked for.

    Nothing asked for means ``production`` — the ordinary case, and the one the daily form takes.
    A test purpose is honoured only when the caller has been vouched for; otherwise this raises
    rather than silently downgrading, because a harness that believes it created disposable data and
    actually created production data is the worse failure of the two.
    """
    if requested is None or (isinstance(requested, str) and not requested.strip()):
        return PURPOSE_PRODUCTION
    if not isinstance(requested, str):
        raise PurposeNotPermitted("run_purpose must be a string")
    wanted = normalise_purpose(requested)
    if wanted == PURPOSE_PRODUCTION:
        return PURPOSE_PRODUCTION
    if wanted == PURPOSE_UNCLASSIFIED:
        raise PurposeNotPermitted(
            "run_purpose must be one of: " + ", ".join(sorted(DECLARABLE_PURPOSES)))
    if not allow_test:
        raise PurposeNotPermitted(
            f"run_purpose={wanted!r} needs a server started with {TEST_PURPOSE_ENV}=1; "
            "a request cannot mark its own data disposable")
    return wanted


class RunPurposeIndex:
    """What every run on disk was for, read once.

    Two sources, in order: the purpose the run itself declared at launch, then the operator's later
    decision about a run that declared nothing. Both are read-only here — recording a decision
    belongs to Data management.
    """

    def __init__(self, output_dir: str = "outputs") -> None:
        self._root = Path(output_dir) / "scout"
        self._overlay: Optional[Dict[str, str]] = None
        self._cache: Dict[str, str] = {}
        self._operator_state: Optional[Dict[str, Any]] = None

    # -- one run ---------------------------------------------------------------------------------

    def purpose_of(self, run_id: str) -> str:
        key = str(run_id or "").strip()
        if not key:
            return PURPOSE_UNCLASSIFIED
        if key not in self._cache:
            self._cache[key] = self._read(key)
        return self._cache[key]

    def _read(self, run_id: str) -> str:
        try:
            raw = json.loads((self._root / run_id / "config.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        declared = normalise_purpose((raw or {}).get("run_purpose"))
        if declared != PURPOSE_UNCLASSIFIED:
            return declared
        return normalise_purpose(self._overlay_purposes().get(run_id))

    def _overlay_purposes(self) -> Dict[str, str]:
        """The operator's recorded decisions, INCLUDING about runs that no longer exist.

        A deleted run leaves its sites behind in History. Reading its purpose from the tombstone is
        what keeps those sites classified: without it, deleting an acceptance run would quietly
        promote its companies into production history — the run's own cleanup undoing the isolation
        the run was created with.
        """
        if self._overlay is None:
            overlay: Dict[str, str] = {}
            state = self._read_operator_state()
            for record in state.get("tombstones") or []:
                if isinstance(record, dict) and record.get("run_id") and record.get("purpose"):
                    overlay[str(record["run_id"])] = str(record["purpose"])
            # A live decision outranks a tombstone if both somehow exist.
            for run_id, decided in (state.get("classified") or {}).items():
                if isinstance(decided, dict) and decided.get("purpose"):
                    overlay[str(run_id)] = str(decided["purpose"])
            self._overlay = overlay
        return self._overlay

    def _read_operator_state(self) -> Dict[str, Any]:
        if self._operator_state is None:
            try:
                raw = json.loads(
                    (self._root / "_operator" / _OPERATOR_STATE_NAME).read_text(encoding="utf-8"))
                self._operator_state = raw if isinstance(raw, dict) else {}
            except (OSError, ValueError):
                self._operator_state = {}
        return self._operator_state

    # -- a set of runs ---------------------------------------------------------------------------

    def purposes_of(self, run_ids: Iterable[str]) -> Set[str]:
        return {self.purpose_of(r) for r in (run_ids or []) if str(r or "").strip()}

    def is_production_visible(self, run_ids: Iterable[str]) -> bool:
        """Does this site belong in the operator's production view?

        Yes unless every run behind it was deliberately disposable. A site with no recorded run at
        all stays visible: unknown provenance is treated as real work, never swept out of sight.
        """
        purposes = self.purposes_of(run_ids)
        if not purposes:
            return True
        return not purposes <= REMOVABLE_PURPOSES

    def matches_filter(self, run_ids: Iterable[str], wanted: str) -> bool:
        """Apply an explicit purpose filter to one site's runs.

        ``production`` (the default view) keeps anything not exclusively disposable; ``all`` keeps
        everything; a named test purpose keeps sites that have at least one run of it.
        """
        selector = str(wanted or "").strip().lower().replace("-", "_")
        if selector in ("", PURPOSE_PRODUCTION):
            return self.is_production_visible(run_ids)
        if selector == "all":
            return True
        if selector not in KNOWN_PURPOSES:
            return self.is_production_visible(run_ids)
        return selector in self.purposes_of(run_ids)


def purpose_label(purpose: str) -> str:
    return PURPOSE_LABELS.get(normalise_purpose(purpose), PURPOSE_LABELS[PURPOSE_UNCLASSIFIED])

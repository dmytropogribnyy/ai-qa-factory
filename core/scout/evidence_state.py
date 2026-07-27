"""Why a piece of evidence is not there — because "not there" has four different meanings.

"0 captured", "Not available", "—" and an empty cell all read the same to an operator: as though
something were still running. They are not the same thing at all, and the difference decides what to
do next:

- **Available** — it exists and can be opened. Zero axe violations is *available* evidence of a clean
  result, not absent evidence; reporting it as missing would invert the finding.
- **Not applicable** — it was never in scope. A static scan opens no browser, so a screenshot did not
  fail to happen; it was never going to.
- **Not captured: reason** — it was in scope and the policy decided against it. Nothing safe
  reproduced cleanly, so no video was kept. An honest outcome, not a fault.
- **Capture failed: reason** — it was in scope, we tried, and we failed. The browser opened and
  axe-core still did not run. This is the only one of the four that is a defect in us, and it is the
  only one that should ever prompt a re-run.

Whether a run was deep or static is read from ``axe_status``, which the engine writes as "" when the
static backend never attempted it, "ok" when axe ran (violations may be empty) and "unavailable" when
deep capture ran but axe itself could not. That is the existing persisted signal — this module reads
it rather than inventing a second notion of scan depth that could disagree with the first.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

AVAILABLE = "available"
NOT_APPLICABLE = "not_applicable"
NOT_CAPTURED = "not_captured"
CAPTURE_FAILED = "capture_failed"

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_VIDEO_SUFFIXES = (".webm", ".mp4")

_STATIC_SCAN = "a static scan was used, which does not open a browser"


@dataclass
class EvidenceState:
    kind: str           # screenshots | video | accessibility | performance | network | trace
    title: str          # what an operator calls it
    state: str
    reason: str         # "" when available or simply out of scope
    count: int = 0

    @property
    def label(self) -> str:
        if self.state == AVAILABLE:
            return "Available"
        if self.state == NOT_APPLICABLE:
            return f"Not applicable — {self.reason}" if self.reason else "Not applicable"
        prefix = "Not captured" if self.state == NOT_CAPTURED else "Capture failed"
        return f"{prefix}: {self.reason}"

    @property
    def is_available(self) -> bool:
        return self.state == AVAILABLE

    def to_dict(self) -> Dict[str, Any]:
        return {**self.__dict__, "label": self.label}


def _deep_capture_ran(detail: Dict[str, Any]) -> bool:
    """Did a real browser open for this target? Read from what the run persisted, never assumed."""
    network = detail.get("network") or {}
    if str(network.get("axe_status") or ""):
        return True
    # A static scan cannot produce an image, so any captured frame is itself proof a browser ran.
    return any(str(m).lower().endswith(_IMAGE_SUFFIXES) for m in (detail.get("media") or []))


def evidence_states(detail: Dict[str, Any]) -> List[EvidenceState]:
    """One state per evidence kind for a target, each carrying its own reason."""
    detail = detail or {}
    media = [str(m) for m in (detail.get("media") or [])]
    network = detail.get("network") or {}
    files = {str(f.get("name") or "") for f in (detail.get("evidence_files") or [])}
    deep = _deep_capture_ran(detail)
    shots = [m for m in media if m.lower().endswith(_IMAGE_SUFFIXES)]
    videos = [m for m in media if m.lower().endswith(_VIDEO_SUFFIXES)]
    states: List[EvidenceState] = []

    # Screenshots
    if shots:
        states.append(EvidenceState("screenshots", "Screenshots", AVAILABLE, "", len(shots)))
    elif not deep:
        states.append(EvidenceState("screenshots", "Screenshots", NOT_APPLICABLE, _STATIC_SCAN))
    else:
        states.append(EvidenceState("screenshots", "Screenshots", CAPTURE_FAILED,
                                    "the browser ran but no frame was written"))

    # Video — decided by the run's recording policy, which is persisted per run.
    video_mode = str(detail.get("video_mode") or "")
    if videos:
        states.append(EvidenceState("video", "Reproduction video", AVAILABLE, "", len(videos)))
    elif video_mode == "off":
        states.append(EvidenceState("video", "Reproduction video", NOT_APPLICABLE,
                                    "video capture was disabled for this run"))
    elif video_mode == "manual":
        states.append(EvidenceState("video", "Reproduction video", NOT_APPLICABLE,
                                    "video is recorded only during an operator-run reproduction"))
    elif video_mode == "qualified_auto":
        states.append(EvidenceState("video", "Reproduction video", NOT_CAPTURED,
                                    "no safe interaction reproduced cleanly, so no clip was kept"))
    else:
        states.append(EvidenceState("video", "Reproduction video", NOT_CAPTURED,
                                    "the video policy was not recorded for this run"))

    # Accessibility — the one kind whose absence can genuinely be our fault.
    axe_status = str(network.get("axe_status") or "")
    if axe_status == "ok":
        states.append(EvidenceState("accessibility", "Accessibility (axe-core)", AVAILABLE, "",
                                    len(network.get("axe_violations") or [])))
    elif axe_status == "unavailable":
        states.append(EvidenceState("accessibility", "Accessibility (axe-core)", CAPTURE_FAILED,
                                    "the browser ran but axe-core could not be injected"))
    else:
        states.append(EvidenceState("accessibility", "Accessibility (axe-core)", NOT_APPLICABLE,
                                    _STATIC_SCAN))

    # Performance timings
    perf = network.get("perf") or {}
    timing = network.get("timing_ms") or {}
    if perf or timing:
        states.append(EvidenceState("performance", "Performance timings", AVAILABLE, "",
                                    len(perf) or len(timing)))
    elif not deep:
        states.append(EvidenceState("performance", "Performance timings", NOT_APPLICABLE,
                                    _STATIC_SCAN))
    else:
        states.append(EvidenceState("performance", "Performance timings", NOT_CAPTURED,
                                    "the page finished before timing data was collected"))

    # Console / network
    console = network.get("console_errors") or []
    failed = network.get("failed_resources") or []
    if console or failed or network.get("status"):
        states.append(EvidenceState("network", "Console and network", AVAILABLE, "",
                                    len(console) + len(failed)))
    elif not deep:
        states.append(EvidenceState("network", "Console and network", NOT_APPLICABLE, _STATIC_SCAN))
    else:
        states.append(EvidenceState("network", "Console and network", NOT_CAPTURED,
                                    "no console or network event was recorded for this page"))

    # Structured browser event trace
    if "browser_trace.json" in files:
        states.append(EvidenceState("trace", "Browser event trace", AVAILABLE, "", 1))
    elif not deep:
        states.append(EvidenceState("trace", "Browser event trace", NOT_APPLICABLE, _STATIC_SCAN))
    else:
        states.append(EvidenceState("trace", "Browser event trace", NOT_CAPTURED,
                                    "no browser interaction sequence ran for this target"))
    return states

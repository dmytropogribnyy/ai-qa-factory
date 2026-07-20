"""Structured bug-reproduction context + result (v3.3, concept §8/§9).

Per finding, Scout persists enough structured context to safely return later (Recheck / Reproduce /
Record short video / Capture stronger evidence). This module defines that record and the honest
reproduction-result states. It never records a video and never fabricates evidence — a
`ReproResult` marked anything other than REPRODUCED must carry no video, and a non-verified cleanup
marks the result unsafe/non-client-safe.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# Reproduction outcome states (honest).
REPRO_REPRODUCED = "reproduced"
REPRO_NOT = "not_reproduced"
REPRO_CHANGED = "changed"
REPRO_BLOCKED = "blocked"
REPRO_UNSAFE = "unsafe"
REPRO_STATES = frozenset({REPRO_REPRODUCED, REPRO_NOT, REPRO_CHANGED, REPRO_BLOCKED, REPRO_UNSAFE})

CONFIDENCE = ("low", "medium", "high")


class ReproError(ValueError):
    """Raised for an inconsistent reproduction record (e.g. a video on a non-reproduced result)."""


@dataclass
class ReproContext:
    finding_id: str
    target_url: str
    permitted_scope: List[str] = field(default_factory=list)   # allowed navigation scope
    precondition_state: str = ""                               # clean starting state
    steps: List[str] = field(default_factory=list)             # exact browser steps
    selectors: List[str] = field(default_factory=list)         # resilient selectors / semantic desc
    expected: str = ""
    actual: str = ""
    stop_boundary: str = ""                                    # irreversible boundary to stop before
    cleanup_required: bool = False
    prior_evidence: List[str] = field(default_factory=list)    # screenshots/trace/console/network refs
    repro_confidence: str = "low"

    def __post_init__(self) -> None:
        if self.repro_confidence not in CONFIDENCE:
            raise ReproError(f"unknown repro_confidence: {self.repro_confidence!r}")

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "ReproContext":
        known = set(cls(finding_id="", target_url="").__dict__)
        return cls(**{k: v for k, v in (d or {}).items() if k in known})


@dataclass
class ReproResult:
    finding_id: str
    outcome: str
    cleanup_verified: bool = True
    evidence_refs: List[str] = field(default_factory=list)
    video_ref: str = ""
    note: str = ""

    def __post_init__(self) -> None:
        if self.outcome not in REPRO_STATES:
            raise ReproError(f"unknown outcome: {self.outcome!r}")
        # Never fabricate: a video may only accompany a genuinely REPRODUCED result.
        if self.video_ref and self.outcome != REPRO_REPRODUCED:
            raise ReproError("a video_ref is only valid when outcome == reproduced (never fabricate)")

    @property
    def is_client_safe_capable(self) -> bool:
        """A result can back client-safe evidence only when reproduced AND cleanup verified."""
        return self.outcome == REPRO_REPRODUCED and self.cleanup_verified

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["is_client_safe_capable"] = self.is_client_safe_capable
        return d


def build_repro_context(*, finding: Dict[str, Any], target_url: str, permitted_scope: List[str],
                        stop_boundary: str = "", cleanup_required: bool = False) -> ReproContext:
    """Build a reproduction context from a finding dict + the target's permitted scope + boundary."""
    return ReproContext(
        finding_id=str(finding.get("finding_id", "")), target_url=target_url,
        permitted_scope=list(permitted_scope),
        precondition_state=str(finding.get("precondition", "clean public page")),
        steps=list(finding.get("reproduction_steps", [])),
        selectors=list(finding.get("selectors", [])),
        expected=str(finding.get("expected", "")), actual=str(finding.get("actual", "")),
        stop_boundary=stop_boundary, cleanup_required=cleanup_required,
        prior_evidence=list(finding.get("evidence_refs", []) or finding.get("evidence_ids", [])),
        repro_confidence=str(finding.get("confidence", "low")))

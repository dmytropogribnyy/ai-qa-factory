"""Execution-lifecycle contract schema (v3.0.0 Milestone 7).

Factory genuinely orchestrates and PERSISTS the client-work lifecycle: approval -> execution started
-> progress/blockers -> produced artifacts -> evidence registration -> validation -> delivery
package -> resume. An Executor is pluggable: real client work is Claude-Code-driven and
human-approved (Factory records what was produced); deterministic acceptance FIXTURE executors drive
the same contract in CI (clearly flagged as acceptance fixtures, never a production autonomous
agent). No LLM/network is required by this schema.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class ExecutionArtifact:
    filename: str
    kind: str = "artifact"        # framework | test | report | fix | api_tests | ...
    relative_path: str = ""       # path relative to the project workspace

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class EvidenceItem:
    evidence_id: str
    kind: str = "artifact"        # screenshot | trace | log | test_output | diff | report
    relative_path: str = ""
    description: str = ""
    created_at: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class ExecutionOutcome:
    """What an Executor produced during EXECUTION (recorded by Factory)."""
    artifacts: List[ExecutionArtifact] = field(default_factory=list)
    evidence: List[EvidenceItem] = field(default_factory=list)
    files_changed: List[str] = field(default_factory=list)
    progress_notes: List[str] = field(default_factory=list)
    blockers: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"artifacts": [a.to_dict() for a in self.artifacts],
                "evidence": [e.to_dict() for e in self.evidence],
                "files_changed": list(self.files_changed),
                "progress_notes": list(self.progress_notes), "blockers": list(self.blockers)}


@dataclass
class ValidationOutcome:
    """What VALIDATION found (recorded by Factory).

    ``evidence`` (v3.0.2 M2) carries validation-produced evidence items (e.g. the captured
    stdout/stderr + provenance metadata of a validation command run). The service registers
    them in EVIDENCE_INDEX.json and includes them in the validated integrity snapshot.
    """
    passed: bool = False
    tests_run: int = 0
    tests_passed: int = 0
    failures: List[str] = field(default_factory=list)
    report: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    evidence: List[EvidenceItem] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["evidence"] = [e.to_dict() for e in self.evidence]
        return d


@dataclass
class ExecutionContext:
    """Handed to the Executor: the persisted workspace + profile + requirements."""
    project_id: str
    profile: str
    workspace_dir: str
    requirements: List[str] = field(default_factory=list)
    now: str = ""

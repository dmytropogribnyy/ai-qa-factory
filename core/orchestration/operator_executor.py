"""OperatorWorkspaceExecutor (v3.0.0 Milestone 7d) - the REAL Claude-Code-driven execution path.

This is the bridge between "a human/Claude-Code operator produced deliverables in the workspace" and
"the Factory persists the execution lifecycle". Unlike the CI acceptance FIXTURES (which are flagged
``is_acceptance_fixture=True`` and fabricate their own content), this executor fabricates nothing: it
registers the files an operator actually wrote and runs a declared, REAL validation over them. It is
NOT an autonomous coding agent and never claims one ran - the operator (a real Claude Code session or
a person) did the work; the Factory records, validates, and persists it.

Contract match with ``WorkExecutionService``: ``execute(ctx) -> ExecutionOutcome`` and
``validate(ctx) -> ValidationOutcome``. ``is_acceptance_fixture`` is ``False``.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional

from core.schemas.work_execution import (
    EvidenceItem,
    ExecutionArtifact,
    ExecutionContext,
    ExecutionOutcome,
    ValidationOutcome,
)


@dataclass
class ProducedArtifact:
    """A deliverable the operator authored in the workspace (path relative to it)."""
    relative_path: str
    kind: str = "artifact"           # framework | test | report | fix | api_tests | ...
    is_evidence: bool = False
    evidence_kind: str = "artifact"  # screenshot | trace | log | test_output | diff | report
    description: str = ""


# A validator runs a REAL check over the produced workspace and returns the outcome.
Validator = Callable[[ExecutionContext], ValidationOutcome]


class OperatorWorkspaceExecutor:
    """Records operator/Claude-Code-authored artifacts and runs a real validation over them."""

    is_acceptance_fixture = False

    def __init__(self, produced: List[ProducedArtifact], validator: Validator,
                 executor_id: str = "operator:claude-code",
                 progress_notes: Optional[List[str]] = None) -> None:
        self._produced = list(produced)
        self._validator = validator
        self.executor_id = executor_id
        self._notes = list(progress_notes or [])

    def execute(self, ctx: ExecutionContext) -> ExecutionOutcome:
        ws = Path(ctx.workspace_dir)
        artifacts: List[ExecutionArtifact] = []
        evidence: List[EvidenceItem] = []
        blockers: List[str] = []
        for pa in self._produced:
            if not (ws / pa.relative_path).exists():
                blockers.append(f"declared artifact missing: {pa.relative_path}")
                continue
            artifacts.append(ExecutionArtifact(pa.relative_path, pa.kind))
            if pa.is_evidence:
                evidence.append(EvidenceItem(f"ev-{len(evidence) + 1}", pa.evidence_kind,
                                             pa.relative_path, pa.description, ctx.now))
        notes = self._notes or [f"recorded {len(artifacts)} operator-authored artifact(s)"]
        return ExecutionOutcome(artifacts=artifacts, evidence=evidence,
                                files_changed=[a.filename for a in artifacts],
                                progress_notes=notes, blockers=blockers)

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        return self._validator(ctx)

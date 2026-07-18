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

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Sequence, Union

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
    """Records operator/Claude-Code-authored artifacts and runs a real validation over them.

    ``validator`` is optional: the CLI records execution and validates in two separate steps, so an
    execute-only executor carries no validator and raises if ``validate`` is called on it directly.
    """

    is_acceptance_fixture = False

    def __init__(self, produced: List[ProducedArtifact], validator: Optional[Validator] = None,
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
        if self._validator is None:
            raise ValueError("this executor records execution only; validate via a validator")
        return self._validator(ctx)


class CommandValidationExecutor:
    """Runs an operator-specified validation command INSIDE the project workspace and records the
    result + captured output as evidence.

    The command is the operator's own (e.g. ``pytest -q`` or ``npx playwright test``). It is not
    remote or model-authored code: it runs locally, under the operator's account, only when they
    invoke ``client-work validate``. It is executed with ``shell=False`` (no shell interpolation),
    with a timeout, confined to the workspace as the working directory.
    """

    is_acceptance_fixture = False

    def __init__(self, command: Union[str, Sequence[str]], executor_id: str = "operator:validate",
                 timeout_s: int = 900) -> None:
        # Tokenize like a POSIX shell (quotes stripped) so `-c "code"` and quoted args work; on
        # Windows the operator should use forward slashes in paths (backslash is the escape char).
        self._argv: List[str] = (list(command) if not isinstance(command, str)
                                 else shlex.split(command))
        self._display = command if isinstance(command, str) else " ".join(command)
        self.executor_id = executor_id
        self._timeout = timeout_s

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        if not self._argv:
            return ValidationOutcome(passed=False, failures=["empty validation command"],
                                     report="no command given")
        try:
            proc = subprocess.run(self._argv, cwd=ctx.workspace_dir, capture_output=True,  # noqa: S603
                                  text=True, timeout=self._timeout, check=False)
            rc, out = proc.returncode, (proc.stdout or "") + "\n" + (proc.stderr or "")
        except (OSError, subprocess.TimeoutExpired) as exc:
            rc, out = -1, f"{type(exc).__name__}: {exc}"
        ev = Path(ctx.workspace_dir) / "evidence"
        ev.mkdir(parents=True, exist_ok=True)
        (ev / "validation_output.txt").write_text(
            f"$ {self._display}\n(exit {rc})\n\n{out[-16000:]}", encoding="utf-8")
        passed = rc == 0
        return ValidationOutcome(
            passed=passed, tests_run=1, tests_passed=1 if passed else 0,
            failures=[] if passed else [f"command exited {rc}"],
            report=f"ran `{self._display}` in the workspace (exit {rc}); output in "
                   "evidence/validation_output.txt", details={"returncode": rc})

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


class ValidationCommandError(ValueError):
    """A validation command that violates the structured-argv contract."""


# Bounds for a structured validation command (v3.0.2 M3): a small, local operator command.
_MAX_ARGS = 64
_MAX_ARG_CHARS = 4096
_MAX_TOTAL_CHARS = 32768
_MAX_TIMEOUT_S = 3600
_OUTPUT_TAIL_CHARS = 16000


class CommandValidationExecutor:
    """Runs an operator-specified validation command INSIDE the project workspace and records
    each attempt as separate, registered evidence (v3.0.2 M2).

    The command is the operator's own (e.g. ``pytest -q`` or ``npx playwright test``). It is not
    remote or model-authored code: it runs locally, under the operator's account, only when they
    invoke ``client-work validate``. It is executed with ``shell=False`` (no shell interpolation),
    with a bounded timeout, confined to the workspace as the working directory. Every attempt gets
    a stable validation id and its own ``evidence/validation/<id>/`` directory (metadata.json +
    stdout.txt + stderr.txt) - later attempts never overwrite earlier evidence. Output is bounded
    (tail-truncated) and truncation is recorded honestly. No environment dump, credential, or
    token is ever persisted.
    """

    is_acceptance_fixture = False

    def __init__(self, command: Union[str, Sequence[str]], executor_id: str = "operator:validate",
                 timeout_s: int = 900) -> None:
        # Preferred: a structured argv (list of strings) - unambiguous on Windows and the future
        # Dashboard contract. A plain string remains a documented CLI convenience, tokenized like
        # a POSIX shell (quotes stripped); on Windows prefer the structured form for paths.
        if isinstance(command, str):
            argv = shlex.split(command)
        else:
            argv = [str(a) for a in command]
        self._check_argv(argv)
        self._argv: List[str] = argv
        # Redact likely secret-bearing arguments before they are ever persisted as evidence
        # (metadata/display) - reusing the single intake redactor. The real argv still runs.
        from core.orchestration.content_safety import redact_intake_text
        self._safe_argv: List[str] = [redact_intake_text(a).text for a in argv]
        self._display = " ".join(self._safe_argv)
        self.executor_id = executor_id
        self._timeout = max(1, min(int(timeout_s), _MAX_TIMEOUT_S))

    @staticmethod
    def _check_argv(argv: List[str]) -> None:
        if not argv:
            raise ValidationCommandError("validation command is empty")
        if len(argv) > _MAX_ARGS:
            raise ValidationCommandError(f"validation command has too many arguments "
                                         f"({len(argv)} > {_MAX_ARGS})")
        total = 0
        for a in argv:
            if not a:
                raise ValidationCommandError("validation command contains an empty argument")
            if len(a) > _MAX_ARG_CHARS:
                raise ValidationCommandError(f"a validation argument exceeds {_MAX_ARG_CHARS} chars")
            total += len(a)
        if total > _MAX_TOTAL_CHARS:
            raise ValidationCommandError(f"validation command exceeds {_MAX_TOTAL_CHARS} chars total")

    @staticmethod
    def _next_validation_id(ws: Path) -> str:
        base = ws / "evidence" / "validation"
        n = 1
        while (base / f"val-{n:04d}").exists():
            n += 1
        return f"val-{n:04d}"

    @staticmethod
    def _decode(data: object) -> str:
        if data is None:
            return ""
        if isinstance(data, bytes):
            return data.decode("utf-8", errors="replace")
        return str(data)

    @staticmethod
    def _write_bounded(path: Path, header: str, body: str) -> bool:
        truncated = len(body) > _OUTPUT_TAIL_CHARS
        tail = body[-_OUTPUT_TAIL_CHARS:]
        note = "[output truncated: only the tail is kept]\n" if truncated else ""
        path.write_text(f"{header}\n{note}{tail}", encoding="utf-8")
        return truncated

    @staticmethod
    def _sha256(path: Path) -> str:
        import hashlib
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        from datetime import datetime, timezone
        ws = Path(ctx.workspace_dir)
        vid = self._next_validation_id(ws)
        vdir = ws / "evidence" / "validation" / vid
        vdir.mkdir(parents=True, exist_ok=True)
        started = datetime.now(timezone.utc).isoformat()
        timed_out, spawn_error = False, ""
        rc: Union[int, None] = None
        out, err = "", ""
        try:
            proc = subprocess.run(self._argv, cwd=str(ws), capture_output=True,  # noqa: S603
                                  text=True, timeout=self._timeout, check=False)
            rc, out, err = proc.returncode, self._decode(proc.stdout), self._decode(proc.stderr)
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            out, err = self._decode(exc.stdout), self._decode(exc.stderr)
        except OSError as exc:
            spawn_error = f"{type(exc).__name__}: {exc}"
        finished = datetime.now(timezone.utc).isoformat()
        out_trunc = self._write_bounded(vdir / "stdout.txt", f"$ {self._display}", out)
        err_trunc = self._write_bounded(vdir / "stderr.txt", f"$ {self._display}", err)
        rel = f"evidence/validation/{vid}"
        passed = rc == 0
        metadata = {
            "validation_id": vid, "project_id": ctx.project_id, "executor_id": self.executor_id,
            "argv": list(self._safe_argv), "cwd": ".", "cwd_confined_to_workspace": True,
            "started_at": started, "finished_at": finished, "timeout_s": self._timeout,
            "exit_code": rc, "timed_out": timed_out, "spawn_error": spawn_error, "passed": passed,
            "stdout": {"path": f"{rel}/stdout.txt", "truncated": out_trunc,
                       "sha256": self._sha256(vdir / "stdout.txt")},
            "stderr": {"path": f"{rel}/stderr.txt", "truncated": err_trunc,
                       "sha256": self._sha256(vdir / "stderr.txt")},
            "note": "validation-attempt provenance; no environment variables are persisted",
        }
        import json as _json
        (vdir / "metadata.json").write_text(_json.dumps(metadata, indent=2, sort_keys=True),
                                            encoding="utf-8")
        evidence = [
            EvidenceItem(f"{vid}-metadata", "log", f"{rel}/metadata.json",
                         "validation attempt provenance", ctx.now),
            EvidenceItem(f"{vid}-stdout", "test_output", f"{rel}/stdout.txt",
                         "validation command stdout (bounded)", ctx.now),
            EvidenceItem(f"{vid}-stderr", "test_output", f"{rel}/stderr.txt",
                         "validation command stderr (bounded)", ctx.now),
        ]
        if timed_out:
            failure = f"command timed out after {self._timeout}s"
        elif spawn_error:
            failure = f"command could not start: {spawn_error}"
        else:
            failure = f"command exited {rc}"
        return ValidationOutcome(
            passed=passed, tests_run=1, tests_passed=1 if passed else 0,
            failures=[] if passed else [failure],
            report=f"ran `{self._display}` in the workspace (exit {rc}, timed_out={timed_out}); "
                   f"evidence in {rel}/",
            details={"returncode": rc, "validation_id": vid, "timed_out": timed_out,
                     "evidence_dir": rel},
            evidence=evidence)

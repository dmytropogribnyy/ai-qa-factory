"""v3.2 P0-D (integrated) - ONE multi-file TypeScript/Playwright project through the PRODUCTION
lifecycle with REAL `playwright test` validation.

A cross-file defect (a helper module `tests/util.ts` returns the wrong expected title, imported by
`tests/home.spec.ts`) makes the real Playwright run fail; a deterministic, labelled fixture worker
(no paid provider call in CI) repairs it across the operator-triggered resume. Integrity:

- EVERY authored project file — including `package.json` — is tracked in files_changed / artifacts /
  hashes / the delivery manifest;
- the failing-before AND passing-after Playwright runs are preserved in UNIQUE append-only
  `evidence/validation/<id>/` directories (neither overwrites the other);
- the Playwright subprocess runs with the CREDENTIAL-STRIPPED environment (like the production
  validation executor), not the raw process environment.

Drives the real WorkExecutionService: approve -> execute -> failing-before validation -> REPAIR_REQUIRED
-> resume/repair -> passing-after -> review -> prepared delivery (multi-file manifest + per-file hash)
-> fresh-process resume + mark-delivered re-hash. Browser-acceptance job (npm runtime provisioned).
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright not installed")

from core.orchestration.client_work import ClientWorkService  # noqa: E402
from core.orchestration.execution_trust import stripped_subprocess_env  # noqa: E402
from core.orchestration.providers import FixedClock, SequentialIds  # noqa: E402
from core.orchestration.work_execution import WorkExecutionService  # noqa: E402
from core.schemas.work_execution import (  # noqa: E402
    EvidenceItem,
    ExecutionArtifact,
    ExecutionContext,
    ExecutionOutcome,
    ValidationOutcome,
)
from tests.test_v3_genuine_execution_ab import _CONFIG_TS, _counts  # noqa: E402

_RUNTIME = os.environ.get("PLAYWRIGHT_TEST_RUNTIME")
pytestmark = [
    pytest.mark.playwright_acceptance,   # selected by the browser-acceptance job (runtime provisioned)
    pytest.mark.skipif(
        not (_RUNTIME and (Path(_RUNTIME) / "node_modules" / "@playwright" / "test").exists()),
        reason="npm @playwright/test runtime not provisioned (set PLAYWRIGHT_TEST_RUNTIME)"),
]

_SPEC = (
    'import { test, expect } from "@playwright/test";\n'
    'import { expectedTitle } from "./util";\n'
    'test("home has the expected title", async ({ page }) => {\n'
    '  await page.goto("/");\n'
    '  await expect(page).toHaveTitle(expectedTitle());\n});\n')
_UTIL_WRONG = 'export function expectedTitle(): string {\n  return "WRONG TITLE";\n}\n'
_UTIL_RIGHT = 'export function expectedTitle(): string {\n  return "QA Home";\n}\n'
# Every authored deliverable, INCLUDING package.json, is tracked/hashed/delivered.
_PROJECT_FILES = ["package.json", "playwright.config.ts", "tests/home.spec.ts", "tests/util.ts"]


class _TsProjectWorker:
    """A deterministic, labelled fixture worker (executes no untrusted client code). It authors/repairs
    the multi-file TS project and declares the FULL project (all _PROJECT_FILES) as the deliverable."""
    is_acceptance_fixture = True
    executes_client_code = False
    executor_id = "worker:fixture-ts"

    def __init__(self, util: str, *, scaffold: bool) -> None:
        self._util = util
        self._scaffold = scaffold

    def execute(self, ctx: ExecutionContext) -> ExecutionOutcome:
        ws = Path(ctx.workspace_dir)
        (ws / "tests").mkdir(parents=True, exist_ok=True)
        changed = ["tests/util.ts"]
        (ws / "tests" / "util.ts").write_text(self._util, encoding="utf-8")
        if self._scaffold:
            (ws / "playwright.config.ts").write_text(_CONFIG_TS, encoding="utf-8")
            (ws / "tests" / "home.spec.ts").write_text(_SPEC, encoding="utf-8")
            (ws / "package.json").write_text(json.dumps(
                {"name": "qa-golden", "version": "1.0.0",
                 "scripts": {"test": "playwright test"}}, indent=2), encoding="utf-8")
            nm = ws / "node_modules"
            if not nm.exists():
                os.symlink(Path(_RUNTIME) / "node_modules", nm, target_is_directory=True)
            changed = list(_PROJECT_FILES)
        artifacts = [ExecutionArtifact(f, "test" if f.endswith(".ts") else "framework")
                     for f in _PROJECT_FILES]
        return ExecutionOutcome(artifacts=artifacts, evidence=[], files_changed=changed,
                                progress_notes=[f"authored/repaired {len(changed)} project file(s)"])

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:  # pragma: no cover
        raise ValueError("validate via the Playwright validator")


def _next_vid(ws: Path) -> str:
    base = ws / "evidence" / "validation"
    n = 1
    while (base / f"pw-{n:04d}").exists():
        n += 1
    return f"pw-{n:04d}"


class _PlaywrightValidator:
    """Runs the REAL `playwright test` binary (client code) with the CREDENTIAL-STRIPPED environment,
    writing each attempt to a UNIQUE append-only evidence/validation/<id>/ directory."""
    is_acceptance_fixture = False
    executes_client_code = True
    executor_id = "operator:playwright-validate"

    def __init__(self, url: str) -> None:
        self._url = url

    def execute(self, ctx: ExecutionContext) -> ExecutionOutcome:  # pragma: no cover
        raise ValueError("validator only")

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        from core.orchestration.content_safety import redact_intake_text
        ws = Path(ctx.workspace_dir)
        vid = _next_vid(ws)
        vdir = ws / "evidence" / "validation" / vid
        vdir.mkdir(parents=True, exist_ok=True)
        bin_name = "playwright.cmd" if os.name == "nt" else "playwright"
        pw = ws / "node_modules" / ".bin" / bin_name
        # Credential-stripped env (production path) + only the non-secret runtime knobs Playwright needs.
        env = stripped_subprocess_env()
        env.update({"FIXTURE_URL": self._url, "CI": "1"})
        proc = subprocess.run([str(pw), "test", "--reporter=json"],  # noqa: S603
                              cwd=str(ws), env=env, capture_output=True, text=True, timeout=180,
                              check=False)
        out = redact_intake_text(proc.stdout or "").text[-16000:]
        (vdir / "stdout.txt").write_text(out, encoding="utf-8")
        report = {}
        start = (proc.stdout or "").find("{")
        if start != -1:
            try:
                report = json.loads(proc.stdout[start:])
            except ValueError:
                report = {}
        total, passed, failed = _counts(report)
        ok = proc.returncode == 0 and total >= 1 and failed == 0
        (vdir / "metadata.json").write_text(json.dumps(
            {"attempt": vid, "exit_code": proc.returncode, "total": total, "passed": passed,
             "failed": failed, "credential_stripped_env": True}, indent=2, sort_keys=True),
            encoding="utf-8")
        rel = f"evidence/validation/{vid}"
        return ValidationOutcome(
            passed=ok, tests_run=total, tests_passed=passed,
            failures=[] if ok else [f"playwright test exit {proc.returncode}, {failed} failed"],
            report=f"real `playwright test` exit {proc.returncode} ({passed}/{total} passed) [{vid}]",
            evidence=[EvidenceItem(f"{vid}-stdout", "test_output", f"{rel}/stdout.txt",
                                   "real playwright stdout (redacted, stripped env)", ctx.now),
                      EvidenceItem(f"{vid}-meta", "log", f"{rel}/metadata.json",
                                   "playwright attempt metadata", ctx.now)])


def test_integrated_ts_playwright_golden_lifecycle(tmp_path):
    from tests.test_v3_genuine_execution_ab import _serve
    pid = "pw-golden"
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Build and fix a multi-file Playwright + TypeScript suite so the title assertion passes.", pid)
    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    svc.approve(pid, reviewer="operator")

    with _serve("<!doctype html><html lang='en'><head><meta charset='utf-8'><title>QA Home</title>"
                "</head><body><main><h1>Welcome</h1></main></body></html>") as url:
        state, out1 = svc.execute(pid, _TsProjectWorker(_UTIL_WRONG, scaffold=True))
        assert state.status == "VERIFYING" and set(_PROJECT_FILES) <= set(out1.files_changed)

        state, res1 = svc.validate(pid, _PlaywrightValidator(url))     # failing-before (pw-0001)
        assert not res1.passed and state.status == "REPAIR_REQUIRED", res1.report

        state, _ = svc.execute(pid, _TsProjectWorker(_UTIL_RIGHT, scaffold=False))
        assert state.status == "VERIFYING"

        state, res2 = svc.validate(pid, _PlaywrightValidator(url))     # passing-after (pw-0002)
        assert res2.passed and state.status == "READY_FOR_REVIEW", res2.report

    svc.review(pid, reviewer="operator", approved=True)
    manifest = svc.prepare_delivery(pid)
    assert svc.status(pid).status == "DELIVERY_PREPARED"

    # Every authored file (incl package.json) is delivered + hashed.
    for f in _PROJECT_FILES:
        assert f in manifest["included"]["artifacts"] and f in manifest["artifact_hashes"], f
    # BOTH the failing-before and passing-after attempts are preserved + hashed (unique dirs).
    hashed = set(manifest["artifact_hashes"])
    assert "evidence/validation/pw-0001/stdout.txt" in hashed          # fail-before, not overwritten
    assert "evidence/validation/pw-0002/stdout.txt" in hashed          # pass-after
    assert manifest["manifest_digest"].startswith("sha256:")

    # Fresh-process resume: both attempts + all files still present and re-verified.
    fresh = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    assert fresh.resume(pid).status == "DELIVERY_PREPARED"
    ws = tmp_path / pid / "40_ark_work"
    assert (ws / "evidence" / "validation" / "pw-0001" / "stdout.txt").is_file()
    assert (ws / "evidence" / "validation" / "pw-0002" / "stdout.txt").is_file()
    assert fresh.mark_delivered(pid, note="operator sent the package").status == "COMPLETED"

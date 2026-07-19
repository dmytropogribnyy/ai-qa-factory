"""v3.2 P0-D (integrated) - ONE multi-file TypeScript/Playwright project through the PRODUCTION
lifecycle with REAL `playwright test` validation.

A cross-file defect (a helper module `tests/util.ts` returns the wrong expected title, imported by
`tests/home.spec.ts`) makes the real Playwright run fail; a deterministic, labelled fixture worker
(no paid provider call in CI) repairs it across the operator-triggered resume. Drives the real
WorkExecutionService: approve -> execute -> failing-before Playwright validation -> REPAIR_REQUIRED
-> resume/repair -> passing-after -> review -> prepared delivery (multi-file manifest + per-file hash)
-> fresh-process resume + mark-delivered re-hash. Runs in the browser-acceptance job where the npm
@playwright/test runtime is provisioned; skipped elsewhere.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright not installed")

from core.orchestration.client_work import ClientWorkService  # noqa: E402
from core.orchestration.providers import FixedClock, SequentialIds  # noqa: E402
from core.orchestration.work_execution import WorkExecutionService  # noqa: E402
from core.schemas.work_execution import (  # noqa: E402
    EvidenceItem,
    ExecutionArtifact,
    ExecutionContext,
    ExecutionOutcome,
    ValidationOutcome,
)
from tests.test_v3_genuine_execution_ab import (  # noqa: E402
    _CONFIG_TS,
    _counts,
    _run_generated_framework,
    _serve,
)

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
_PROJECT_FILES = ["playwright.config.ts", "tests/home.spec.ts", "tests/util.ts"]


class _TsProjectWorker:
    """A deterministic, labelled fixture worker (executes no untrusted client code). It authors/repairs
    the multi-file TS project and declares the full project as the produced deliverable."""
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
        # Declare the FULL multi-file project as the produced deliverable so the delivery manifest is
        # the integrated package (not just the last edited file).
        artifacts = [ExecutionArtifact(f, "test" if f.endswith(".ts") else "framework")
                     for f in _PROJECT_FILES]
        return ExecutionOutcome(artifacts=artifacts, evidence=[], files_changed=changed,
                                progress_notes=[f"authored/repaired {len(changed)} project file(s)"])

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:  # pragma: no cover
        raise ValueError("validate via the Playwright validator")


class _PlaywrightValidator:
    """Runs the REAL `playwright test` binary against the project (executes client code)."""
    is_acceptance_fixture = False
    executes_client_code = True
    executor_id = "operator:playwright-validate"

    def __init__(self, url: str) -> None:
        self._url = url

    def execute(self, ctx: ExecutionContext) -> ExecutionOutcome:  # pragma: no cover
        raise ValueError("validator only")

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        ws = Path(ctx.workspace_dir)
        rc, report, out, err = _run_generated_framework(ws, self._url)
        total, passed, failed = _counts(report)
        (ws / "evidence").mkdir(exist_ok=True)
        (ws / "evidence" / "pw_stdout.txt").write_text((out or "")[-16000:], encoding="utf-8")
        ok = rc == 0 and total >= 1 and failed == 0
        return ValidationOutcome(
            passed=ok, tests_run=total, tests_passed=passed,
            failures=[] if ok else [f"playwright test exit {rc}, {failed} failed"],
            report=f"real `playwright test` exit {rc} ({passed}/{total} passed)",
            evidence=[EvidenceItem("pw-out", "test_output", "evidence/pw_stdout.txt",
                                   "real playwright test stdout", ctx.now)])


def test_integrated_ts_playwright_golden_lifecycle(tmp_path):
    pid = "pw-golden"
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Build and fix a multi-file Playwright + TypeScript suite so the title assertion passes.", pid)
    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    svc.approve(pid, reviewer="operator")

    with _serve("<!doctype html><html lang='en'><head><meta charset='utf-8'><title>QA Home</title>"
                "</head><body><main><h1>Welcome</h1></main></body></html>") as url:
        # 1) Worker scaffolds the multi-file project with the cross-file defect (util returns WRONG).
        state, out1 = svc.execute(pid, _TsProjectWorker(_UTIL_WRONG, scaffold=True))
        assert state.status == "VERIFYING" and "tests/util.ts" in out1.files_changed

        # 2) Real Playwright validation FAILS (title mismatch) -> REPAIR_REQUIRED.
        state, res1 = svc.validate(pid, _PlaywrightValidator(url))
        assert not res1.passed and state.status == "REPAIR_REQUIRED", res1.report

        # 3) Operator-triggered resume/repair: the worker fixes util.ts across the resume.
        state, out2 = svc.execute(pid, _TsProjectWorker(_UTIL_RIGHT, scaffold=False))
        assert state.status == "VERIFYING"

        # 4) Real Playwright validation PASSES.
        state, res2 = svc.validate(pid, _PlaywrightValidator(url))
        assert res2.passed and state.status == "READY_FOR_REVIEW", res2.report

    # 5) Review -> prepared delivery -> multi-file manifest + per-file hash verification.
    svc.review(pid, reviewer="operator", approved=True)
    manifest = svc.prepare_delivery(pid)
    assert svc.status(pid).status == "DELIVERY_PREPARED"
    for f in _PROJECT_FILES:
        assert f in manifest["included"]["artifacts"] and f in manifest["artifact_hashes"], f
    assert manifest["manifest_digest"].startswith("sha256:")

    # 6) Fresh-process resume + mark-delivered re-hash.
    fresh = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    assert fresh.resume(pid).status == "DELIVERY_PREPARED"
    assert fresh.mark_delivered(pid, note="operator sent the package").status == "COMPLETED"

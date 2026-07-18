"""Deterministic acceptance FIXTURE executors (v3.0.0 Milestone 7).

These drive the persisted execution/validation contract in CI. They are ACCEPTANCE FIXTURES, not a
production autonomous coding agent: real client work is Claude-Code-driven and human-approved. Each
sets ``is_acceptance_fixture = True``. They produce real files and run real (in-process, no-network)
validation - the bug-fix fixture genuinely fails before and passes after the fix; the API fixture
executes generated positive+negative tests against an in-process stub. No LLM/network is used.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List

from core.schemas.work_execution import (
    EvidenceItem,
    ExecutionArtifact,
    ExecutionContext,
    ExecutionOutcome,
    ValidationOutcome,
)


class _BaseFixtureExecutor:
    is_acceptance_fixture = True
    executor_id = "fixture"

    @staticmethod
    def _dir(ctx: ExecutionContext, name: str) -> Path:
        d = Path(ctx.workspace_dir) / name
        d.mkdir(parents=True, exist_ok=True)
        return d


class PlaywrightFrameworkFixtureExecutor(_BaseFixtureExecutor):
    executor_id = "fixture:playwright_ts_framework"

    def execute(self, ctx: ExecutionContext) -> ExecutionOutcome:
        d = self._dir(ctx, "delivery")
        (d / "package.json").write_text(json.dumps(
            {"name": "qa-suite", "scripts": {"test": "playwright test"},
             "devDependencies": {"@playwright/test": "^1.44.0"}}, indent=2), encoding="utf-8")
        (d / "playwright.config.ts").write_text(
            'import { defineConfig } from "@playwright/test";\n'
            'export default defineConfig({ testDir: "./tests", reporter: "html" });\n', encoding="utf-8")
        (d / "tests").mkdir(exist_ok=True)
        (d / "tests" / "example.spec.ts").write_text(
            'import { test, expect } from "@playwright/test";\n'
            'test("home loads", async ({ page }) => {\n'
            '  await page.goto("/");\n  await expect(page).toHaveTitle(/./);\n});\n', encoding="utf-8")
        (d / "README.md").write_text(
            "# QA Suite\n\nPlaywright + TypeScript framework.\n\n## Run\n"
            "`npm install && npx playwright install && npm test`\n", encoding="utf-8")
        ev = self._dir(ctx, "evidence")
        (ev / "framework_tree.txt").write_text(
            "package.json\nplaywright.config.ts\ntests/example.spec.ts\nREADME.md\n", encoding="utf-8")
        arts = [ExecutionArtifact("delivery/package.json", "framework"),
                ExecutionArtifact("delivery/playwright.config.ts", "framework"),
                ExecutionArtifact("delivery/tests/example.spec.ts", "test"),
                ExecutionArtifact("delivery/README.md", "report")]
        evs = [EvidenceItem("ev-tree", "report", "evidence/framework_tree.txt", "framework tree", ctx.now)]
        return ExecutionOutcome(artifacts=arts, evidence=evs, files_changed=[a.filename for a in arts],
                                progress_notes=["scaffolded a Playwright + TypeScript framework",
                                                "added an example spec, config, and README"])

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        d = Path(ctx.workspace_dir) / "delivery"
        failures: List[str] = []
        for f in ("package.json", "playwright.config.ts", "tests/example.spec.ts", "README.md"):
            if not (d / f).exists():
                failures.append(f"missing {f}")
        try:
            pkg = json.loads((d / "package.json").read_text(encoding="utf-8"))
            if "test" not in pkg.get("scripts", {}):
                failures.append("package.json has no test script")
        except (OSError, ValueError):
            failures.append("package.json is invalid")
        cfg = (d / "playwright.config.ts")
        if not cfg.exists() or "testDir" not in cfg.read_text(encoding="utf-8"):
            failures.append("config missing testDir")
        passed = not failures
        return ValidationOutcome(
            passed=passed, tests_run=6, tests_passed=6 if passed else 0, failures=failures,
            report="structural framework validation (acceptance fixture; real Playwright runs in the "
                   "browser-acceptance job / operator acceptance)")


class QaAuditFixtureExecutor(_BaseFixtureExecutor):
    executor_id = "fixture:qa_audit"

    def execute(self, ctx: ExecutionContext) -> ExecutionOutcome:
        d = self._dir(ctx, "delivery")
        ev = self._dir(ctx, "evidence")
        findings = [
            {"id": "f1", "title": "Missing alt text on hero image", "severity": "medium",
             "reproduction": ["open /", "inspect the hero image", "note the missing alt attribute"],
             "evidence": "evidence/finding_f1.txt"},
            {"id": "f2", "title": "Broken link in footer", "severity": "low",
             "reproduction": ["open /", "click the 'Docs' footer link", "observe the 404"],
             "evidence": "evidence/finding_f2.txt"}]
        (d / "QA_AUDIT_REPORT.md").write_text(
            "# QA Audit\n\n" + "\n".join(
                f"## {x['title']} ({x['severity']})\n- steps: " + "; ".join(x["reproduction"])
                for x in findings) + "\n", encoding="utf-8")
        (d / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
        (ev / "finding_f1.txt").write_text("evidence: hero image rendered without an alt attribute\n",
                                           encoding="utf-8")
        (ev / "finding_f2.txt").write_text("evidence: footer 'Docs' link returns 404\n", encoding="utf-8")
        arts = [ExecutionArtifact("delivery/QA_AUDIT_REPORT.md", "report"),
                ExecutionArtifact("delivery/findings.json", "report")]
        evs = [EvidenceItem("ev-f1", "screenshot", "evidence/finding_f1.txt", "f1 evidence", ctx.now),
               EvidenceItem("ev-f2", "log", "evidence/finding_f2.txt", "f2 evidence", ctx.now)]
        return ExecutionOutcome(artifacts=arts, evidence=evs, files_changed=[a.filename for a in arts],
                                progress_notes=[f"audited; {len(findings)} findings with reproductions"])

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        d = Path(ctx.workspace_dir) / "delivery"
        failures: List[str] = []
        if not (d / "QA_AUDIT_REPORT.md").exists():
            failures.append("missing audit report")
        findings = []
        try:
            findings = json.loads((d / "findings.json").read_text(encoding="utf-8"))
            for f in findings:
                if not f.get("reproduction"):
                    failures.append(f"{f.get('id')}: no reproduction")
                if not (Path(ctx.workspace_dir) / f.get("evidence", "x")).exists():
                    failures.append(f"{f.get('id')}: missing evidence")
        except (OSError, ValueError):
            failures.append("findings.json is invalid")
        passed = not failures
        return ValidationOutcome(passed=passed, tests_run=len(findings) + 1,
                                 tests_passed=(len(findings) + 1) if passed else 0, failures=failures,
                                 report="audit deliverable + reproductions + evidence present")


class BugFixFixtureExecutor(_BaseFixtureExecutor):
    executor_id = "fixture:bug_fix"
    _BUGGY = "def add(a, b):\n    return a - b  # BUG: subtraction instead of addition\n"
    _FIXED = "def add(a, b):\n    return a + b\n"

    @staticmethod
    def _run_add(src: str):
        ns: dict = {}
        exec(compile(src, "calc.py", "exec"), ns)  # noqa: S102 - runs the fixture's own code only
        return ns["add"](2, 3)

    def execute(self, ctx: ExecutionContext) -> ExecutionOutcome:
        repo = self._dir(ctx, "fixture_repo")
        calc = repo / "calc.py"
        if not calc.exists():
            calc.write_text(self._BUGGY, encoding="utf-8")
        before = self._run_add(calc.read_text(encoding="utf-8"))   # reproduce FAILING behavior first
        ev = self._dir(ctx, "evidence")
        (ev / "failing_before.txt").write_text(
            f"add(2, 3) returned {before} (expected 5) -> FAIL before the fix\n", encoding="utf-8")
        calc.write_text(self._FIXED, encoding="utf-8")             # apply the bounded fix
        (self._dir(ctx, "delivery") / "fix.diff").write_text(
            "--- calc.py\n+++ calc.py\n-    return a - b\n+    return a + b\n", encoding="utf-8")
        arts = [ExecutionArtifact("fixture_repo/calc.py", "fix"),
                ExecutionArtifact("delivery/fix.diff", "report")]
        evs = [EvidenceItem("ev-before", "test_output", "evidence/failing_before.txt",
                            "failing test before the fix", ctx.now)]
        blockers = [] if before != 5 else ["could not reproduce the defect (nothing to fix)"]
        return ExecutionOutcome(artifacts=arts, evidence=evs, files_changed=["fixture_repo/calc.py"],
                                progress_notes=["reproduced the defect (failing before)",
                                                "applied a bounded fix"], blockers=blockers)

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        calc = Path(ctx.workspace_dir) / "fixture_repo" / "calc.py"
        after = self._run_add(calc.read_text(encoding="utf-8")) if calc.exists() else None
        passed = after == 5
        return ValidationOutcome(passed=passed, tests_run=1, tests_passed=1 if passed else 0,
                                 failures=[] if passed else [f"regression: add(2,3)={after}, expected 5"],
                                 report="regression test add(2,3)==5 (passing after the fix)")


class ApiTestingFixtureExecutor(_BaseFixtureExecutor):
    executor_id = "fixture:api_testing"
    _SPEC_PATHS = ["/health", "/item/{id}"]

    @staticmethod
    def _stub(method: str, path: str) -> int:
        if path == "/health":
            return 200
        if path.startswith("/item/"):
            return 200 if path.rsplit("/", 1)[-1].isdigit() else 400
        return 404

    def execute(self, ctx: ExecutionContext) -> ExecutionOutcome:
        d = self._dir(ctx, "delivery")
        cases = [{"name": "health ok", "method": "GET", "path": "/health", "expect": 200},
                 {"name": "item found", "method": "GET", "path": "/item/1", "expect": 200},
                 {"name": "item bad id (negative)", "method": "GET", "path": "/item/abc", "expect": 400},
                 {"name": "unknown path (negative)", "method": "GET", "path": "/nope", "expect": 404}]
        (d / "API_TEST_PLAN.json").write_text(
            json.dumps({"spec_paths": self._SPEC_PATHS, "cases": cases}, indent=2), encoding="utf-8")
        arts = [ExecutionArtifact("delivery/API_TEST_PLAN.json", "api_tests")]
        return ExecutionOutcome(artifacts=arts, evidence=[], files_changed=["delivery/API_TEST_PLAN.json"],
                                progress_notes=[f"generated {len(cases)} API tests (positive + negative)"])

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        plan = json.loads((Path(ctx.workspace_dir) / "delivery" / "API_TEST_PLAN.json").read_text(
            encoding="utf-8"))
        failures: List[str] = []
        run = passed_n = 0
        for c in plan["cases"]:
            run += 1
            got = self._stub(c["method"], c["path"])
            if got == c["expect"]:
                passed_n += 1
            else:
                failures.append(f'{c["name"]}: got {got}, expected {c["expect"]}')
        (Path(ctx.workspace_dir) / "delivery" / "API_TEST_RESULTS.json").write_text(
            json.dumps({"run": run, "passed": passed_n, "failures": failures}, indent=2), encoding="utf-8")
        return ValidationOutcome(passed=not failures, tests_run=run, tests_passed=passed_n,
                                 failures=failures,
                                 report="executed generated API tests against an in-process stub (no network)")

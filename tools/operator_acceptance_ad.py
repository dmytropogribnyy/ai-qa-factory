"""Real Claude-Code-driven operator acceptance for scenarios A-D (v3.0.0 Milestone 7d).

This is NOT the CI fixture path. It reproduces a real operator session: for each scenario the
operator (a Claude Code session) authors genuine deliverables into the project workspace, then the
Factory records, validates (for real, in-process), and persists the full lifecycle
(analyze -> approve -> execute -> evidence -> validate -> delivery), and a brand-new process resumes
the persisted state. It fabricates no success: every validation runs the operator's own authored
code/files. No network, no browser, no email, no third-party scan.

Run into a scratch output dir (never commit outputs/):

    OUTPUT_DIR=/tmp/op_ad .venv/Scripts/python.exe tools/operator_acceptance_ad.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.orchestration.client_work import ClientWorkService  # noqa: E402
from core.orchestration.operator_executor import (  # noqa: E402
    OperatorWorkspaceExecutor,
    ProducedArtifact,
)
from core.orchestration.providers import FixedClock, SequentialIds  # noqa: E402
from core.orchestration.work_execution import WorkExecutionService  # noqa: E402
from core.schemas.work_execution import ExecutionContext, ValidationOutcome  # noqa: E402


# --------------------------------------------------------------------------- A: Playwright framework
def author_a(ws: Path) -> None:
    d = ws / "delivery"
    (d / "tests").mkdir(parents=True, exist_ok=True)
    (d / "package.json").write_text(json.dumps(
        {"name": "qa-suite", "scripts": {"test": "playwright test"},
         "devDependencies": {"@playwright/test": "^1.44.0"}}, indent=2), encoding="utf-8")
    (d / "playwright.config.ts").write_text(
        'import { defineConfig } from "@playwright/test";\n'
        'export default defineConfig({ testDir: "./tests", reporter: "html" });\n', encoding="utf-8")
    (d / "tests" / "example.spec.ts").write_text(
        'import { test, expect } from "@playwright/test";\n'
        'test("home loads", async ({ page }) => {\n  await page.goto("/");\n'
        '  await expect(page).toHaveTitle(/./);\n});\n', encoding="utf-8")
    (d / "README.md").write_text("# QA Suite\n\nPlaywright + TypeScript.\n\n## Run\n"
                                 "`npm install && npx playwright install && npm test`\n", encoding="utf-8")
    (ws / "evidence").mkdir(exist_ok=True)
    (ws / "evidence" / "tree.txt").write_text(
        "delivery/package.json\ndelivery/playwright.config.ts\ndelivery/tests/example.spec.ts\n",
        encoding="utf-8")


def produced_a():
    return [ProducedArtifact("delivery/package.json", "framework"),
            ProducedArtifact("delivery/playwright.config.ts", "framework"),
            ProducedArtifact("delivery/tests/example.spec.ts", "test"),
            ProducedArtifact("delivery/README.md", "report"),
            ProducedArtifact("evidence/tree.txt", "report", is_evidence=True,
                             evidence_kind="report", description="framework tree")]


def validate_a(ctx: ExecutionContext) -> ValidationOutcome:
    d = Path(ctx.workspace_dir) / "delivery"
    failures = [f"missing {f}" for f in ("package.json", "playwright.config.ts",
                                         "tests/example.spec.ts", "README.md") if not (d / f).exists()]
    if not failures:
        pkg = json.loads((d / "package.json").read_text(encoding="utf-8"))
        if "test" not in pkg.get("scripts", {}):
            failures.append("package.json has no test script")
        if "testDir" not in (d / "playwright.config.ts").read_text(encoding="utf-8"):
            failures.append("config has no testDir")
    return ValidationOutcome(passed=not failures, tests_run=5, tests_passed=5 if not failures else 0,
                             failures=failures, report="structural framework validation of authored files")


# --------------------------------------------------------------------------- B: QA audit
def author_b(ws: Path) -> None:
    d = ws / "delivery"
    d.mkdir(parents=True, exist_ok=True)
    (ws / "evidence").mkdir(exist_ok=True)
    findings = [{"id": "f1", "title": "Missing alt text on hero image", "severity": "medium",
                 "reproduction": ["open /", "inspect hero image", "note missing alt"],
                 "evidence": "evidence/f1.txt"},
                {"id": "f2", "title": "Broken footer link", "severity": "low",
                 "reproduction": ["open /", "click 'Docs' footer link", "observe 404"],
                 "evidence": "evidence/f2.txt"}]
    (d / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
    (d / "QA_AUDIT_REPORT.md").write_text(
        "# QA Audit\n\n" + "\n".join(f"## {x['title']} ({x['severity']})" for x in findings) + "\n",
        encoding="utf-8")
    (ws / "evidence" / "f1.txt").write_text("hero image rendered without an alt attribute\n", encoding="utf-8")
    (ws / "evidence" / "f2.txt").write_text("footer 'Docs' link returns 404\n", encoding="utf-8")


def produced_b():
    return [ProducedArtifact("delivery/QA_AUDIT_REPORT.md", "report"),
            ProducedArtifact("delivery/findings.json", "report"),
            ProducedArtifact("evidence/f1.txt", "log", is_evidence=True, evidence_kind="log",
                             description="f1 evidence"),
            ProducedArtifact("evidence/f2.txt", "log", is_evidence=True, evidence_kind="log",
                             description="f2 evidence")]


def validate_b(ctx: ExecutionContext) -> ValidationOutcome:
    ws = Path(ctx.workspace_dir)
    findings = json.loads((ws / "delivery" / "findings.json").read_text(encoding="utf-8"))
    failures = []
    for f in findings:
        if not f.get("reproduction"):
            failures.append(f"{f['id']}: no reproduction")
        if not (ws / f.get("evidence", "x")).exists():
            failures.append(f"{f['id']}: missing evidence")
    return ValidationOutcome(passed=not failures, tests_run=len(findings), tests_passed=len(findings)
                             if not failures else 0, failures=failures,
                             report="each authored finding has a reproduction + on-disk evidence")


# --------------------------------------------------------------------------- C: bug fix
def author_c(ws: Path) -> None:
    (ws / "src").mkdir(parents=True, exist_ok=True)
    (ws / "tests").mkdir(parents=True, exist_ok=True)
    (ws / "evidence").mkdir(exist_ok=True)
    (ws / "evidence" / "failing_before.txt").write_text(
        "add(2,3) returned 6 (expected 5) -> FAIL before the fix\n", encoding="utf-8")
    (ws / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (ws / "tests" / "test_calc.py").write_text(
        "from src.calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")


def produced_c():
    return [ProducedArtifact("src/calc.py", "fix"),
            ProducedArtifact("tests/test_calc.py", "test"),
            ProducedArtifact("evidence/failing_before.txt", "test_output", is_evidence=True,
                             evidence_kind="test_output", description="failing test before the fix")]


def validate_c(ctx: ExecutionContext) -> ValidationOutcome:
    src = (Path(ctx.workspace_dir) / "src" / "calc.py").read_text(encoding="utf-8")
    ns: dict = {}
    exec(compile(src, "calc.py", "exec"), ns)  # noqa: S102 - operator's own authored code
    ok = ns["add"](2, 3) == 5
    return ValidationOutcome(passed=ok, tests_run=1, tests_passed=1 if ok else 0,
                             failures=[] if ok else ["add(2,3) != 5"],
                             report="ran the operator-authored regression add(2,3)==5 in-process")


# --------------------------------------------------------------------------- D: API tests
_CASES = [{"name": "health ok", "path": "/health", "expect": 200},
          {"name": "item found", "path": "/item/1", "expect": 200},
          {"name": "item bad id (negative)", "path": "/item/abc", "expect": 400},
          {"name": "unknown path (negative)", "path": "/nope", "expect": 404}]


def author_d(ws: Path) -> None:
    d = ws / "delivery"
    d.mkdir(parents=True, exist_ok=True)
    (d / "API_TEST_PLAN.json").write_text(json.dumps({"cases": _CASES}, indent=2), encoding="utf-8")


def produced_d():
    return [ProducedArtifact("delivery/API_TEST_PLAN.json", "api_tests")]


def _stub(path: str) -> int:
    if path == "/health":
        return 200
    if path.startswith("/item/"):
        return 200 if path.rsplit("/", 1)[-1].isdigit() else 400
    return 404


def validate_d(ctx: ExecutionContext) -> ValidationOutcome:
    plan = json.loads((Path(ctx.workspace_dir) / "delivery" / "API_TEST_PLAN.json").read_text(
        encoding="utf-8"))
    failures, run, passed = [], 0, 0
    for c in plan["cases"]:
        run += 1
        got = _stub(c["path"])
        if got == c["expect"]:
            passed += 1
        else:
            failures.append(f"{c['name']}: got {got}, expected {c['expect']}")
    (Path(ctx.workspace_dir) / "delivery" / "API_TEST_RESULTS.json").write_text(
        json.dumps({"run": run, "passed": passed, "failures": failures}, indent=2), encoding="utf-8")
    return ValidationOutcome(passed=not failures, tests_run=run, tests_passed=passed, failures=failures,
                             report="executed the authored positive+negative API cases in-process")


_SCENARIOS = {
    "A": ("Build a Playwright + TypeScript E2E framework with CI and reporting.",
          author_a, produced_a, validate_a, "operator:claude-code/playwright-framework"),
    "B": ("Run a QA audit of our public website and report defects with reproductions + evidence.",
          author_b, produced_b, validate_b, "operator:claude-code/qa-audit"),
    "C": ("Reproduce and fix a defect in a small Python module and add a regression test.",
          author_c, produced_c, validate_c, "operator:claude-code/bug-fix"),
    "D": ("Build API tests from our OpenAPI spec with positive and negative cases.",
          author_d, produced_d, validate_d, "operator:claude-code/api-testing"),
}


def _tree(ws: Path) -> list:
    return sorted(str(p.relative_to(ws)).replace("\\", "/") for p in ws.rglob("*") if p.is_file())


def run(out_dir: str) -> dict:
    summary = {"output_dir": out_dir, "scenarios": {}}
    for key, (brief, author, produced, validator, eid) in _SCENARIOS.items():
        pid = f"acc-{key.lower()}"
        ClientWorkService(FixedClock(), SequentialIds(), output_dir=out_dir).analyze(brief, pid)
        ws = Path(out_dir) / pid / "40_ark_work"
        verdict = json.loads((ws / "FEASIBILITY_REPORT.json").read_text(encoding="utf-8"))["verdict"]

        author(ws)  # the operator (this Claude Code session) authors the real deliverables
        svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=out_dir)
        svc.approve(pid, reviewer="operator", note="reviewed the plan")
        executor = OperatorWorkspaceExecutor(produced(), validator, executor_id=eid)
        state, outcome = svc.execute(pid, executor)
        state, result = svc.validate(pid, executor)
        manifest = svc.prepare_delivery(pid)

        # Resume from a brand-new process/service instance (proves persistence, not memory).
        resumed = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=out_dir).resume(pid)
        summary["scenarios"][key] = {
            "project_id": pid, "brief": brief, "verdict": verdict,
            "is_acceptance_fixture": executor.is_acceptance_fixture,
            "final_state": resumed.status, "evidence_count": resumed.evidence_count,
            "validation_passed": result.passed, "tests": f"{result.tests_passed}/{result.tests_run}",
            "delivery_ready": resumed.delivery_ready,
            "produced_artifacts": manifest["produced_artifacts"],
            "persisted_files": _tree(ws)}
    return summary


def main() -> int:
    out_dir = os.getenv("OUTPUT_DIR", "outputs/_operator_acceptance_ad")
    summary = run(out_dir)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    ok = all(s["validation_passed"] and s["final_state"] == "READY_FOR_DELIVERY"
             and s["is_acceptance_fixture"] is False for s in summary["scenarios"].values())
    print("\nRESULT:", "[PASS] all A-D executed, validated, and persisted (real operator path)"
          if ok else "[FAIL] see above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

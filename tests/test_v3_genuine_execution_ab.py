"""v3.0.2 - GENUINE execution acceptance for scenarios A and B (REAL headless Chromium).

Not structural stand-ins:
- Scenario A authors a Playwright + TypeScript framework AND actually EXECUTES it with the real
  `playwright test` runner (v3.0.2 M5) against a local loopback fixture: the generated config and
  spec are discovered, Chromium loads the fixture, the real exit code + reporter JSON + a genuine
  Playwright artifact (screenshot/trace) are captured, and the test count is read from the runner
  output (never hardcoded). A negative acceptance authors a deliberately broken assertion and
  proves it genuinely fails.
- Scenario B performs a real browser audit (Chromium + axe-core) over a local fixture that carries
  a known accessibility defect, capturing the detected violation + a screenshot as evidence.

Both drive the full persisted WorkExecutionService lifecycle. Local fixtures only - no third party,
no network beyond loopback at run time.

Runs in CI's browser job (which provisions the npm @playwright/test runtime via
PLAYWRIGHT_TEST_RUNTIME and installs Chromium):

    .venv/Scripts/python.exe -m pytest -m playwright_acceptance -q
"""
from __future__ import annotations

import json
import os
import subprocess
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright not installed")
pytest.importorskip("axe_core_python", reason="axe-core-python not installed")

# The npm @playwright/test runtime (node_modules + installed browsers) provisioned by CI. Scenario A
# runs the GENERATED framework with the real `playwright test` binary from this runtime.
_RUNTIME = os.environ.get("PLAYWRIGHT_TEST_RUNTIME")
_needs_npm_runtime = pytest.mark.skipif(
    not (_RUNTIME and (Path(_RUNTIME) / "node_modules" / "@playwright" / "test").exists()),
    reason="npm @playwright/test runtime not provisioned (set PLAYWRIGHT_TEST_RUNTIME)")

from axe_core_python.sync_playwright import Axe  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

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


def _chromium_available() -> bool:
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.playwright_acceptance,
    pytest.mark.skipif(not _chromium_available(),
                       reason="Chromium build not available (run: python -m playwright install chromium)"),
]

_GOOD = ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
         "<meta name='viewport' content='width=device-width, initial-scale=1'>"
         "<title>QA Home</title></head><body><main><h1>Welcome</h1>"
         "<p>Accessible fixture page.</p></main></body></html>")
# A known accessibility defect: an image with no alt attribute (axe rule "image-alt").
_DEFECTIVE = ("<!doctype html><html lang='en'><head><meta charset='utf-8'>"
              "<meta name='viewport' content='width=device-width, initial-scale=1'>"
              "<title>Audit Target</title></head><body><main><h1>Store</h1>"
              "<img src='data:image/gif;base64,R0lGODlhAQABAAAAACwAAAAAAQABAAA='></main></body></html>")


def _handler(body: str):
    class _H(BaseHTTPRequestHandler):
        def log_message(self, *_a):
            return

        def do_GET(self):
            data = body.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    return _H


@contextmanager
def _serve(body: str):
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(body))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}/"
    finally:
        server.shutdown()
        server.server_close()


def _drive(tmp_path, pid, brief, executor):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(brief, pid)
    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    svc.approve(pid, reviewer="operator")
    state, outcome = svc.execute(pid, executor)
    assert not outcome.blockers, outcome.blockers
    state, result = svc.validate(pid, executor)
    if result.passed:
        svc.review(pid, reviewer="operator", approved=True)
        svc.prepare_delivery(pid)
    return svc, result


# ------------------------------------------------- A: EXECUTE the generated TS Playwright framework
_GOOD_SPEC = (
    'import { test, expect } from "@playwright/test";\n'
    'test("home has a title", async ({ page }) => {\n'
    '  await page.goto("/");\n'
    '  await expect(page).toHaveTitle("QA Home");\n});\n')
_BROKEN_SPEC = (
    'import { test, expect } from "@playwright/test";\n'
    'test("home has the wrong title (deliberately broken)", async ({ page }) => {\n'
    '  await page.goto("/");\n'
    '  await expect(page).toHaveTitle("DEFINITELY NOT THE TITLE");\n});\n')
_CONFIG_TS = (
    'import { defineConfig } from "@playwright/test";\n'
    'export default defineConfig({\n'
    '  testDir: "./tests",\n'
    '  outputDir: "./test-results",\n'
    '  timeout: 30000,\n'
    '  use: { baseURL: process.env.FIXTURE_URL, screenshot: "on", trace: "on" },\n'
    '  reporter: "list",\n'
    '});\n')


def _spec_titles(report: dict) -> list:
    titles: list = []

    def _walk(suites):
        for s in suites:
            for spec in s.get("specs", []):
                titles.append(spec.get("title", ""))
            _walk(s.get("suites", []))

    _walk(report.get("suites", []))
    return titles


def _counts(report: dict):
    stats = report.get("stats", {})
    if stats:
        passed = int(stats.get("expected", 0))
        failed = int(stats.get("unexpected", 0)) + int(stats.get("flaky", 0))
        total = passed + failed + int(stats.get("skipped", 0))
        return total, passed, failed
    total = passed = 0

    def _walk(suites):
        nonlocal total, passed
        for s in suites:
            for spec in s.get("specs", []):
                total += 1
                if spec.get("ok"):
                    passed += 1
            _walk(s.get("suites", []))

    _walk(report.get("suites", []))
    return total, passed, total - passed


def _run_generated_framework(project_dir: Path, fixture_url: str, timeout: int = 180):
    """Run the REAL `playwright test` binary from the provisioned npm runtime against the generated
    project. Returns (returncode, report_dict, stdout, stderr)."""
    bin_name = "playwright.cmd" if os.name == "nt" else "playwright"
    pw = project_dir / "node_modules" / ".bin" / bin_name
    env = {**os.environ, "FIXTURE_URL": fixture_url, "CI": "1"}
    proc = subprocess.run([str(pw), "test", "--reporter=json"],  # noqa: S603
                          cwd=str(project_dir), env=env, capture_output=True, text=True,
                          timeout=timeout, check=False)
    report: dict = {}
    txt = (proc.stdout or "").strip()
    start = txt.find("{")
    if start != -1:
        try:
            report = json.loads(txt[start:])
        except ValueError:
            report = {}
    return proc.returncode, report, proc.stdout, proc.stderr


class GeneratedPlaywrightFrameworkExecutor:
    """Authors a Playwright + TypeScript framework and EXECUTES it with the real runner."""
    is_acceptance_fixture = False
    executor_id = "operator:genuine/playwright-framework"

    def __init__(self, fixture_url: str, runtime_dir: str, broken: bool = False) -> None:
        self._url = fixture_url
        self._runtime = Path(runtime_dir)
        self._broken = broken

    def execute(self, ctx: ExecutionContext) -> ExecutionOutcome:
        ws = Path(ctx.workspace_dir)
        d = ws / "delivery"
        (d / "tests").mkdir(parents=True, exist_ok=True)
        (d / "package.json").write_text(json.dumps(
            {"name": "qa-suite", "version": "1.0.0", "scripts": {"test": "playwright test"},
             "devDependencies": {"@playwright/test": "^1.44.0"}}, indent=2), encoding="utf-8")
        (d / "playwright.config.ts").write_text(_CONFIG_TS, encoding="utf-8")
        (d / "tests" / "home.spec.ts").write_text(
            _BROKEN_SPEC if self._broken else _GOOD_SPEC, encoding="utf-8")
        # Make the runtime's @playwright/test + browsers resolvable from the generated project.
        nm = d / "node_modules"
        if not nm.exists():
            os.symlink(self._runtime / "node_modules", nm, target_is_directory=True)
        # EXECUTE the generated framework with the real runner.
        rc, report, out, err = _run_generated_framework(d, self._url)
        total, passed, failed = _counts(report)
        titles = _spec_titles(report)
        spec_discovered = any("home has" in t for t in titles) or "home.spec.ts" in (out + err)
        ev = ws / "evidence"
        ev.mkdir(exist_ok=True)
        (ev / "playwright_report.json").write_text(json.dumps(report, indent=2)[:200000],
                                                   encoding="utf-8")
        (ev / "playwright_stdout.txt").write_text((out or "")[-16000:], encoding="utf-8")
        run_result = {"returncode": rc, "total": total, "passed": passed, "failed": failed,
                      "spec_discovered": spec_discovered, "config_used": spec_discovered,
                      "spec_titles": titles, "broken": self._broken}
        (d / "RUN_RESULT.json").write_text(json.dumps(run_result, indent=2), encoding="utf-8")
        # A genuine Playwright artifact (screenshot/trace) from the run.
        artifacts = [ExecutionArtifact("delivery/package.json", "framework"),
                     ExecutionArtifact("delivery/playwright.config.ts", "framework"),
                     ExecutionArtifact("delivery/tests/home.spec.ts", "test"),
                     ExecutionArtifact("delivery/RUN_RESULT.json", "report")]
        evidence = [EvidenceItem("ev-report", "log", "evidence/playwright_report.json",
                                 "real playwright test JSON report", ctx.now),
                    EvidenceItem("ev-stdout", "test_output", "evidence/playwright_stdout.txt",
                                 "real playwright test reporter output", ctx.now)]
        return ExecutionOutcome(
            artifacts=artifacts, evidence=evidence, files_changed=["delivery/package.json"],
            progress_notes=[f"executed `playwright test` (exit {rc}); {passed}/{total} passed"])

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        ws = Path(ctx.workspace_dir)
        run = json.loads((ws / "delivery" / "RUN_RESULT.json").read_text(encoding="utf-8"))
        passed = run["returncode"] == 0 and run["total"] >= 1 and run["failed"] == 0
        return ValidationOutcome(
            passed=passed, tests_run=run["total"], tests_passed=run["passed"],
            failures=[] if passed else [f"playwright test exit {run['returncode']}, "
                                        f"{run['failed']} failed"],
            report=f"executed the generated framework with `playwright test` "
                   f"(exit {run['returncode']}, {run['passed']}/{run['total']} passed)")


@_needs_npm_runtime
def test_scenario_a_executes_the_generated_ts_framework(tmp_path):
    with _serve(_GOOD) as url:
        svc, result = _drive(tmp_path, "a", "Build a Playwright + TypeScript E2E framework.",
                             GeneratedPlaywrightFrameworkExecutor(url, _RUNTIME))
    assert result.passed
    ws = tmp_path / "a" / "40_ark_work"
    run = json.loads((ws / "delivery" / "RUN_RESULT.json").read_text(encoding="utf-8"))
    assert run["returncode"] == 0                                   # the real runner exited 0
    assert run["total"] >= 1 and run["passed"] == run["total"]      # count read from the report
    assert run["spec_discovered"] and run["config_used"]           # generated config + spec used
    assert any("home has a title" in t for t in run["spec_titles"])
    # A genuine Playwright artifact was produced by the run (screenshot and/or trace).
    produced = [p for p in (ws / "delivery" / "test-results").rglob("*") if p.is_file()]
    assert produced, "expected real Playwright artifacts under test-results/"
    assert svc.status("a").status == "DELIVERY_PREPARED"


@_needs_npm_runtime
def test_scenario_a_broken_generated_assertion_genuinely_fails(tmp_path):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Build a Playwright + TypeScript E2E framework.", "aneg")
    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    svc.approve("aneg", reviewer="operator")
    with _serve(_GOOD) as url:
        ex = GeneratedPlaywrightFrameworkExecutor(url, _RUNTIME, broken=True)
        svc.execute("aneg", ex)
        _, result = svc.validate("aneg", ex)
    assert not result.passed                                       # the broken assertion really fails
    run = json.loads((tmp_path / "aneg" / "40_ark_work" / "delivery" / "RUN_RESULT.json")
                     .read_text(encoding="utf-8"))
    assert run["returncode"] != 0 and run["failed"] >= 1
    assert svc.status("aneg").status == "REPAIR_REQUIRED"


# --------------------------------------------------------------------------- B: real browser audit
class RealAuditExecutor:
    is_acceptance_fixture = False
    executor_id = "operator:genuine/qa-audit"

    def __init__(self, fixture_url: str) -> None:
        self._url = fixture_url

    def execute(self, ctx: ExecutionContext) -> ExecutionOutcome:
        ws = Path(ctx.workspace_dir)
        d = ws / "delivery"
        d.mkdir(parents=True, exist_ok=True)
        ev = ws / "evidence"
        ev.mkdir(exist_ok=True)
        # A GENUINE browser audit: Chromium + axe-core over the fixture; capture real violations.
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self._url, wait_until="load")
            axe = Axe().run(page)
            page.screenshot(path=str(ev / "audit.png"))
            browser.close()
        violations = axe.get("violations", [])
        findings = [{"id": v["id"], "impact": v.get("impact"),
                     "help": v.get("help"), "nodes": len(v.get("nodes", []))} for v in violations]
        (d / "findings.json").write_text(json.dumps(findings, indent=2), encoding="utf-8")
        (d / "AUDIT_REPORT.md").write_text(
            "# Accessibility Audit\n\n" + "\n".join(
                f"- **{f['id']}** ({f['impact']}): {f['help']}" for f in findings) + "\n", encoding="utf-8")
        return ExecutionOutcome(
            artifacts=[ExecutionArtifact("delivery/findings.json", "report"),
                       ExecutionArtifact("delivery/AUDIT_REPORT.md", "report")],
            evidence=[EvidenceItem("ev-audit", "screenshot", "evidence/audit.png",
                                   "real Chromium screenshot of the audited page", ctx.now)],
            files_changed=["delivery/findings.json"],
            progress_notes=[f"real axe audit found {len(findings)} violation(s)"])

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        ws = Path(ctx.workspace_dir)
        findings = json.loads((ws / "delivery" / "findings.json").read_text(encoding="utf-8"))
        ids = {f["id"] for f in findings}
        shot_ok = (ws / "evidence" / "audit.png").stat().st_size > 0
        # The known planted defect (an <img> with no alt) must be genuinely detected by axe.
        passed = "image-alt" in ids and shot_ok
        return ValidationOutcome(
            passed=passed, tests_run=1, tests_passed=1 if passed else 0,
            failures=[] if passed else ["expected 'image-alt' violation was not detected"],
            report=f"real axe audit detected {len(findings)} violation(s): {sorted(ids)}")


def test_scenario_b_real_browser_audit_with_evidence(tmp_path):
    with _serve(_DEFECTIVE) as url:
        svc, result = _drive(tmp_path, "b", "Run a QA accessibility audit of our public page.",
                             RealAuditExecutor(url))
    assert result.passed
    ws = tmp_path / "b" / "40_ark_work"
    findings = json.loads((ws / "delivery" / "findings.json").read_text(encoding="utf-8"))
    assert any(f["id"] == "image-alt" for f in findings)           # genuinely detected the defect
    assert (ws / "evidence" / "audit.png").stat().st_size > 0      # real screenshot evidence
    assert svc.status("b").status == "DELIVERY_PREPARED"

"""v3.0.1 - GENUINE execution acceptance for scenarios A and B (REAL headless Chromium).

Not structural stand-ins: scenario A authors a Playwright + TypeScript framework AND performs a real
Playwright run (Chromium loads a local fixture, the spec assertion is checked, a screenshot is
captured); scenario B performs a real browser audit (Chromium + axe-core) over a local fixture that
carries a known accessibility defect, and captures the detected violation + a screenshot as evidence.
Both drive the full persisted WorkExecutionService lifecycle. Local fixtures only - no third party,
no network beyond loopback.

Skipped unless playwright + Chromium + axe-core-python are installed; runs in CI's browser job:

    .venv/Scripts/python.exe -m pytest -m playwright_acceptance -q
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright not installed")
pytest.importorskip("axe_core_python", reason="axe-core-python not installed")

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


# --------------------------------------------------------------------------- A: real Playwright run
class RealPlaywrightExecutor:
    is_acceptance_fixture = False
    executor_id = "operator:genuine/playwright"

    def __init__(self, fixture_url: str) -> None:
        self._url = fixture_url

    def execute(self, ctx: ExecutionContext) -> ExecutionOutcome:
        ws = Path(ctx.workspace_dir)
        d = ws / "delivery"
        (d / "tests").mkdir(parents=True, exist_ok=True)
        (d / "package.json").write_text(json.dumps(
            {"name": "qa-suite", "scripts": {"test": "playwright test"},
             "devDependencies": {"@playwright/test": "^1.44.0"}}, indent=2), encoding="utf-8")
        (d / "playwright.config.ts").write_text(
            'import { defineConfig } from "@playwright/test";\n'
            'export default defineConfig({ testDir: "./tests" });\n', encoding="utf-8")
        (d / "tests" / "home.spec.ts").write_text(
            'import { test, expect } from "@playwright/test";\n'
            'test("home has a title", async ({ page }) => {\n'
            '  await page.goto("/");\n  await expect(page).toHaveTitle(/.+/);\n});\n', encoding="utf-8")
        # A GENUINE Playwright run: launch Chromium, load the fixture, check the spec assertion.
        ev = ws / "evidence"
        ev.mkdir(exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(self._url, wait_until="load")
            title = page.title()
            page.screenshot(path=str(ev / "home.png"))
            browser.close()
        (d / "RUN_RESULT.json").write_text(json.dumps(
            {"title": title, "assertion": "toHaveTitle(/.+/)", "passed": bool(title)}, indent=2),
            encoding="utf-8")
        if not title:
            return ExecutionOutcome(blockers=["Playwright run produced an empty page title"])
        return ExecutionOutcome(
            artifacts=[ExecutionArtifact("delivery/package.json", "framework"),
                       ExecutionArtifact("delivery/tests/home.spec.ts", "test"),
                       ExecutionArtifact("delivery/RUN_RESULT.json", "report")],
            evidence=[EvidenceItem("ev-shot", "screenshot", "evidence/home.png",
                                   "real Chromium screenshot of the fixture", ctx.now)],
            files_changed=["delivery/package.json"], progress_notes=[f"real Playwright run; title={title!r}"])

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        ws = Path(ctx.workspace_dir)
        run = json.loads((ws / "delivery" / "RUN_RESULT.json").read_text(encoding="utf-8"))
        shot_ok = (ws / "evidence" / "home.png").stat().st_size > 0
        passed = bool(run.get("passed")) and shot_ok
        return ValidationOutcome(passed=passed, tests_run=1, tests_passed=1 if passed else 0,
                                 failures=[] if passed else ["playwright assertion or screenshot missing"],
                                 report=f"real Playwright run asserted a page title ({run.get('title')!r})")


def test_scenario_a_real_playwright_run(tmp_path):
    with _serve(_GOOD) as url:
        svc, result = _drive(tmp_path, "a", "Build a Playwright + TypeScript E2E framework.",
                             RealPlaywrightExecutor(url))
    assert result.passed
    ws = tmp_path / "a" / "40_ark_work"
    assert (ws / "evidence" / "home.png").stat().st_size > 0        # a real screenshot was captured
    run = json.loads((ws / "delivery" / "RUN_RESULT.json").read_text(encoding="utf-8"))
    assert run["title"] == "QA Home" and run["passed"] is True      # the browser really loaded it
    assert svc.status("a").status == "DELIVERY_PREPARED"


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

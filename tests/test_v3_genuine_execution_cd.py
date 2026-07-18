"""v3.0.1 - GENUINE execution acceptance for scenarios C and D (deterministic; no browser).

Not structural stand-ins: scenario C runs REAL pytest commands that fail before the fix and pass
after it; scenario D authors a real OpenAPI fixture, starts a real localhost HTTP server that
implements it, and issues real positive + negative HTTP requests. Both drive the full persisted
WorkExecutionService lifecycle (analyze -> approve -> execute -> validate -> review -> delivery) and
assert the genuine artifacts, evidence, and validation the Factory recorded. No network beyond
loopback, no third party, no manufactured counts.
"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from core.orchestration.client_work import ClientWorkService
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionService
from core.schemas.work_execution import (
    EvidenceItem,
    ExecutionArtifact,
    ExecutionContext,
    ExecutionOutcome,
    ValidationOutcome,
)


def _drive(tmp_path, pid, brief, executor):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(brief, pid)
    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    svc.approve(pid, reviewer="operator", note="reviewed the plan")
    state, outcome = svc.execute(pid, executor)
    assert not outcome.blockers, outcome.blockers
    state, result = svc.validate(pid, executor)
    if result.passed:
        svc.review(pid, reviewer="operator", approved=True, note="verified")
        svc.prepare_delivery(pid)
    return svc, result


# --------------------------------------------------------------------------- C: real bug fix
class RealBugFixExecutor:
    is_acceptance_fixture = False
    executor_id = "operator:genuine/bug-fix"
    _BUGGY = "def add(a, b):\n    return a - b  # defect\n"
    _FIXED = "def add(a, b):\n    return a + b\n"
    _TEST = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"

    @staticmethod
    def _pytest(ws: Path):
        return subprocess.run(  # noqa: S603
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "test_calc.py"],
            cwd=str(ws), capture_output=True, text=True, timeout=300, check=False)

    def execute(self, ctx: ExecutionContext) -> ExecutionOutcome:
        ws = Path(ctx.workspace_dir)
        (ws / "calc.py").write_text(self._BUGGY, encoding="utf-8")
        (ws / "test_calc.py").write_text(self._TEST, encoding="utf-8")
        before = self._pytest(ws)                      # REAL pytest: must fail before the fix
        (ws / "evidence").mkdir(exist_ok=True)
        (ws / "evidence" / "failing_before.txt").write_text(
            f"$ pytest -q (before)\n(exit {before.returncode})\n\n{before.stdout}{before.stderr}",
            encoding="utf-8")
        if before.returncode == 0:
            return ExecutionOutcome(blockers=["defect did not reproduce (pytest passed before the fix)"])
        (ws / "calc.py").write_text(self._FIXED, encoding="utf-8")   # apply the bounded fix
        return ExecutionOutcome(
            artifacts=[ExecutionArtifact("calc.py", "fix"), ExecutionArtifact("test_calc.py", "test")],
            evidence=[EvidenceItem("ev-before", "test_output", "evidence/failing_before.txt",
                                   "pytest failing before the fix", ctx.now)],
            files_changed=["calc.py"], progress_notes=["reproduced failing pytest, applied the fix"])

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        ws = Path(ctx.workspace_dir)
        after = self._pytest(ws)                       # REAL pytest: must pass after the fix
        (ws / "evidence" / "passing_after.txt").write_text(
            f"$ pytest -q (after)\n(exit {after.returncode})\n\n{after.stdout}{after.stderr}",
            encoding="utf-8")
        passed = after.returncode == 0
        return ValidationOutcome(
            passed=passed, tests_run=1, tests_passed=1 if passed else 0,
            failures=[] if passed else [f"pytest still failing (exit {after.returncode})"],
            report="genuine pytest: failed before the fix, passed after", details={"after_rc": after.returncode})


def test_scenario_c_real_pytest_fails_before_passes_after(tmp_path):
    svc, result = _drive(tmp_path, "c", "Reproduce and fix a defect in a small Python module.",
                         RealBugFixExecutor())
    assert result.passed and result.tests_passed == 1
    ws = tmp_path / "c" / "40_ark_work"
    before = (ws / "evidence" / "failing_before.txt").read_text(encoding="utf-8")
    after = (ws / "evidence" / "passing_after.txt").read_text(encoding="utf-8")
    assert "(exit 0)" not in before.splitlines()[1] and "1 failed" in before   # genuinely failed first
    assert "(exit 0)" in after and "1 passed" in after                         # genuinely passed after
    assert svc.status("c").status == "READY_FOR_DELIVERY"


# --------------------------------------------------------------------------- D: real OpenAPI + HTTP
_OPENAPI = {
    "openapi": "3.0.0", "info": {"title": "Fixture API", "version": "1.0.0"},
    "paths": {
        "/health": {"get": {"responses": {"200": {"description": "ok"}}}},
        "/item/{id}": {"get": {"parameters": [{"name": "id", "in": "path", "required": True,
                                               "schema": {"type": "integer"}}],
                               "responses": {"200": {"description": "found"},
                                             "400": {"description": "bad id"}}}}}}


class _ApiHandler(BaseHTTPRequestHandler):
    def log_message(self, *_a):
        return

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path == "/health":
            code = 200
        elif path.startswith("/item/"):
            code = 200 if path.rsplit("/", 1)[-1].isdigit() else 400
        else:
            code = 404
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"status": code}).encode("utf-8"))


def _http_status(url: str) -> int:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code


class RealApiTestExecutor:
    is_acceptance_fixture = False
    executor_id = "operator:genuine/api-testing"
    _CASES = [{"name": "health ok", "path": "/health", "expect": 200},
              {"name": "item found", "path": "/item/1", "expect": 200},
              {"name": "item bad id (negative)", "path": "/item/abc", "expect": 400},
              {"name": "unknown path (negative)", "path": "/nope", "expect": 404}]

    def execute(self, ctx: ExecutionContext) -> ExecutionOutcome:
        d = Path(ctx.workspace_dir) / "delivery"
        d.mkdir(parents=True, exist_ok=True)
        (d / "openapi.json").write_text(json.dumps(_OPENAPI, indent=2), encoding="utf-8")
        (d / "api_test_plan.json").write_text(json.dumps({"cases": self._CASES}, indent=2), encoding="utf-8")
        return ExecutionOutcome(
            artifacts=[ExecutionArtifact("delivery/openapi.json", "report"),
                       ExecutionArtifact("delivery/api_test_plan.json", "api_tests")],
            files_changed=["delivery/openapi.json", "delivery/api_test_plan.json"],
            progress_notes=[f"authored an OpenAPI fixture + {len(self._CASES)} pos/neg cases"])

    def validate(self, ctx: ExecutionContext) -> ValidationOutcome:
        ws = Path(ctx.workspace_dir)
        cases = json.loads((ws / "delivery" / "api_test_plan.json").read_text(encoding="utf-8"))["cases"]
        server = ThreadingHTTPServer(("127.0.0.1", 0), _ApiHandler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        results, failures = [], []
        try:
            for c in cases:
                got = _http_status(base + c["path"])   # a REAL loopback HTTP request
                ok = got == c["expect"]
                results.append({**c, "got": got, "ok": ok})
                if not ok:
                    failures.append(f"{c['name']}: got {got}, expected {c['expect']}")
        finally:
            server.shutdown()
            server.server_close()
        (ws / "delivery" / "API_TEST_RESULTS.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        (ws / "evidence").mkdir(exist_ok=True)
        (ws / "evidence" / "api_run.txt").write_text(
            "\n".join(f"{r['path']} -> {r['got']} (expected {r['expect']}) {'OK' if r['ok'] else 'FAIL'}"
                      for r in results) + "\n", encoding="utf-8")
        passed = not failures
        return ValidationOutcome(passed=passed, tests_run=len(cases),
                                 tests_passed=sum(1 for r in results if r["ok"]), failures=failures,
                                 report="genuine localhost HTTP positive+negative tests against the fixture")


def test_scenario_d_real_openapi_localhost_http_pos_neg(tmp_path):
    svc, result = _drive(tmp_path, "d", "Build API tests from our OpenAPI spec (positive + negative).",
                         RealApiTestExecutor())
    assert result.passed and result.tests_run == 4 and result.tests_passed == 4
    ws = tmp_path / "d" / "40_ark_work"
    results = json.loads((ws / "delivery" / "API_TEST_RESULTS.json").read_text(encoding="utf-8"))
    got = {r["path"]: r["got"] for r in results}
    assert got == {"/health": 200, "/item/1": 200, "/item/abc": 400, "/nope": 404}   # real responses
    assert svc.status("d").status == "READY_FOR_DELIVERY"

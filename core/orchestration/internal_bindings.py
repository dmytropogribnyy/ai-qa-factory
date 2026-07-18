"""Internal tool binding registry (v3.0.2 M4).

Maps an internal tool id to a PRODUCTION module + callable adapter + a bounded health check.
A tool exceeds ``declared`` only when ALL of these hold:

  1. its production module imports;
  2. the expected callable/adapter attribute exists on it;
  3. the adapter is callable (a valid contract);
  4. a bounded health check passes.

Test files are NEVER a runtime binding. Package importability is distinguished from
browser-runtime readiness, and local fixture exercise is distinguished from live acceptance -
no binding here ever reports ``live-accepted``. If no genuine production runner exists for a
capability, that tool stays ``declared``.
"""
from __future__ import annotations

import importlib
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Tuple


@dataclass(frozen=True)
class BindingResult:
    ok: bool
    readiness: str          # readiness to report (only meaningful; 'declared' when not ok)
    detail: str             # honest check_result text
    setup: str = ""         # setup instruction to surface when not ok


@dataclass(frozen=True)
class InternalBinding:
    """A production binding for one internal tool id."""
    tool_id: str
    module: str                                  # importable PRODUCTION module (never a tests/ file)
    attr: str                                    # callable adapter attribute on that module
    readiness_when_ok: str                       # "fixture-tested" | "health-checked"
    health: Callable[[Any], Tuple[bool, str]]    # bounded check: (module) -> (ok, detail)
    setup: str = ""
    requires_modules: Tuple[str, ...] = field(default_factory=tuple)  # extra importable deps

    def evaluate(self, *, module_available: Callable[[str], bool],
                 import_module: Callable[[str], Any] = importlib.import_module) -> BindingResult:
        # 1. optional dependency importability (distinct from browser/tool runtime readiness).
        missing = [m for m in self.requires_modules if not module_available(m)]
        if missing:
            return BindingResult(False, "declared",
                                 f"dependency not importable: {', '.join(missing)}", self.setup)
        # 2. the production module itself must be importable.
        if not module_available(self.module):
            return BindingResult(False, "declared",
                                 f"production module '{self.module}' not importable", self.setup)
        try:
            mod = import_module(self.module)
        except Exception as exc:  # defensive: a present-but-broken module is honestly 'declared'
            return BindingResult(False, "declared",
                                 f"production module '{self.module}' failed to import: {exc}",
                                 self.setup)
        # 3. the callable/adapter must exist on it.
        adapter = getattr(mod, self.attr, None)
        if adapter is None:
            return BindingResult(False, "declared",
                                 f"adapter '{self.attr}' not found in '{self.module}'", self.setup)
        # 4. the adapter contract: it must be callable (class or function).
        if not callable(adapter):
            return BindingResult(False, "declared",
                                 f"adapter '{self.module}.{self.attr}' is not callable", self.setup)
        # 5. a bounded health check must pass.
        try:
            ok, detail = self.health(mod)
        except Exception as exc:
            return BindingResult(False, "declared", f"health check raised: {exc}", self.setup)
        if not ok:
            return BindingResult(False, "declared", f"health check failed: {detail}", self.setup)
        return BindingResult(True, self.readiness_when_ok, detail, "")


# ---------------------------------------------------------------------------------------------
# Health checks (bounded; local only; no network, no browser launch, no side effects in the repo)
# ---------------------------------------------------------------------------------------------

def _api_runner_health(module: Any) -> Tuple[bool, str]:
    """Genuinely exercise the production API pipeline against a tiny in-memory OpenAPI fixture:
    parse it with APIContractImporter, then generate stubs with APITestGenerator."""
    import json
    import tempfile
    from pathlib import Path

    from core.api_test_generator import APITestGenerator

    spec = {"openapi": "3.0.0", "info": {"title": "healthcheck", "version": "1.0.0"},
            "paths": {"/ping": {"get": {"responses": {"200": {"description": "ok"}}}}}}
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "openapi.json"
        p.write_text(json.dumps(spec), encoding="utf-8")
        report = module.APIContractImporter().analyze("healthcheck", str(p))
    if report.total_endpoints < 1 or report.parse_errors:
        return False, (f"importer returned {report.total_endpoints} endpoint(s), "
                       f"errors={report.parse_errors}")
    if report.safe_readonly_count < 1:
        return False, "no safe read-only endpoint classified from the fixture"
    gen = APITestGenerator().generate(report)
    if gen.total_test_stubs < 1:
        return False, "generator produced no test stubs for a safe endpoint"
    return True, ("APIContractImporter parsed a fixture OpenAPI (1 safe endpoint) and "
                  "APITestGenerator produced stubs in-process")


def _playwright_runner_health(module: Any) -> Tuple[bool, str]:
    """Confirm the in-repo Playwright runner adapter is present and valid. Browser-runtime
    readiness (Node/npx + Chromium) and local-fixture acceptance are verified separately in the
    browser CI job - never claimed as live-accepted here."""
    runner = getattr(module, "TestRunner", None)
    if runner is None or not callable(getattr(runner, "run_playwright", None)):
        return False, "TestRunner.run_playwright adapter is missing"
    return True, ("in-repo Playwright runner binding present (tools.test_runner:TestRunner); "
                  "browser-runtime (Node/Chromium) verified by the browser acceptance job, "
                  "not here - never live-accepted")


_BINDINGS: Dict[str, InternalBinding] = {
    # A real production pipeline exists for API testing -> exercised against a fixture in-process.
    "api_runner_internal": InternalBinding(
        tool_id="api_runner_internal", module="core.api_contract_importer",
        attr="APIContractImporter", readiness_when_ok="fixture-tested",
        health=_api_runner_health,
        setup="internal API runner ships with the Factory; no setup required"),
    # A real production runner exists (npx playwright test) -> binding present = health-checked;
    # the browser toolchain is a separate, honestly-reported readiness.
    "playwright_internal": InternalBinding(
        tool_id="playwright_internal", module="tools.test_runner",
        attr="TestRunner", readiness_when_ok="health-checked",
        health=_playwright_runner_health,
        setup="install Node.js + run `npx playwright install chromium` for browser runtime"),
}


def binding_for(tool_id: str) -> InternalBinding | None:
    return _BINDINGS.get(tool_id)

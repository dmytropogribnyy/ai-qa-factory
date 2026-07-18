"""v3.0.2 M4 - the internal binding registry: honest readiness, never a test-file binding.

A tool exceeds 'declared' only when its production module imports, the callable adapter exists
and is callable, and a bounded health check passes. A missing callable or a failing/raising health
check honestly yields 'declared' with a reason. No binding points at a tests/ file.
"""
from __future__ import annotations

from core.orchestration.internal_bindings import InternalBinding, binding_for


def _ok_health(_mod):
    return True, "healthy"


def test_registered_bindings_never_point_at_test_files():
    import importlib

    for tid in ("api_runner_internal", "playwright_internal"):
        b = binding_for(tid)
        assert b is not None
        # The binding must resolve to a real, importable PRODUCTION module - not the tests package.
        parts = b.module.split(".")
        assert "tests" not in parts, b.module
        mod = importlib.import_module(b.module)
        assert "tests" not in (mod.__file__ or "").replace("\\", "/").split("/"), b.module
        assert callable(getattr(mod, b.attr, None)), f"{b.module}.{b.attr} not callable"


def test_api_runner_binding_is_a_real_production_module():
    b = binding_for("api_runner_internal")
    assert b.module == "core.api_contract_importer" and b.attr == "APIContractImporter"
    res = b.evaluate(module_available=lambda _n: True)
    assert res.ok and res.readiness == "fixture-tested"
    assert "APIContractImporter" in res.detail


def test_playwright_binding_is_health_checked_not_live():
    b = binding_for("playwright_internal")
    assert b.module == "tools.test_runner" and b.attr == "TestRunner"
    res = b.evaluate(module_available=lambda _n: True)
    assert res.ok and res.readiness == "health-checked"
    assert "never live-accepted" in res.detail


def test_dependency_present_but_no_binding_stays_declared():
    # A binding that requires a dependency which is 'available' but whose production module is
    # reported unavailable stays declared (dependency alone is never enough).
    b = InternalBinding(tool_id="x", module="some.production.mod", attr="Runner",
                        readiness_when_ok="fixture-tested", health=_ok_health,
                        requires_modules=("json",))
    res = b.evaluate(module_available=lambda n: n == "json")   # dep ok, module not importable
    assert not res.ok and res.readiness == "declared"
    assert "not importable" in res.detail


def test_missing_callable_is_declared():
    b = InternalBinding(tool_id="x", module="core.api_contract_importer", attr="NoSuchAdapter",
                        readiness_when_ok="fixture-tested", health=_ok_health)
    res = b.evaluate(module_available=lambda _n: True)
    assert not res.ok and res.readiness == "declared"
    assert "not found" in res.detail


def test_non_callable_adapter_is_declared():
    # __doc__ exists on the module but is not callable.
    b = InternalBinding(tool_id="x", module="core.api_contract_importer", attr="__doc__",
                        readiness_when_ok="fixture-tested", health=_ok_health)
    res = b.evaluate(module_available=lambda _n: True)
    assert not res.ok and "not callable" in res.detail


def test_failing_health_check_is_declared_with_reason():
    b = InternalBinding(tool_id="x", module="core.api_contract_importer", attr="APIContractImporter",
                        readiness_when_ok="fixture-tested",
                        health=lambda _m: (False, "endpoint parse returned nothing"))
    res = b.evaluate(module_available=lambda _n: True)
    assert not res.ok and res.readiness == "declared"
    assert "endpoint parse returned nothing" in res.detail


def test_raising_health_check_is_declared_not_crash():
    def _boom(_m):
        raise RuntimeError("kaboom")

    b = InternalBinding(tool_id="x", module="core.api_contract_importer", attr="APIContractImporter",
                        readiness_when_ok="fixture-tested", health=_boom)
    res = b.evaluate(module_available=lambda _n: True)
    assert not res.ok and "health check raised" in res.detail

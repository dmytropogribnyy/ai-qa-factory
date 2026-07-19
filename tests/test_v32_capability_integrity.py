"""v3.2 P0 (items 18-25) - honest component/provider readiness + typed access-id gaps.

The matrix never shows a multi-provider row as Live/Fixture Verified when only one component is
verified, and a service is not "ready" while a required client-owned access prerequisite is missing.
"""
from __future__ import annotations

from core.orchestration.access_bootstrap import AccessBootstrap
from core.orchestration.service_capability import (
    aggregate_readiness,
    get_service,
    service_view,
    snapshot,
)
from core.orchestration.tool_gap import plan_tools


# ---------------------------------------------------------------- component/provider readiness (18-19)
def test_cicd_row_is_never_live_verified_when_only_github_is():
    view = service_view(get_service("cicd"), detected={})
    assert view["readiness"] == "Partially Verified"          # NOT "Live Verified"
    comps = {c["component_id"]: c["readiness"] for c in view["components"]}
    assert comps["github_actions"] == "Live Verified"
    assert comps["azure_devops"] == "Needs Client"
    assert comps["gitlab_ci"] == "Needs Client"
    assert comps["jenkins"] == "Needs Client"


def test_docker_aws_row_is_not_verified_on_docker_alone():
    # Even with Docker present, the aggregate is Partially Verified because AWS is Needs Client.
    view = service_view(get_service("docker_aws"), detected={"docker": "Runtime Available"})
    assert view["readiness"] == "Partially Verified"
    comps = {c["component_id"]: c["readiness"] for c in view["components"]}
    assert comps["docker"] == "Runtime Available" and comps["aws"] == "Needs Client"


def test_db_engines_have_honest_component_readiness():
    view = service_view(get_service("ui_api_db_validation"),
                        detected={"postgresql": "Needs Client", "mysql": "Needs Client",
                                  "sqlite": "Fixture Verified"})
    comps = {c["component_id"]: c["readiness"] for c in view["components"]}
    assert comps["sqlite"] == "Fixture Verified"
    assert comps["postgresql"] == "Needs Client" and comps["mysql"] == "Needs Client"
    assert view["readiness"] == "Partially Verified"


def test_aggregate_readiness_is_conservative():
    from core.orchestration.service_capability import Component as C
    assert aggregate_readiness([], "Declared") == "Declared"
    assert aggregate_readiness([C("a", "A", "Live Verified"), C("b", "B", "Live Verified")],
                               "x") == "Live Verified"
    assert aggregate_readiness([C("a", "A", "Live Verified"), C("b", "B", "Needs Client")],
                               "x") == "Partially Verified"


def test_snapshot_v2_schema_and_no_overstated_rows():
    snap = snapshot()
    assert snap["schema"].endswith("/v2")
    by_id = {s["service_id"]: s for s in snap["services"]}
    # These two multi-provider rows must never present as Live/Fixture Verified in the aggregate.
    assert by_id["cicd"]["readiness"] == "Partially Verified"
    assert by_id["docker_aws"]["readiness"] == "Partially Verified"
    # bdd is now genuinely executable, not merely Declared.
    assert by_id["bdd"]["readiness"] == "Fixture Verified"
    # n8n/Make stays Needs Client (item 23).
    assert by_id["workflow_automation"]["readiness"] == "Needs Client"


# ---------------------------------------------------------------- typed access-id gaps (item 20)
class _FakeAccess(AccessBootstrap):
    """An AccessBootstrap whose integrations we control, to prove access resolution deterministically."""

    def __init__(self, overrides):
        super().__init__()
        self._overrides = overrides

    def inspect(self):
        items = super().inspect()
        for it in items:
            if it.id in self._overrides:
                it.readiness = self._overrides[it.id]
        return items


def test_missing_client_access_makes_service_not_ready_with_exact_action():
    # migration requires the client repository; without it the service is NOT ready and the access
    # gap carries the exact client action (regardless of whether local tools are also missing).
    report = plan_tools("migration", access=AccessBootstrap())
    assert report.ready is False
    ids = {g["access_id"]: g for g in report.access_gaps}
    assert "client_repository" in ids
    gap = ids["client_repository"]
    assert gap["owner"] == "client" and gap["readiness"] == "Needs Client" and gap["action"]
    assert report.operator_action           # a precise next action is always surfaced when blocked


def test_provided_client_access_clears_the_access_gap():
    # When the client repository is genuinely provided (satisfied readiness) and tools are ready,
    # the access gap disappears. We satisfy both the tool and the access prerequisite.
    from core.orchestration.tool_broker import ToolBroker

    class _AllToolsReady(ToolBroker):
        def discover(self):
            from core.orchestration.tool_broker import ToolStatus
            return [ToolStatus(id=t, name=t, domain="", readiness="fixture-tested",
                               capabilities=[], auth_requirement="", fallback="")
                    for t in get_service("migration").required_tools]

    access = _FakeAccess({"client_repository": "Runtime Verified"})
    report = plan_tools("migration", broker=_AllToolsReady(clock=lambda: ""), access=access)
    assert not report.access_gaps and not report.gaps and report.ready is True


def test_technical_writing_has_no_client_access_prerequisite():
    # technical writing needs only operator review (no client-owned access), so access never blocks it.
    report = plan_tools("technical_writing", access=AccessBootstrap())
    assert report.access_gaps == []

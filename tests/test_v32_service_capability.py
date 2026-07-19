"""v3.2 Section 7 - the Service Capability Matrix is complete and honest."""
from __future__ import annotations

from core.orchestration.service_capability import (
    READINESS,
    SERVICE_CAPABILITIES,
    SCHEMA_VERSION,
    snapshot,
)

_MANDATORY = {
    "playwright_framework", "migration", "ui_api_db_validation", "cicd", "stabilization",
    "ai_mvp", "bdd", "website_qa", "workflow_automation", "technical_writing", "legal_tech",
    "docker_aws",
}


def test_all_mandatory_services_present():
    ids = {s.service_id for s in SERVICE_CAPABILITIES}
    assert _MANDATORY <= ids


def test_every_service_is_fully_specified_and_honest():
    for s in SERVICE_CAPABILITIES:
        assert s.name and s.description and s.modes
        assert s.readiness in READINESS
        assert s.operator_action_if_blocked            # an exact action always exists
        assert s.fallback and s.safety_boundaries
        # A "Verified" readiness must cite acceptance evidence.
        if s.readiness in ("Fixture Verified", "Live Verified", "Runtime Verified"):
            assert s.acceptance_evidence, s.service_id


def test_honesty_boundaries():
    by = {s.service_id: s for s in SERVICE_CAPABILITIES}
    # The CI/CD ROW is never shown as Live Verified: only its GitHub Actions component is (item 19).
    assert by["cicd"].readiness == "Partially Verified"
    comps = {c.component_id: c.readiness for c in by["cicd"].components}
    assert comps["github_actions"] == "Live Verified"
    assert comps["azure_devops"] == "Needs Client" and comps["jenkins"] == "Needs Client"
    assert any("GitHub" in e for e in by["cicd"].acceptance_evidence)
    assert any("never shown as live verified" in b.lower() for b in by["cicd"].safety_boundaries)
    # n8n/Make needs the real client runtime; never Live Verified without it.
    assert by["workflow_automation"].readiness == "Needs Client"
    # Legal-tech requires operator review; never a legal certification.
    assert by["legal_tech"].readiness == "Needs Operator"
    assert any("legal certification" in b.lower() or "not a substitute" in b.lower()
               for b in by["legal_tech"].safety_boundaries)
    # DB mutation is gated.
    assert any("MUTATION" in b or "mutation" in b for b in by["ui_api_db_validation"].safety_boundaries)


def test_snapshot_shape():
    snap = snapshot()
    assert snap["schema"] == SCHEMA_VERSION and snap["service_count"] == len(SERVICE_CAPABILITIES)
    assert all("operator_action_if_blocked" in s for s in snap["services"])

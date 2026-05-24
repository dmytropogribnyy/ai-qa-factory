"""
Integration schema tests — Phase 1B-n8n.

Covers:
- IntegrationEndpoint safe defaults
- IntegrationEvent safe defaults
- IntegrationPolicy safe defaults
- to_dict / from_dict round-trips
- Integration constants
- __init__.py exports
"""
from __future__ import annotations

from core.schemas.integration import IntegrationEndpoint, IntegrationEvent, IntegrationPolicy
from core.schemas.constants import (
    INTEGRATION_PROVIDERS,
    INTEGRATION_DIRECTIONS,
    INTEGRATION_EVENT_TYPES,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestIntegrationConstants:
    def test_providers_frozenset(self):
        assert isinstance(INTEGRATION_PROVIDERS, frozenset)
        for p in ("n8n", "make", "zapier", "github_actions", "slack", "telegram",
                  "email", "google_drive", "jira", "linear", "notion",
                  "browserstack", "checkly", "unknown"):
            assert p in INTEGRATION_PROVIDERS

    def test_directions_frozenset(self):
        assert isinstance(INTEGRATION_DIRECTIONS, frozenset)
        for d in ("outbound_event", "inbound_webhook", "bidirectional", "manual_export"):
            assert d in INTEGRATION_DIRECTIONS

    def test_event_types_frozenset(self):
        assert isinstance(INTEGRATION_EVENT_TYPES, frozenset)
        for t in ("project_created", "approval_required", "approval_granted",
                  "approval_rejected", "report_generated", "client_delivery_ready",
                  "client_delivery_blocked", "quality_gate_passed", "quality_gate_failed",
                  "ai_fallback_detected", "blocker_created", "admin_attention_required"):
            assert t in INTEGRATION_EVENT_TYPES


# ---------------------------------------------------------------------------
# IntegrationEndpoint
# ---------------------------------------------------------------------------

class TestIntegrationEndpoint:
    def test_safe_defaults(self):
        ep = IntegrationEndpoint()
        assert ep.enabled is False
        assert ep.requires_approval is True
        assert ep.contains_sensitive_config is False
        assert ep.provider == "unknown"
        assert ep.direction == "outbound_event"
        assert ep.url_ref is None
        assert ep.auth_ref_id is None
        assert ep.notes == []

    def test_id_auto_generated(self):
        ep = IntegrationEndpoint()
        assert len(ep.id) > 0

    def test_url_ref_is_reference_not_live_url(self):
        ep = IntegrationEndpoint(url_ref="N8N_WEBHOOK_URL_ENV_VAR")
        assert ep.enabled is False
        assert ep.url_ref == "N8N_WEBHOOK_URL_ENV_VAR"

    def test_auth_ref_id_is_reference(self):
        ep = IntegrationEndpoint(auth_ref_id="cred-ref-001")
        assert ep.auth_ref_id == "cred-ref-001"
        assert ep.enabled is False

    def test_roundtrip(self):
        ep = IntegrationEndpoint(
            provider="n8n",
            direction="outbound_event",
            label="QA workflow trigger",
            url_ref="N8N_APPROVAL_WEBHOOK",
            enabled=False,
            notes=["Configured but not yet enabled"],
        )
        d = ep.to_dict()
        ep2 = IntegrationEndpoint.from_dict(d)
        assert ep2.provider == "n8n"
        assert ep2.direction == "outbound_event"
        assert ep2.url_ref == "N8N_APPROVAL_WEBHOOK"
        assert ep2.enabled is False
        assert ep2.requires_approval is True

    def test_from_dict_ignores_unknown_fields(self):
        ep = IntegrationEndpoint.from_dict({"provider": "slack", "unknown_key": "ignored"})
        assert ep.provider == "slack"


# ---------------------------------------------------------------------------
# IntegrationEvent
# ---------------------------------------------------------------------------

class TestIntegrationEvent:
    def test_safe_defaults(self):
        ev = IntegrationEvent()
        assert ev.delivered is False
        assert ev.contains_sensitive_data is False
        assert ev.client_visible is False
        assert ev.delivery_error is None
        assert ev.provider == "n8n"
        assert ev.event_type == "project_created"
        assert ev.payload_ref_path is None
        assert ev.notes == []

    def test_id_auto_generated(self):
        ev = IntegrationEvent()
        assert len(ev.id) > 0

    def test_payload_summary_is_safe_metadata(self):
        ev = IntegrationEvent(
            project_id="p1",
            event_type="approval_required",
            payload_summary="Approval required for run-against-staging on project p1",
        )
        assert ev.contains_sensitive_data is False
        assert ev.delivered is False
        assert ev.client_visible is False

    def test_roundtrip(self):
        ev = IntegrationEvent(
            provider="slack",
            event_type="report_generated",
            project_id="p1",
            payload_summary="Report generated for project p1",
            contains_sensitive_data=False,
            client_visible=False,
        )
        d = ev.to_dict()
        ev2 = IntegrationEvent.from_dict(d)
        assert ev2.provider == "slack"
        assert ev2.event_type == "report_generated"
        assert ev2.delivered is False
        assert ev2.client_visible is False

    def test_delivery_error_optional(self):
        ev = IntegrationEvent(delivery_error="Connection timeout")
        assert ev.delivery_error == "Connection timeout"
        assert ev.delivered is False


# ---------------------------------------------------------------------------
# IntegrationPolicy
# ---------------------------------------------------------------------------

class TestIntegrationPolicy:
    def test_safe_defaults_block_all_external(self):
        p = IntegrationPolicy(project_id="p1")
        assert p.allow_outbound_events is False
        assert p.allow_inbound_webhooks is False
        assert p.require_approval_for_external_calls is True
        assert p.redact_sensitive_payloads is True
        assert p.allowed_providers == []
        assert p.blocked_event_types == []

    def test_no_provider_allowed_by_default(self):
        p = IntegrationPolicy(project_id="p1")
        assert len(p.allowed_providers) == 0

    def test_roundtrip(self):
        p = IntegrationPolicy(
            project_id="p1",
            allow_outbound_events=True,
            allowed_providers=["n8n", "slack"],
            blocked_event_types=["client_delivery_ready"],
            notes=["Approved for staging notifications only"],
        )
        d = p.to_dict()
        p2 = IntegrationPolicy.from_dict(d)
        assert p2.allow_outbound_events is True
        assert p2.allow_inbound_webhooks is False
        assert "n8n" in p2.allowed_providers
        assert "slack" in p2.allowed_providers
        assert p2.redact_sensitive_payloads is True
        assert p2.notes == ["Approved for staging notifications only"]

    def test_blocked_event_types_customisable(self):
        p = IntegrationPolicy(
            project_id="p1",
            blocked_event_types=["client_delivery_ready", "report_generated"],
        )
        assert "client_delivery_ready" in p.blocked_event_types


# ---------------------------------------------------------------------------
# __init__.py exports
# ---------------------------------------------------------------------------

class TestIntegrationPackageExports:
    def test_integration_classes_importable(self):
        import core.schemas as s
        assert s.IntegrationEndpoint is not None
        assert s.IntegrationEvent is not None
        assert s.IntegrationPolicy is not None

    def test_integration_constants_importable(self):
        import core.schemas as s
        assert "n8n" in s.INTEGRATION_PROVIDERS
        assert "outbound_event" in s.INTEGRATION_DIRECTIONS
        assert "approval_required" in s.INTEGRATION_EVENT_TYPES

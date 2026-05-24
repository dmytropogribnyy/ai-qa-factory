from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.schemas.base import SchemaMixin

# Hard rules for this module:
# - url_ref and auth_ref_id are reference labels only, NOT actual URLs with secrets or tokens.
# - IntegrationPolicy.allow_outbound_events = False by default — no external calls without approval.
# - All integration payloads must be redacted before delivery.
# - This module is schema/config foundation only. No runtime HTTP calls in this phase.


@dataclass
class IntegrationEndpoint(SchemaMixin):
    """Reference descriptor for an optional external integration endpoint.

    url_ref holds a label or env-var name pointing to the URL — never a real
    webhook URL containing tokens or secrets.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    provider: str = "unknown"
    direction: str = "outbound_event"
    label: str = ""
    url_ref: Optional[str] = None          # env var name or reference label, not a live URL
    auth_ref_id: Optional[str] = None      # CredentialReference.id or env var name
    enabled: bool = False
    requires_approval: bool = True
    contains_sensitive_config: bool = False
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> IntegrationEndpoint:
        return super().from_dict(data)


@dataclass
class IntegrationEvent(SchemaMixin):
    """Metadata record for one integration event emitted or queued by the workbench."""

    id: str = field(default_factory=lambda: str(uuid4()))
    provider: str = "n8n"
    event_type: str = "project_created"
    project_id: str = ""
    payload_summary: str = ""              # short safe metadata, no raw sensitive content
    payload_ref_path: Optional[str] = None  # path to local redacted payload artifact (future)
    contains_sensitive_data: bool = False
    client_visible: bool = False
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    delivered: bool = False
    delivery_error: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> IntegrationEvent:
        return super().from_dict(data)


@dataclass
class IntegrationPolicy(SchemaMixin):
    """Project-level policy governing external integration calls. All safe defaults."""

    project_id: str = ""
    allow_outbound_events: bool = False
    allow_inbound_webhooks: bool = False
    require_approval_for_external_calls: bool = True
    redact_sensitive_payloads: bool = True
    allowed_providers: List[str] = field(default_factory=list)
    blocked_event_types: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> IntegrationPolicy:
        return super().from_dict(data)

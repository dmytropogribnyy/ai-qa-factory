from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import uuid4

from core.schemas.base import SchemaMixin

# Hard rule: this module must NEVER store raw secret values.
# secret_names holds only environment variable names or reference labels,
# never actual passwords, tokens, cookies, API keys, or any secret value.


@dataclass
class CredentialReference(SchemaMixin):
    """Metadata reference for a credential used in testing.

    Stores only the *name* of the secret (e.g. the env var name), never its
    actual value. raw_value_stored must remain False at all times.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    credential_type: str = "unknown"
    label: str = ""
    target_ref_id: Optional[str] = None
    environment_type: str = "unknown"
    storage_mode: str = "not_stored"
    # Names of env vars or secret references — NOT actual secret values.
    secret_names: List[str] = field(default_factory=list)
    raw_value_stored: bool = False          # must never be set to True
    requires_approval_before_use: bool = True
    approved_for_use: bool = False
    expires_after_run: bool = True
    masked_in_logs: bool = True
    # Web/mobile surface context
    app_surface: str = "unknown"
    auth_mechanism: str = "unknown"
    auth_provider: Optional[str] = None
    mobile_auth_context: Optional[str] = None
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CredentialReference:
        return super().from_dict(data)


@dataclass
class CredentialPolicy(SchemaMixin):
    """Project-level policy governing how credentials may be used in testing."""

    project_id: str = ""
    allow_credential_use: bool = False
    allow_production_credentials: bool = False
    require_explicit_approval: bool = True
    require_test_account: bool = True
    require_sandbox_for_payment: bool = True
    prohibit_destructive_account_actions: bool = True
    mask_secrets_in_outputs: bool = True
    block_client_delivery_if_secrets_detected: bool = True
    allowed_storage_modes: List[str] = field(
        default_factory=lambda: ["env_var", "env_file", "secure_prompt", "not_stored"]
    )
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CredentialPolicy:
        return super().from_dict(data)


@dataclass
class CredentialUseApproval(SchemaMixin):
    """Recorded approval for using a specific credential in a specific action."""

    credential_ref_id: str = ""
    action_id: str = ""
    approved: bool = False
    approved_by: Optional[str] = None
    approved_at: Optional[str] = None
    approval_scope: str = "none"
    allowed_actions: List[str] = field(default_factory=list)
    # Destructive account actions are forbidden by default.
    forbidden_actions: List[str] = field(
        default_factory=lambda: [
            "change_password",
            "delete_account",
            "change_billing",
            "create_real_payment",
            "modify_production_data",
        ]
    )
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CredentialUseApproval:
        return super().from_dict(data)

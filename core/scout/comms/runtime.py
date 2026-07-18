"""Production runtime provider registry (Final Operator-Path Hotfix, v2.0.2).

The public ``scout send`` command uses THIS registry (not the deterministic demo registry): it wires
the genuine Gmail provider (``gmail_personal``) into the operator path with the real HTTP transport,
the OAuth token provider, and an env-driven readiness status provider — so preflight can block before
any approval is consumed. ``local_sink`` stays available for demos and testing. Resend is optional,
secondary, and registered only when a verified darrowcode.com sender is configured. The transport /
token / status are injectable so deterministic tests drive the full CLI path with a fake transport
and fake credentials (no network, no Google client library, no real send).
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

from core.scout.comms.gmail import GmailProvider, gmail_config_from_env, real_gmail_transport
from core.scout.comms.gmail_oauth import build_token_provider, gmail_status, prove_current_identity
from core.scout.comms.providers import DeterministicLocalSinkProvider, ProviderRegistry


def build_runtime_provider_registry(
    sink_dir: str, *, env: Optional[Dict[str, str]] = None,
    gmail_transport: Optional[Callable[[str, str], Dict[str, Any]]] = None,
    gmail_token_provider: Optional[Callable[[], str]] = None,
    gmail_status_provider: Optional[Callable[[], Dict[str, Any]]] = None,
    gmail_identity_prover: Optional[Callable[[], str]] = None,
    include_resend: bool = True,
) -> ProviderRegistry:
    reg = ProviderRegistry()
    reg.register(DeterministicLocalSinkProvider(sink_dir))

    cfg = gmail_config_from_env(env)
    reg.register(GmailProvider(
        from_email=cfg["from_email"], from_name=cfg["from_name"],
        expected_account=cfg["expected_account"],
        transport=gmail_transport or real_gmail_transport,
        token_provider=gmail_token_provider or build_token_provider(cfg["token_json"]),
        status_provider=gmail_status_provider or (lambda: gmail_status(cfg)),
        identity_prover=gmail_identity_prover or (lambda: prove_current_identity(cfg))))

    # Resend is optional/secondary and never on the critical path — register only when a verified
    # darrowcode.com sender is configured; a misconfiguration must not break the runtime registry.
    if include_resend:
        try:
            from core.scout.comms.resend import (
                ResendProvider,
                real_resend_transport,
                resend_config_from_env,
            )
            rc = resend_config_from_env(env)
            if rc["from_email"]:
                reg.register(ResendProvider(
                    from_email=rc["from_email"], reply_to=rc["reply_to"],
                    transport=real_resend_transport,
                    api_key_provider=lambda: os.environ.get("RESEND_API_KEY", "")))
        except Exception:  # noqa: BLE001 - Resend is optional; never break the primary path
            pass
    return reg

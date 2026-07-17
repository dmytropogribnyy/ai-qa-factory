"""Outreach controls (Final Phase II).

Sending is disabled by default. Controls (global / per-campaign / per-provider / per-channel /
pause / global-kill / recipient allowlist) are checked at approval, at pre-send revalidation, at
reservation, and immediately before the provider call. A kill/disable added after approval but
before the provider call blocks the send.
"""
from __future__ import annotations

from typing import List, Tuple

from core.scout.comms.repository import CommsRepository

_BLOCKING = frozenset({"DISABLED", "PAUSED", "KILLED"})


def sending_allowed(repo: CommsRepository, *, campaign_id: str, provider_id: str, channel: str,
                    recipient: str, live: bool) -> Tuple[bool, List[str]]:
    """Return (allowed, blockers). Fail-closed: global outreach is DISABLED by default."""
    blockers: List[str] = []
    if repo.get_control("__global_outreach__") in _BLOCKING:
        blockers.append("global_outreach_disabled")
    if repo.get_control("__kill__") == "KILLED":
        blockers.append("global_kill")
    if repo.get_control(f"campaign:{campaign_id}") in _BLOCKING:
        blockers.append("campaign_disabled")
    if repo.get_control(f"provider:{provider_id}") in _BLOCKING:
        blockers.append("provider_disabled")
    if repo.get_control(f"channel:{channel}") in _BLOCKING:
        blockers.append("channel_disabled")
    # Live sending additionally requires the recipient to be on the allowlist.
    if live and not repo.is_allowlisted(recipient):
        blockers.append("recipient_not_allowlisted")
    return (not blockers), blockers


def global_kill(repo: CommsRepository) -> None:
    repo.set_control("__kill__", "KILLED")

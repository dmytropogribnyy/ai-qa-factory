"""Daily outreach safety limits for real senders (Final Independent Acceptance, v2.0.1).

Conservative defaults for the personal Gmail sender (and any real provider): at most a small number
of NEW outreach messages per day, a configurable hard ceiling, and an optional per-campaign ceiling.
Counts are transactional and derived from authoritative provider-invocation records (an outbound
message that reached the provider). Fixture/local-sink sends never consume the real ceiling. There
is no auto-send scheduler and no auto-retry; each message is one recipient with no batch API.
"""
from __future__ import annotations

from typing import List

from core.scout.comms.repository import CommsRepository

# Providers whose sends count against the real daily ceiling.
REAL_PROVIDERS = frozenset({"gmail_personal", "resend_email"})
# A send is counted once it has (attempted to) reach the provider.
_COUNTED_STATES = ("PROVIDER_CALL_IN_PROGRESS", "ACCEPTED", "DELIVERED", "REPLIED", "OPTED_OUT",
                   "BOUNCED", "OUTCOME_UNKNOWN")
DEFAULT_DAILY_MAX = 5
HARD_DAILY_CEILING = 10


def _day(iso: str) -> str:
    return (iso or "")[:10]


def _configured_daily_max(comms: CommsRepository, provider_id: str) -> int:
    override = comms.get_control_extra(f"daily_max:{provider_id}").get("max")
    try:
        override = int(override)
    except (TypeError, ValueError):
        override = DEFAULT_DAILY_MAX
    return max(0, min(override, HARD_DAILY_CEILING))


def real_send_count_today(comms: CommsRepository, provider_id: str, now: str) -> int:
    day = _day(now)
    qs = ",".join("?" for _ in _COUNTED_STATES)
    rows = comms.db.query(
        f"SELECT created_at, sent_at FROM outbound_messages WHERE provider_id=? AND state IN ({qs})",
        (provider_id, *_COUNTED_STATES))
    return sum(1 for r in rows if _day(r["sent_at"] or r["created_at"]) == day)


def campaign_send_count_today(comms: CommsRepository, campaign_id: str, now: str) -> int:
    day = _day(now)
    qs = ",".join("?" for _ in _COUNTED_STATES)
    rows = comms.db.query(
        f"SELECT m.created_at, m.sent_at FROM outbound_messages m JOIN companies c "
        f"ON m.company_id=c.company_id WHERE c.campaign_id=? AND m.provider_id IN "
        f"({','.join('?' for _ in REAL_PROVIDERS)}) AND m.state IN ({qs})",
        (campaign_id, *sorted(REAL_PROVIDERS), *_COUNTED_STATES))
    return sum(1 for r in rows if _day(r["sent_at"] or r["created_at"]) == day)


def daily_limit_blockers(comms: CommsRepository, *, provider_id: str, campaign_id: str, now: str
                         ) -> List[str]:
    """Blockers from the daily/campaign ceilings. Fixture/local-sink providers are never limited."""
    if provider_id not in REAL_PROVIDERS:
        return []
    blockers: List[str] = []
    if real_send_count_today(comms, provider_id, now) >= _configured_daily_max(comms, provider_id):
        blockers.append("daily_send_ceiling_reached")
    camp_max = comms.get_control_extra(f"campaign_daily_max:{campaign_id}").get("max")
    if isinstance(camp_max, int) and campaign_send_count_today(comms, campaign_id, now) >= camp_max:
        blockers.append("campaign_daily_ceiling_reached")
    return blockers

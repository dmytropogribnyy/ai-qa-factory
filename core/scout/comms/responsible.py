"""Responsible-disclosure routing (Final Phase II).

Critical security/privacy findings must never be used as ordinary sales pressure. A
responsible-disclosure finding (category `security`, or an explicit flag) cannot enter normal
outreach: it is fail-closed blocked from draft/send and routed to a separate secure/manual review
queue. Outreach value can never override this rule.
"""
from __future__ import annotations

from typing import Any, Dict

from core.scout.memory.repository import MemoryRepository

SECURE_QUEUE = "secure_disclosure_review"


def is_responsible_disclosure(finding: Dict[str, Any]) -> bool:
    if not finding:
        return False
    return (finding.get("category") == "security"
            or bool(finding.get("responsible_disclosure_flag")))


def route_to_secure_queue(mem: MemoryRepository, *, finding_id: str, company_id: str, now: str
                          ) -> None:
    mem.add_review_item(f"secure-{finding_id}", SECURE_QUEUE, finding_id, company_id, now)

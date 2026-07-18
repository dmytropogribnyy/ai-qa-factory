"""Final Phase II — approved communication (immutable revisions, single-use approvals, sending).

Sending is disabled by default. Every external message must be individually, explicitly, and
currently human-approved after a transactional pre-send revalidation from authoritative persisted
truth. The deterministic tests use only a confined local sink — nothing is sent to a real
external recipient. Exactly-once external delivery is not claimed.
"""
from __future__ import annotations

COMMS_VERSION = "2.0.1"

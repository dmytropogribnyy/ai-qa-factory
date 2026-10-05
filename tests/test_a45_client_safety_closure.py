"""A4.5 foundation closure — an evidence item's own sanitisation decides its client safety.

`EvidenceCenter.add_text` rejects a secret-bearing payload outright: it sets
``sanitization_status="rejected"`` and stores nothing, leaving ``storage_ref`` empty. The pipeline
engine then overwrote the item's ``client_safe`` from the FINDING's predicate
(``item.client_safe = f.is_client_safe``), which knows nothing about that rejection. The outreach
gate reads only the flag (`core/scout/comms/revalidation.py` -> ``if not e["client_safe"]``), so an
item rejected *for containing a secret*, with no stored bytes, could be carried to a client.

Two predicates for one fact, and the weaker one won. The rule is the one the module's own docstring
already states — "client-safe only when sanitized AND its finding is independently verified" — and
which `core/schemas/evidence_adapters.py` implements for the canonical record. It now lives on the
item itself, so there is one expression rather than a copy per caller.
"""
from __future__ import annotations

import pytest

from core.scout.pipeline.evidence import EvidenceItem


@pytest.mark.parametrize("sanitization, verification, expected", [
    ("sanitized", "VERIFIED", True),
    ("rejected", "VERIFIED", False),      # the live case: a secret-bearing payload
    ("unsanitized", "VERIFIED", False),
    ("sanitized", "UNVERIFIED", False),
    ("sanitized", "REPRODUCED", False),
    ("rejected", "UNVERIFIED", False),
])
def test_an_item_is_client_safe_only_when_sanitised_and_verified(sanitization, verification,
                                                                 expected):
    item = EvidenceItem(evidence_id="e1", sanitization_status=sanitization,
                        verification_status=verification)
    assert item.is_client_safe is expected


def test_a_rejected_item_is_never_client_safe_however_the_flag_was_set():
    """The stored flag is not the authority; the item's own sanitisation outcome is."""
    item = EvidenceItem(evidence_id="e1", sanitization_status="rejected",
                        verification_status="VERIFIED", client_safe=True)
    assert item.is_client_safe is False


def test_the_engine_does_not_mark_rejected_evidence_client_safe(monkeypatch, tmp_path):
    """End to end through the collector: a secret-bearing payload must not come out client-safe.

    This is the path the outreach gate trusts, so it is asserted on the real collector rather than
    on a hand-made item.
    """
    from core.scout.pipeline.evidence import EvidenceCenter

    class _AlwaysFinds:
        def scan_text(self, _eid, _text):
            return ["secret_pattern"]          # the scanner fires on this payload

        def scan_bytes(self, *a, **k):
            return []

    class _Store:
        def save_bytes(self, *_a, **_k):
            raise AssertionError("a rejected payload must never be stored")

    collector = EvidenceCenter(store=_Store(), campaign_id="cid", company_id="c", session_id="s")
    collector._scanner = _AlwaysFinds()
    item = collector.add_text("reproduction_steps", {"token": "tvly-secret"}, finding_id="f1")
    assert item.sanitization_status == "rejected"
    assert item.storage_ref == "", "a rejected payload is not stored, so there is nothing to show"
    assert item.is_client_safe is False, "rejected evidence must never be client-safe"


def test_a_sanitised_verified_item_remains_client_safe(tmp_path):
    """Control: the fix must not withhold legitimate evidence."""
    from core.scout.pipeline.evidence import EvidenceCenter

    class _Clean:
        def scan_text(self, *_a):
            return []

        def scan_bytes(self, *_a, **_k):
            return []

    class _Store:
        def save_bytes(self, parts, _data):
            return "/".join(parts)

    collector = EvidenceCenter(store=_Store(), campaign_id="cid", company_id="c", session_id="s")
    collector._scanner = _Clean()
    item = collector.add_text("reproduction_steps", {"step": "click"}, finding_id="f1")
    assert item.sanitization_status == "sanitized" and item.storage_ref
    item.verification_status = "VERIFIED"
    assert item.is_client_safe is True

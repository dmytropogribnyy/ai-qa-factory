"""Final Phase II — canonical snapshot hashing for send authorization (deterministic)."""
from __future__ import annotations

from core.scout.comms.snapshots import (
    approval_binding,
    canonical_hash,
    is_placeholder_ref,
)

_CONTACT = {"contact_id": "k1", "channel": "email", "normalized_value": "hi@one.example",
            "status": "VERIFIED", "data_subject_category": "organization",
            "manual_review_required": False, "last_verified_at": "2026-07-17T00:00:00+00:00",
            "source_category": "public_website"}
_FINDING = {"finding_id": "f1", "verification_state": "VERIFIED", "lifecycle_state": "ACTIVE",
            "is_client_safe": True, "evidence_ids": ["e1"]}
_DISC = {"ready": True, "stage": "OUTREACH", "item_finding_refs": ["f1"], "blockers": []}
_SUPP = {"company_id": "co-1", "no_outreach": False, "company_suppressed": False,
         "opted_out": False, "do_not_contact": False, "hard_bounced": False}
_EVID = [{"evidence_id": "e1", "content_hash": "sha256:aa", "client_safe": True,
          "retention_deadline": "2026-12-01T00:00:00+00:00"}]


def _binding(**over):
    kw = dict(revision_id="rev-1", recipient=_CONTACT, channel="email", subject="Hi",
              body="Body", disclosure=_DISC, finding=_FINDING, evidence_rows=_EVID,
              contact=_CONTACT, suppression=_SUPP)
    kw.update(over)
    return approval_binding(**kw)


def test_canonical_hash_is_deterministic_and_order_independent():
    assert canonical_hash({"a": 1, "b": 2}) == canonical_hash({"b": 2, "a": 1})
    assert canonical_hash({"a": 1}) != canonical_hash({"a": 2})


def test_placeholder_refs_are_rejected():
    for ref in ("", "supp-1", "reval-1", "ev-pending", "pending"):
        assert is_placeholder_ref(ref)
    assert not is_placeholder_ref("supp-check-abc123")


def test_binding_changes_when_authorizing_state_changes():
    base = _binding()
    assert _binding(body="Different") != base                       # body change
    assert _binding(subject="Different") != base                    # subject change
    assert _binding(recipient={**_CONTACT, "normalized_value": "other@x"}) != base  # recipient
    assert _binding(finding={**_FINDING, "lifecycle_state": "RESOLVED"}) != base    # finding
    assert _binding(suppression={**_SUPP, "opted_out": True}) != base               # opt-out
    assert _binding() == base                                       # stable when unchanged

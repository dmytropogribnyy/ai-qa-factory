"""Independent second-pass verification for the Scout (Phase 8.3).

Candidate findings from the first pass are confirmed only if they REPRODUCE on a separate,
independent observation pass (a fresh fetch + re-run of the same checks). Transient /
unreproducible findings are REJECTED. A reproduced finding then captures sanitized evidence
and is marked VERIFIED only if it scans clean. Only VERIFIED + sanitized findings are
client-safe. This is independent of the first pass (a different observation).
"""
from __future__ import annotations

from typing import List, Set, Tuple

from core.scout.findings import (
    ScoutFinding, VERIFY_EVIDENCE_CAPTURED, VERIFY_REJECTED, VERIFY_REPRODUCED,
    VERIFY_SANITIZED, VERIFY_VERIFIED,
)
from core.scout.sanitize import Sanitizer


class IndependentVerifier:
    def __init__(self, sanitizer: Sanitizer) -> None:
        self.sanitizer = sanitizer

    def verify(
        self,
        first_pass: List[ScoutFinding],
        second_pass_signatures: Set[str],
        evidence_ref: str = "",
    ) -> Tuple[List[ScoutFinding], List[ScoutFinding]]:
        """Return (verified, rejected). Reproduction is required for every finding."""
        verified: List[ScoutFinding] = []
        rejected: List[ScoutFinding] = []
        for f in first_pass:
            if f.signature not in second_pass_signatures:
                f.verification_state = VERIFY_REJECTED
                f.notes.append("not reproduced on independent second pass")
                rejected.append(f)
                continue
            f.verification_state = VERIFY_REPRODUCED
            if evidence_ref:
                f.evidence_refs = [evidence_ref]
            f.verification_state = VERIFY_EVIDENCE_CAPTURED
            self.sanitizer.sanitize_finding(f)
            if not f.sanitized:
                f.verification_state = VERIFY_REJECTED
                f.notes.append("could not be sanitized")
                rejected.append(f)
                continue
            f.verification_state = VERIFY_SANITIZED
            f.verification_state = VERIFY_VERIFIED
            verified.append(f)
        return verified, rejected

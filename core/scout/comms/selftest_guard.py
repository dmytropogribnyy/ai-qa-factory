"""Idempotency guard for the controlled Gmail self-test (v3.2).

Exactly ONE controlled self-test is authorized per workflow (dipptrue -> drdiplextech+aiqa-selftest).
This guard makes a repeat impossible-by-default: a runner must call ``assert_single_selftest`` before
sending, which fails closed if any redacted self-test evidence already exists. It inspects only file
NAMES in the evidence directory; it never reads or exposes secrets or message bodies.
"""
from __future__ import annotations

from pathlib import Path
from typing import List

DEFAULT_EVIDENCE_DIR = "outputs/_email_selftest"


class SelfTestAlreadyRan(RuntimeError):
    """Raised to prevent a second self-test send when evidence of one already exists."""


def existing_selftest_evidence(evidence_dir: str = DEFAULT_EVIDENCE_DIR) -> List[str]:
    """Return the names of existing self-test evidence files (``selftest_*.json``); [] if none."""
    d = Path(evidence_dir)
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.glob("selftest_*.json"))


def selftest_already_completed(evidence_dir: str = DEFAULT_EVIDENCE_DIR) -> bool:
    return bool(existing_selftest_evidence(evidence_dir))


def assert_single_selftest(evidence_dir: str = DEFAULT_EVIDENCE_DIR) -> None:
    """Fail closed if a self-test has already run — a runner MUST call this before sending."""
    existing = existing_selftest_evidence(evidence_dir)
    if existing:
        raise SelfTestAlreadyRan(
            f"a controlled self-test already exists ({existing[0]}); refusing to send another "
            "(exactly one is authorized). Reuse the existing redacted evidence.")

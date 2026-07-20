"""v3.2 — the controlled Gmail self-test is idempotent: exactly one may exist. This guard prevents an
accidental repeat send. It inspects only evidence file NAMES; no secret or body is read."""
from __future__ import annotations

import pytest

from core.scout.comms.selftest_guard import (
    SelfTestAlreadyRan,
    assert_single_selftest,
    existing_selftest_evidence,
    selftest_already_completed,
)


def test_no_evidence_allows_a_first_selftest(tmp_path):
    d = str(tmp_path / "ev")
    assert existing_selftest_evidence(d) == [] and not selftest_already_completed(d)
    assert_single_selftest(d)                     # does not raise -> a first send is allowed


def test_existing_evidence_blocks_a_second_selftest(tmp_path):
    d = tmp_path / "ev"
    d.mkdir()
    (d / "selftest_74a9e423.json").write_text("{}", encoding="utf-8")
    assert selftest_already_completed(str(d))
    with pytest.raises(SelfTestAlreadyRan):
        assert_single_selftest(str(d))            # fails closed -> no accidental repeat send

"""Issue #17 P0-A — shared process-liveness fencing helper."""
from __future__ import annotations

import os

from core.collaboration.process_liveness import (
    local_host,
    owner_liveness,
    pid_alive,
)

_DEAD_PID = 2_147_483_646  # an implausible PID, effectively never a live process


def test_pid_alive_for_self_and_dead():
    assert pid_alive(os.getpid()) is True
    assert pid_alive(_DEAD_PID) is False
    assert pid_alive(0) is False
    assert pid_alive(-1) is False


def test_owner_liveness_same_host_live_and_dead():
    host = local_host()
    assert owner_liveness(owner_host=host, owner_pids=[os.getpid()]) is True
    assert owner_liveness(owner_host=host, owner_pids=[_DEAD_PID]) is False
    # a live pid anywhere in the tree keeps the owner alive
    assert owner_liveness(owner_host=host, owner_pids=[_DEAD_PID, os.getpid()]) is True


def test_owner_liveness_unknown_host_or_no_pids_is_none():
    # different host -> cannot inspect -> unknown (fail closed)
    assert owner_liveness(owner_host="some-other-host-xyz", owner_pids=[os.getpid()]) is None
    # same host but no pid info -> unknown
    assert owner_liveness(owner_host=local_host(), owner_pids=[]) is None
    assert owner_liveness(owner_host="", owner_pids=[1]) is None

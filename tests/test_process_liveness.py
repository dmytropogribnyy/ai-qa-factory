"""Issue #17 P0-A — shared process-liveness fencing helper."""
from __future__ import annotations

import os

from core.collaboration.process_liveness import (
    descendant_pids,
    local_host,
    owner_liveness,
    pid_alive,
)

_DEAD_PID = 2_147_483_646  # an implausible PID, effectively never a live process
_DEAD_PID2 = 2_147_483_645


def test_pid_alive_for_self_and_dead():
    assert pid_alive(os.getpid()) is True
    assert pid_alive(_DEAD_PID) is False
    assert pid_alive(0) is False
    assert pid_alive(-1) is False


def test_owner_liveness_needs_two_pids_and_reflects_tree_liveness():
    host = local_host()
    # a fully-captured tree (>=2 pids): any live pid -> alive; all dead -> dead
    assert owner_liveness(owner_host=host, owner_pids=[_DEAD_PID, os.getpid()]) is True
    assert owner_liveness(owner_host=host, owner_pids=[_DEAD_PID, _DEAD_PID2]) is False


def test_owner_liveness_single_pid_fails_closed():
    # P0-A: a lone recorded pid (typically just the relaunch parent before its worker child was
    # persisted) cannot prove the whole writer tree is dead -> unknown (fail closed).
    assert owner_liveness(owner_host=local_host(), owner_pids=[_DEAD_PID]) is None
    assert owner_liveness(owner_host=local_host(), owner_pids=[os.getpid()]) is None


def test_owner_liveness_unknown_host_or_no_pids_is_none():
    assert owner_liveness(owner_host="some-other-host-xyz", owner_pids=[_DEAD_PID, os.getpid()]) is None
    assert owner_liveness(owner_host=local_host(), owner_pids=[]) is None
    assert owner_liveness(owner_host="", owner_pids=[1, 2]) is None


def test_descendant_pids_is_recursive_and_excludes_self():
    # best-effort; must never raise and never include the root itself
    kids = descendant_pids(os.getpid())
    assert isinstance(kids, list)
    assert os.getpid() not in kids

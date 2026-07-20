"""v3.3 — scheduling modes on the existing Windows Task Scheduler wrapper (no schtasks call).

Deterministic argv construction only. Verifies the trigger per mode, disabled-by-default create,
manual has no task, and the invariant that the TAVILY key is NEVER embedded in the task command.
"""
from __future__ import annotations

import types

import pytest

from tools.scout_schedule import (
    ScheduleModeError,
    build_create_argv,
    discovery_cli_args,
    schedule_trigger_args,
    task_name,
)


def _args(**kw):
    base = dict(campaign_id="acc-1", countries="us,de", industries="B2B SaaS", business_types="",
                keywords="", mode="daily", day="MON", time="09:00", max_results=10, max_requests=8,
                output="outputs")
    base.update(kw)
    return types.SimpleNamespace(**base)


def test_trigger_args_per_mode():
    assert schedule_trigger_args("daily")[:2] == ["/SC", "DAILY"]
    wd = schedule_trigger_args("weekdays")
    assert wd[:2] == ["/SC", "WEEKLY"] and "MON,TUE,WED,THU,FRI" in wd
    assert schedule_trigger_args("weekly", day="WED")[:4] == ["/SC", "WEEKLY", "/D", "WED"]
    assert schedule_trigger_args("once")[:2] == ["/SC", "ONCE"]


def test_manual_has_no_scheduled_task():
    with pytest.raises(ScheduleModeError):
        schedule_trigger_args("manual")


def test_unknown_mode_rejected():
    with pytest.raises(ScheduleModeError):
        schedule_trigger_args("hourly")


def test_create_is_disabled_by_default_and_uses_mode():
    argv = build_create_argv(_args(mode="weekdays"))
    assert "/DISABLE" in argv                    # never auto-runs on create
    assert "/F" in argv
    assert "WEEKLY" in argv and "MON,TUE,WED,THU,FRI" in argv
    assert "/TN" in argv and task_name("acc-1") in argv


def test_key_is_never_in_the_task_command():
    argv = build_create_argv(_args())
    joined = " ".join(argv).upper()
    assert "TAVILY_API_KEY" not in joined
    assert "TVLY-" not in joined
    # the command runs the canonical CLI with approval, never a secret
    cli = " ".join(discovery_cli_args(_args()))
    assert "--approve-live-discovery" in cli and "TAVILY_API_KEY" not in cli.upper()

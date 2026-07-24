"""Static Windows autostart contract for the long-lived Observer tunnel."""
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = (_ROOT / "tools" / "observer_tunnel_autostart.ps1").read_text(encoding="utf-8")


def test_scheduled_task_runs_tunnel_client_as_the_action() -> None:
    """The service lifetime must not be owned by a transient PowerShell launcher."""
    assert "New-ScheduledTaskAction -Execute $TunnelClient" in _SCRIPT
    assert '$TunnelClient = Join-Path $Root "tools\\tunnel-client.exe"' in _SCRIPT
    assert 'New-ScheduledTaskAction -Execute "powershell.exe"' not in _SCRIPT


def test_scheduled_task_keeps_durable_native_diagnostics() -> None:
    """Native JSON logs must survive task exit and include future failure context."""
    assert '$ClientLog = Join-Path $LogDir "tunnel-client.service.jsonl"' in _SCRIPT
    assert '--log.file `"$ClientLog`"' in _SCRIPT
    assert "New-Item -ItemType Directory -Force -Path $LogDir" in _SCRIPT


def test_scheduled_task_retains_single_instance_and_restart_guards() -> None:
    assert "-MultipleInstances IgnoreNew" in _SCRIPT
    assert "-RestartCount 3" in _SCRIPT
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in _SCRIPT

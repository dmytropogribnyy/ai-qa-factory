<#
.SYNOPSIS
  Manage the "AI QA Factory Observer Tunnel" Windows autostart (Task Scheduler). Idempotent.

.DESCRIPTION
  Registers a per-user, non-admin, hidden scheduled task that runs tunnel-client.exe directly
  at logon (delayed 20s), restarts on failure, and never carries the secret in its arguments.
  Running the service executable as the task action keeps its lifetime independent from a
  PowerShell launcher/console session.

.PARAMETER Action
  install | start | status | stop | restart | uninstall   (default: status)

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\observer_tunnel_autostart.ps1 -Action install
#>
[CmdletBinding()]
param(
  [ValidateSet("install", "start", "status", "stop", "restart", "uninstall")]
  [string]$Action = "status"
)
$ErrorActionPreference = "Stop"
$TaskName = "AI QA Factory Observer Tunnel"
$Root = "C:\aiqa"
$TunnelClient = Join-Path $Root "tools\tunnel-client.exe"
$LogDir = Join-Path $env:LOCALAPPDATA "AIQA-Observer-Tunnel"
$ClientLog = Join-Path $LogDir "tunnel-client.service.jsonl"
$TaskArgs = "run --profile ai-qa-factory --log.file `"$ClientLog`""

function Test-Health {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri "http://127.0.0.1:8080/healthz"
    return ($r.StatusCode -eq 200)
  } catch { return $false }
}

function Install-Task {
  if (-not (Test-Path $TunnelClient)) { throw "tunnel-client not found: $TunnelClient" }
  New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
  $action = New-ScheduledTaskAction -Execute $TunnelClient -Argument $TaskArgs -WorkingDirectory $Root
  $trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
  $trigger.Delay = "PT20S"
  $settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -Hidden `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
  $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited
  Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Settings $settings -Principal $principal -Force | Out-Null
  Write-Host "[autostart] registered task '$TaskName' (at logon +20s, hidden, non-admin, single instance)." -ForegroundColor Green
  Write-Host "[autostart] task command carries NO secret (profile name + durable log path only)."
}

switch ($Action) {
  "install" { Install-Task }
  "start" {
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 6
    Write-Host "[autostart] started; health :8080 = $(Test-Health)"
  }
  "status" {
    $t = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if (-not $t) { Write-Host "[autostart] task NOT installed."; break }
    $info = Get-ScheduledTaskInfo -TaskName $TaskName
    $proc = Get-Process tunnel-client -ErrorAction SilentlyContinue
    Write-Host "[autostart] task state : $($t.State)"
    Write-Host "[autostart] last run   : $($info.LastRunTime)  result: $($info.LastTaskResult)"
    Write-Host "[autostart] processes  : $(@($proc).Count) tunnel-client"
    Write-Host "[autostart] health :8080: $(Test-Health)"
    Write-Host "[autostart] key set     : $([bool][Environment]::GetEnvironmentVariable('CONTROL_PLANE_API_KEY','User'))"
  }
  "stop" {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Get-Process tunnel-client -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "[autostart] stopped task + tunnel-client process(es)."
  }
  "restart" {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Get-Process tunnel-client -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
    Start-ScheduledTask -TaskName $TaskName
    Start-Sleep -Seconds 6
    Write-Host "[autostart] restarted; health :8080 = $(Test-Health)"
  }
  "uninstall" {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    Get-Process tunnel-client -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "[autostart] uninstalled task '$TaskName' (env var + profile left intact)."
  }
}

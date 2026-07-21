# Install/update the durable AI QA Factory supervisor as a per-user Windows Scheduled Task
# (Issue #14 P0 5039502213). Runs the supervisor at logon, restarts it on failure, one instance only,
# using the repo venv python + latest checked-out main. Idempotent: re-run to update.
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot -Parent
$py = Join-Path $repo '.venv\Scripts\python.exe'
$script = Join-Path $repo 'tools\collab_supervisor.py'
$taskName = 'AIQA-Collab-Supervisor'

if (-not (Test-Path $py)) { throw "venv python not found at $py" }
if (-not (Test-Path $script)) { throw "supervisor not found at $script" }

$action = New-ScheduledTaskAction -Execute $py -Argument "`"$script`" --output-root outputs --interval 30" -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Seconds 0) `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description 'AI QA Factory Dashboard + Direct Collaboration Driver supervisor' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Output "Installed and started scheduled task '$taskName' (venv python + repo $repo)."

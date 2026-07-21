# Uninstall the AI QA Factory supervisor scheduled task and stop any running instance.
$ErrorActionPreference = 'SilentlyContinue'
$taskName = 'AIQA-Collab-Supervisor'
Stop-ScheduledTask -TaskName $taskName
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
# Stop a running supervisor process, if any.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'collab_supervisor.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
# Remove the status file + lock so /collab does not keep showing the supervisor as installed/alive.
$repo = Split-Path $PSScriptRoot -Parent
Remove-Item (Join-Path $repo 'outputs\_review_relay\collab_supervisor.json') -Force -ErrorAction SilentlyContinue
Remove-Item (Join-Path $repo '.aiqa_supervisor.lock') -Force -ErrorAction SilentlyContinue
Write-Output "Uninstalled scheduled task '$taskName', stopped any running supervisor, cleared status/lock."

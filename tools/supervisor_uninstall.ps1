# Uninstall the AI QA Factory supervisor scheduled task and stop any running instance.
$ErrorActionPreference = 'SilentlyContinue'
$taskName = 'AIQA-Collab-Supervisor'
Stop-ScheduledTask -TaskName $taskName
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
# Stop a running supervisor process, if any.
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'collab_supervisor.py' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Write-Output "Uninstalled scheduled task '$taskName' and stopped any running supervisor."

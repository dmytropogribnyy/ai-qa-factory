# Show the AI QA Factory supervisor scheduled-task state + last supervision status.
$ErrorActionPreference = 'SilentlyContinue'
$repo = Split-Path $PSScriptRoot -Parent
$taskName = 'AIQA-Collab-Supervisor'
$task = Get-ScheduledTask -TaskName $taskName
if ($task) {
    $info = Get-ScheduledTaskInfo -TaskName $taskName
    Write-Output "Task: $taskName  State=$($task.State)  LastRun=$($info.LastRunTime)  LastResult=$($info.LastTaskResult)  NextRun=$($info.NextRunTime)"
} else {
    Write-Output "Task '$taskName' is NOT installed."
}
Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
    Where-Object { $_.CommandLine -match 'collab_supervisor.py' } |
    ForEach-Object { Write-Output "  supervisor PID $($_.ProcessId) (started $($_.CreationDate))" }
$status = Join-Path $repo 'outputs\_review_relay\collab_supervisor.json'
if (Test-Path $status) { Write-Output "Last supervision status:"; Get-Content $status -Raw }

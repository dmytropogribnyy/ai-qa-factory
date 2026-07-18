# AI QA Factory / Prospect QA Radar - stop the local dashboard (Windows), ownership-safe.
#
# This NEVER kills a process by name + port alone. It stops the dashboard only after PROVING the
# listening process is THIS dashboard invocation, using the ownership record the dashboard wrote
# (PID + process start time + expected command identity + port + repo). If ownership cannot be
# proven, it refuses and leaves the process running.
#
# Usage: scripts\stop-local.ps1 [-Port <1-65535>] [-OutputDir <path>]   (default port 8765)
#requires -Version 5
[CmdletBinding()]
param(
    [ValidateRange(1, 65535)][int]$Port = 8765,
    [string]$OutputDir
)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$repo = Split-Path -Parent $PSScriptRoot
if (-not $OutputDir) { $OutputDir = Join-Path $repo "outputs" }
$recordPath = Join-Path $OutputDir "scout\_dashboard\ownership-$Port.json"

function Remove-StaleRecord($reason) {
    Write-Host $reason
    if (Test-Path -LiteralPath $recordPath) {
        Remove-Item -LiteralPath $recordPath -Force -ErrorAction SilentlyContinue
        Write-Host "Removed stale ownership record: $recordPath"
    }
}

# 1) Ownership record must exist. No record -> we will NOT kill anything by port/name.
if (-not (Test-Path -LiteralPath $recordPath)) {
    Write-Host "No ownership record for port $Port under $OutputDir."
    Write-Host "Refusing to stop by port/name alone. If a dashboard is running, stop it with Ctrl+C."
    exit 0
}

try {
    $record = Get-Content -LiteralPath $recordPath -Raw -Encoding UTF8 | ConvertFrom-Json
} catch {
    Remove-StaleRecord "Ownership record is unreadable/corrupt."
    exit 0
}

$recPid = [int]$record.pid
if ($record.port -ne $Port) {
    Write-Error "Ownership record port ($($record.port)) does not match -Port $Port. Refusing."
    exit 3
}

# 2) The recorded PID must be alive.
$proc = Get-Process -Id $recPid -ErrorAction SilentlyContinue
if (-not $proc) {
    Remove-StaleRecord "Recorded dashboard PID $recPid is not running (already stopped)."
    exit 0
}

# 3) Anti-PID-reuse: the live process start time must not be AFTER the record was written
#    (a reused PID belongs to a newer, unrelated process).
try {
    $startedAt = [datetimeoffset]::Parse($record.started_at).UtcDateTime
    $procStart = $proc.StartTime.ToUniversalTime()
    if ($procStart -gt $startedAt.AddSeconds(5)) {
        Write-Error ("PID $recPid was reused (process started $procStart, after the ownership " +
                     "record at $startedAt). Refusing to stop an unrelated process.")
        exit 4
    }
} catch {
    Write-Error "Could not verify process start time for PID $recPid. Refusing."
    exit 4
}

# 4) Command identity: the live process must actually be this dashboard (right executable + the
#    dashboard command marker + the matching port). This is what prevents killing an arbitrary
#    Python process that merely happens to hold the port.
$cim = Get-CimInstance Win32_Process -Filter "ProcessId=$recPid" -ErrorAction SilentlyContinue
if (-not $cim) {
    Write-Error "Could not read process command line for PID $recPid. Refusing."
    exit 4
}
$cmdline = [string]$cim.CommandLine
$marker = [string]$record.command_marker
if ([string]::IsNullOrWhiteSpace($cmdline) -or ($cmdline -notlike "*$marker*") -or
    ($cmdline -notlike "*--port*$Port*")) {
    Write-Error ("PID $recPid does not look like this dashboard invocation " +
                 "(command line: '$cmdline'). Refusing to stop it.")
    exit 4
}

# 5) The recorded PID must actually own the listening port (ties the record to the real listener).
if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
    $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    $ownerPids = @()
    if ($conns) { $ownerPids = @($conns | ForEach-Object { [int]$_.OwningProcess }) }
    if ($ownerPids.Count -gt 0 -and ($ownerPids -notcontains $recPid)) {
        Write-Error ("Port $Port is held by PID(s) $($ownerPids -join ', '), not the recorded " +
                     "dashboard PID $recPid. Refusing to stop a process we do not own.")
        exit 4
    }
}

# All ownership checks passed: stop THIS dashboard.
Write-Host "Ownership proven for PID $recPid on port $Port; stopping the dashboard..."
Stop-Process -Id $recPid -Force
Start-Sleep -Milliseconds 300
if (Get-Process -Id $recPid -ErrorAction SilentlyContinue) {
    Write-Error "Dashboard PID $recPid did not stop."
    exit 5
}
Remove-Item -LiteralPath $recordPath -Force -ErrorAction SilentlyContinue
Write-Host "Dashboard stopped and ownership record removed."
exit 0

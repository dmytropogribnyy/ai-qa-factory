<#
.SYNOPSIS
  Restart THIS project's operator Dashboard so it serves the current code.

.DESCRIPTION
  The Dashboard is run from source: edit a file under core/ or main.py and the running process keeps
  serving what it loaded at start. Overview's Runtime block reports that ("Restart required: Yes");
  this script is how you clear it.

  Process control deliberately lives OUT here, not behind an HTTP button in the Dashboard itself:
  the Dashboard never spawns processes and never accepts a command over HTTP.

  Scope: only this repository's Dashboard is stopped. Other Python processes -- including Dashboards
  of a different checkout -- are left alone. Identification is by the ownership record the Dashboard
  writes for its own port, plus command lines that reference THIS repo's interpreter, plus their
  child processes (on Windows a venv's python.exe launches the base interpreter as a child, so the
  serving process shows the base path while running the venv environment).

  Restart itself is handed to the existing AIQA-Collab-Supervisor scheduled task, which health-checks
  the Dashboard and brings it back on the repo venv. If that task is not running, this script says so
  and exits non-zero rather than reporting a success it did not achieve.

.PARAMETER Port
  Dashboard port to restart (default 8765).

.PARAMETER TimeoutSeconds
  How long to wait for the supervisor to bring the Dashboard back (default 90).

.PARAMETER StartIfNoSupervisor
  Start the Dashboard directly when the supervisor is not available, instead of failing.

.PARAMETER TaskName
  Scheduled task expected to restart the Dashboard. Override it to rehearse the no-supervisor path
  without touching the real task.

.PARAMETER OpenBrowser
  Open the Dashboard once it answers. Used by the Desktop shortcut, which replaces the older
  start-only launcher: starting a Dashboard that is already running is just the special case of
  restarting one, so a single button covers both.
#>
[CmdletBinding()]
param(
    [int]$Port = 8765,
    [int]$TimeoutSeconds = 90,
    [switch]$StartIfNoSupervisor,
    [string]$TaskName = 'AIQA-Collab-Supervisor',
    [switch]$OpenBrowser
)

$ErrorActionPreference = 'Stop'
$Repo = Split-Path $PSScriptRoot -Parent
$VenvPy = Join-Path $Repo '.venv\Scripts\python.exe'
$OwnershipPath = Join-Path $Repo "outputs\scout\_dashboard\ownership-$Port.json"
$HealthUrl = "http://127.0.0.1:$Port/health"
$BuildUrl = "http://127.0.0.1:$Port/api/build"

function Get-Build {
    try { return Invoke-RestMethod -TimeoutSec 5 -Uri $BuildUrl } catch { return $null }
}

function Test-Health {
    try { return ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $HealthUrl).StatusCode -eq 200) }
    catch { return $false }
}

# --- 1. Find THIS project's Dashboard processes -------------------------------------------------
$ownedPid = $null
if (Test-Path $OwnershipPath) {
    try {
        $record = Get-Content $OwnershipPath -Raw | ConvertFrom-Json
        if ($record.repo -eq $Repo) { $ownedPid = [int]$record.pid }
    } catch { $ownedPid = $null }
}

$allDash = @(Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match 'main\.py\s+dashboard' })

$targets = @($allDash | Where-Object {
        $_.ProcessId -eq $ownedPid -or $_.CommandLine -like "*$VenvPy*"
    })
# Pull in the venv launcher's children, which carry the base-interpreter path in their command line.
for ($pass = 0; $pass -lt 3; $pass++) {
    $ids = @($targets | ForEach-Object { $_.ProcessId })
    $more = @($allDash | Where-Object { $ids -notcontains $_.ProcessId -and $ids -contains $_.ParentProcessId })
    if ($more.Count -eq 0) { break }
    $targets += $more
}

$stoppedCount = $targets.Count
if ($targets.Count -eq 0) {
    Write-Host "No Dashboard of this repo is running ($Repo)." -ForegroundColor Yellow
} else {
    foreach ($proc in $targets) {
        Write-Host ("Stopping Dashboard PID {0}" -f $proc.ProcessId)
        Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue
    }
}
$skipped = @($allDash | Where-Object { $targets.ProcessId -notcontains $_.ProcessId })
if ($skipped.Count -gt 0) {
    Write-Host ("Left {0} Dashboard process(es) of another checkout untouched." -f $skipped.Count)
}
Start-Sleep -Seconds 2

# --- 2. Hand the restart to the supervisor ------------------------------------------------------
$task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
$supervisorRunning = $false
if ($task) {
    $supervisorRunning = ($task.State -eq 'Running')
    if (-not $supervisorRunning) {
        try { Start-ScheduledTask -TaskName $TaskName; Start-Sleep -Seconds 2; $supervisorRunning = $true }
        catch { $supervisorRunning = $false }
    }
}

if (-not $supervisorRunning) {
    if ($StartIfNoSupervisor) {
        Write-Host "Supervisor unavailable - starting the Dashboard directly on the repo venv."
        Start-Process -FilePath $VenvPy -ArgumentList 'main.py', 'dashboard' `
            -WorkingDirectory $Repo -WindowStyle Hidden
    } else {
        Write-Host ""
        Write-Host "The Dashboard was stopped but NOTHING will restart it." -ForegroundColor Red
        Write-Host "The '$TaskName' scheduled task is missing or could not be started."
        Write-Host "Do one of:"
        Write-Host "  * install/repair the supervisor:  powershell -ExecutionPolicy Bypass -File `"$Repo\tools\supervisor_install.ps1`""
        Write-Host "  * or re-run this script with -StartIfNoSupervisor to launch it directly"
        Write-Host "  * or start it yourself:  `"$VenvPy`" main.py dashboard"
        exit 1
    }
}

# --- 3. Wait for it to answer -------------------------------------------------------------------
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
while ((Get-Date) -lt $deadline) {
    if (Test-Health) { break }
    Start-Sleep -Milliseconds 700
}

if (-not (Test-Health)) {
    Write-Host ""
    Write-Host "Dashboard did not answer on $HealthUrl within $TimeoutSeconds s." -ForegroundColor Red
    Write-Host "Check the supervisor log, or start it directly:  `"$VenvPy`" main.py dashboard"
    exit 1
}

# --- 4. Report what is actually serving now -----------------------------------------------------
$build = Get-Build
$newPid = $null
$exe = 'unknown'
if (Test-Path $OwnershipPath) {
    try {
        $record = Get-Content $OwnershipPath -Raw | ConvertFrom-Json
        $newPid = $record.pid
        $exe = $record.python_executable
    } catch { }
}

Write-Host ""
# Say what this invocation actually did. Reporting "restarted" after stopping nothing -- which is
# what a second, concurrent run of this script sees -- claims an action that never happened.
if ($stoppedCount -gt 0) {
    Write-Host "Dashboard restarted." -ForegroundColor Green
} else {
    Write-Host "Dashboard was not running; it is up now." -ForegroundColor Green
}
Write-Host ("  PID              : {0}" -f $(if ($newPid) { $newPid } else { 'unknown' }))
Write-Host ("  Started at       : {0}" -f $(if ($build) { $build.process_started_at } else { 'unknown' }))
Write-Host ("  Running build    : {0}" -f $(if ($build) { $build.running_build } else { 'unknown' }))
Write-Host ("  Restart required : {0}" -f $(if ($build) { $(if ($build.restart_required) { 'Yes' } else { 'No' }) } else { 'unknown' }))
Write-Host ("  Executable       : {0}" -f $exe)
Write-Host ("  Health           : 200 OK  ({0})" -f $HealthUrl)

if ($OpenBrowser) {
    Start-Process "http://127.0.0.1:$Port/scout/new"
}
exit 0

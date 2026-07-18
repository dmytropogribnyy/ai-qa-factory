# AI QA Factory / Prospect QA Radar - stop the local dashboard (Windows).
# Stops any Python process listening on the dashboard port. Safe: only touches python* processes on
# that exact local port. Usage: scripts\stop-local.ps1 [-Port <1-65535>]   (default 8765)
#requires -Version 5
[CmdletBinding()]
param([ValidateRange(1, 65535)][int]$Port = 8765)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

if (-not (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue)) {
    Write-Error "Get-NetTCPConnection is unavailable; stop the dashboard with Ctrl+C in its window."
    exit 1
}
$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
if (-not $conns) {
    Write-Host "No dashboard is listening on port $Port."
    exit 0
}
$stopped = 0
foreach ($c in $conns) {
    $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -like "python*") {
        Write-Host "Stopping dashboard (PID $($p.Id)) on port $Port..."
        Stop-Process -Id $p.Id -Force
        $stopped++
    } elseif ($p) {
        Write-Host "Port $Port is held by '$($p.ProcessName)' (PID $($p.Id)); not a python dashboard - left alone."
    }
}
Write-Host "Stopped $stopped dashboard process(es)."

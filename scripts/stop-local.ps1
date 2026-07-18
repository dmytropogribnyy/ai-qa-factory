# AI QA Factory / Prospect QA Radar - stop the local dashboard (Windows).
# Stops any Python process listening on the dashboard port. Safe: only touches python* processes on
# that exact local port. Usage: scripts\stop-local.ps1 [port]   (default 8765)
#requires -Version 5
$ErrorActionPreference = "Stop"
$port = if ($args.Count -ge 1) { [int]$args[0] } else { 8765 }
$conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
if (-not $conns) {
    Write-Host "No dashboard is listening on port $port."
    exit 0
}
$stopped = 0
foreach ($c in $conns) {
    $p = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -like "python*") {
        Write-Host "Stopping dashboard (PID $($p.Id)) on port $port..."
        Stop-Process -Id $p.Id -Force
        $stopped++
    }
}
Write-Host "Stopped $stopped dashboard process(es)."

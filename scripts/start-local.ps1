# AI QA Factory / Prospect QA Radar - start the local operator dashboard (Windows).
# Starts the localhost HOME dashboard (no scan, no email, no Gmail OAuth). The operator opens the
# printed URL, then starts a campaign explicitly from the app / CLI. Ctrl+C stops it.
# Usage: scripts\start-local.ps1 [port]   (default port 8765)
#requires -Version 5
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$venvPy = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Error "Virtual environment missing. Run scripts\setup-local.ps1 first."
    exit 1
}
$port = if ($args.Count -ge 1) { [int]$args[0] } else { 8765 }
Write-Host "Starting the local operator dashboard (idle home; nothing is scanned or sent)..."
Write-Host "Open:  http://127.0.0.1:$port" -ForegroundColor Green
Write-Host "Health: http://127.0.0.1:$port/health    Tools: http://127.0.0.1:$port/tools"
Write-Host "Press Ctrl+C to stop."
& $venvPy main.py scout dashboard --port $port

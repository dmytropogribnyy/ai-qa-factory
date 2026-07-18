# AI QA Factory / Prospect QA Radar - start the local operator dashboard (Windows).
# Starts the localhost HOME dashboard (no scan, no email, no Gmail OAuth). The operator opens the
# printed URL, then starts a campaign explicitly from the app / CLI. Ctrl+C stops it.
# Usage: scripts\start-local.ps1 [-Port <1-65535>]   (default 8765)
#requires -Version 5
[CmdletBinding()]
param([ValidateRange(1, 65535)][int]$Port = 8765)
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$venvPy = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-Error "Virtual environment missing. Run scripts\setup-local.ps1 first."
    exit 1
}
Write-Host "Starting the local operator dashboard (idle home; nothing is scanned or sent)..."
Write-Host "Open:  http://127.0.0.1:$Port" -ForegroundColor Green
Write-Host "Health: http://127.0.0.1:$Port/health    Tools: http://127.0.0.1:$Port/tools"
Write-Host "Press Ctrl+C to stop."
& $venvPy main.py scout dashboard --port $Port
exit $LASTEXITCODE

# AI QA Factory / Prospect QA Radar - one-time local setup (Windows).
# Verifies Python, creates the .venv, installs requirements.txt (free/local deps only), and checks
# writable local storage. Does NOT install Gmail OAuth libs, request any credential, or start a scan.
#requires -Version 5
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
Write-Host "AI QA Factory - local setup ($repo)"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3.12 was not found on PATH. Install Python 3.12, then re-run this script."
    exit 1
}
if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtual environment (.venv)..."
    python -m venv .venv
}
$venvPy = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { Write-Error "venv creation failed (missing $venvPy)."; exit 1 }

Write-Host "Installing dependencies from requirements.txt..."
& $venvPy -m pip install --upgrade pip | Out-Null
& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Error "dependency install failed."; exit 1 }

if (-not (Test-Path "outputs")) { New-Item -ItemType Directory -Path "outputs" | Out-Null }
try {
    "ok" | Out-File -FilePath "outputs\.write_test" -Encoding utf8
    Remove-Item "outputs\.write_test" -Force
} catch {
    Write-Error "outputs\ is not writable: $($_.Exception.Message)"
    exit 1
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Next:  scripts\start-local.ps1   (opens the local dashboard)"
Write-Host "Check: scripts\doctor-local.ps1  (readiness)"
Write-Host "Optional Gmail live-send setup is separate (docs\GMAIL_PROVIDER_SETUP.md) and not required."

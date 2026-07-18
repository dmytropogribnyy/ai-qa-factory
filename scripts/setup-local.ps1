# AI QA Factory / Prospect QA Radar - one-time local setup (Windows).
# Verifies Python, creates the .venv, installs requirements.txt (free/local deps only), and checks
# writable local storage. Does NOT install Gmail OAuth libs, request any credential, or start a scan.
#requires -Version 5
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
Write-Host "AI QA Factory - local setup ($repo)"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Write-Error "Python 3.12 was not found on PATH. Install Python 3.12, then re-run this script."
    exit 1
}
# Require a supported interpreter (3.10+, 3.12 recommended).
$ver = (& python -c "import sys; print('%d.%d' % sys.version_info[:2])").Trim()
$major, $minor = $ver.Split('.')
if ([int]$major -lt 3 -or ([int]$major -eq 3 -and [int]$minor -lt 10)) {
    Write-Error "Python $ver found; 3.10+ (3.12 recommended) is required."
    exit 1
}
Write-Host "Python $ver detected."

if (-not (Test-Path -LiteralPath ".venv")) {
    Write-Host "Creating virtual environment (.venv)..."
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Write-Error "virtual-environment creation failed."; exit 1 }
}
$venvPy = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) { Write-Error "venv creation failed (missing $venvPy)."; exit 1 }

Write-Host "Installing dependencies from requirements.txt..."
& $venvPy -m pip install --upgrade pip | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Error "pip upgrade failed."; exit 1 }
& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Write-Error "dependency install failed."; exit 1 }

if (-not (Test-Path -LiteralPath "outputs")) { New-Item -ItemType Directory -Path "outputs" | Out-Null }
try {
    "ok" | Out-File -FilePath "outputs\.write_test" -Encoding utf8
    Remove-Item -LiteralPath "outputs\.write_test" -Force
} catch {
    Write-Error "outputs\ is not writable: $($_.Exception.Message)"
    exit 1
}

Write-Host ""
Write-Host "Setup complete." -ForegroundColor Green
Write-Host "Next:  scripts\start-local.ps1   (opens the local dashboard)"
Write-Host "Check: scripts\doctor-local.ps1  (readiness)"
Write-Host "Optional Gmail live-send setup is separate (docs\GMAIL_PROVIDER_SETUP.md) and not required."

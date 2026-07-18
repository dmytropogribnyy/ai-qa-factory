# AI QA Factory / Prospect QA Radar - local health check (Windows).
# Reports Python, dependency, storage, and tool readiness. No secret is printed; nothing is scanned
# or sent. Usage: scripts\doctor-local.ps1
#requires -Version 5
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo
$venvPy = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) {
    Write-Error "Virtual environment missing. Run scripts\setup-local.ps1 first."
    exit 1
}
Write-Host "== Python ==";        & $venvPy --version
Write-Host "== Core imports ==";  & $venvPy -c "import core.scout, core.orchestration; print('core packages import OK')"
Write-Host "== Storage ==";       if (Test-Path "outputs") { Write-Host "outputs\ present" } else { Write-Host "outputs\ MISSING (run setup-local.ps1)" }
Write-Host "== Tool readiness =="; & $venvPy main.py tool-status
Write-Host ""
Write-Host "Doctor complete. If a tool shows 'unavailable' or 'blocked-by-auth', follow its setup line."

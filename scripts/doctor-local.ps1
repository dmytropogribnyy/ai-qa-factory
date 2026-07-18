# AI QA Factory / Prospect QA Radar - local health check (Windows).
# Reports Python, dependency, storage, and tool readiness. No secret is printed; nothing is scanned
# or sent. Exit code is non-zero if a core check fails. Usage: scripts\doctor-local.ps1
#requires -Version 5
[CmdletBinding()]
param()
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repo
$venvPy = Join-Path $repo ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $venvPy)) {
    Write-Error "Virtual environment missing. Run scripts\setup-local.ps1 first."
    exit 1
}
$failures = 0

Write-Host "== Python =="
& $venvPy --version
if ($LASTEXITCODE -ne 0) { $failures++ }

Write-Host "== Core imports =="
& $venvPy -c "import core.scout, core.orchestration; print('core packages import OK')"
if ($LASTEXITCODE -ne 0) { Write-Warning "core packages failed to import"; $failures++ }

Write-Host "== Storage =="
if (Test-Path -LiteralPath "outputs") { Write-Host "outputs\ present" }
else { Write-Warning "outputs\ MISSING (run setup-local.ps1)"; $failures++ }

Write-Host "== Tool readiness =="
& $venvPy main.py tool-status
if ($LASTEXITCODE -ne 0) { $failures++ }

Write-Host ""
if ($failures -eq 0) {
    Write-Host "Doctor complete: all core checks passed." -ForegroundColor Green
    exit 0
}
Write-Warning "Doctor complete: $failures core check(s) failed. Follow the setup lines above."
exit 1

<#
.SYNOPSIS
  Launch the AI QA Factory operator dashboard (current code) and open the adaptive Scout.

.DESCRIPTION
  Starts `python main.py dashboard` from the repo (via the space-free junction C:\aiqa) only if it
  is not already serving on 127.0.0.1:8765, then opens the browser at /scout/new (Discover
  Prospects). The dashboard is read-only + loopback-bound. Idempotent: re-running just focuses the
  browser if the server is already up.
#>
$ErrorActionPreference = "SilentlyContinue"
$Repo = "C:\aiqa"                       # junction -> D:\1QA AI\ai-qa-factory (no spaces)
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
$Url = "http://127.0.0.1:8765/scout/new"

function Test-Up {
  try { return ((Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 -Uri "http://127.0.0.1:8765/health").StatusCode -eq 200) }
  catch { return $false }
}

if (-not (Test-Up)) {
  if (-not (Test-Path $Py)) { $Py = "python" }   # fall back to PATH python
  Start-Process -FilePath $Py -ArgumentList "main.py", "dashboard" -WorkingDirectory $Repo -WindowStyle Hidden
  for ($i = 0; $i -lt 25; $i++) { Start-Sleep -Milliseconds 800; if (Test-Up) { break } }
}

Start-Process $Url                       # open the adaptive Scout in the default browser

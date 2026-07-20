<#
.SYNOPSIS
  Launcher for the AI QA Factory Observer OpenAI Secure MCP Tunnel (no secret inside this file).

.DESCRIPTION
  Reads CONTROL_PLANE_API_KEY from the environment (user env var, set once out-of-band).
  Idempotent: if a tunnel is already healthy on 127.0.0.1:8080 it exits 0 without starting a
  second instance. Otherwise it runs `tunnel-client run --profile ai-qa-factory` from C:\aiqa.
  Never prints the key; logs go to %LOCALAPPDATA%\AIQA-Observer-Tunnel (outside the repo).
#>
$ErrorActionPreference = "Stop"
$Root = "C:\aiqa"
$LogDir = Join-Path $env:LOCALAPPDATA "AIQA-Observer-Tunnel"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$Log = Join-Path $LogDir "launcher.log"
$ClientLog = Join-Path $LogDir "tunnel-client.out.log"

function Log([string]$m) { "$(Get-Date -Format o)  $m" | Add-Content -Path $Log -Encoding utf8 }

# 1. secret must be present (never written here; comes from the user env var)
if (-not $env:CONTROL_PLANE_API_KEY) {
  Log "ERROR: CONTROL_PLANE_API_KEY is not set. Set it once: [Environment]::SetEnvironmentVariable('CONTROL_PLANE_API_KEY','<key>','User'); then log off/on."
  exit 2
}

# 2. already healthy? -> do nothing (single instance)
try {
  $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri "http://127.0.0.1:8080/healthz"
  if ($r.StatusCode -eq 200) { Log "tunnel already healthy on :8080 -> skip start"; exit 0 }
} catch { }

# 3. environment for the MCP server behind the tunnel
$env:AIQA_OUTPUT_ROOT = "C:\aiqa\outputs"

# 4. locate the tunnel-client binary inside the repo tools tree
$exe = Get-ChildItem "$Root\tools" -Filter "tunnel-client.exe" -Recurse -ErrorAction SilentlyContinue |
  Select-Object -First 1 -ExpandProperty FullName
if (-not $exe) { Log "ERROR: tunnel-client.exe not found under $Root\tools"; exit 3 }

# 5. run (blocks; Task Scheduler keeps it alive). Client JSON logs (no key) go to a file.
Set-Location $Root
Log "starting: $exe run --profile ai-qa-factory (workdir $Root)"
& $exe run --profile ai-qa-factory *>> $ClientLog
$code = $LASTEXITCODE
Log "tunnel-client exited with code $code"
exit $code

<#
.SYNOPSIS
  One-shot restore of the Observer MCP tunnel: launches the EXISTING `ai-qa-factory` profile
  detached, verifies local health, and returns. Registers no autostart.

.DESCRIPTION
  Canonical manual restore path documented in docs/operations/observer-mcp-tunnel.md.

  Idempotent by design. It starts nothing when the tunnel is already healthy OR when a
  `tunnel-client` process already exists, so running it twice can never produce two tunnels.

  The tunnel client makes an OUTBOUND connection to the OpenAI control plane and spawns the
  read-only Observer over stdio. No public inbound port is opened, no new tunnel is created, and the
  ChatGPT connector binding is never touched — while the profile's stable tunnel id is unchanged the
  endpoint is unchanged too.

  CONTROL_PLANE_API_KEY is read from the User environment scope and passed to the child through the
  process environment. It is never printed, logged, or written to disk by this script.

  Local health is necessary but NOT proof: only a real external MCP call through the ChatGPT
  connector, returning the expected git build, proves the Observer is reachable.

.PARAMETER HealthPort
  Local operator health surface of the tunnel client. Default 8080.

.PARAMETER ProfileName
  Tunnel-client profile to run. Default `ai-qa-factory` — do not change without owner approval.

.PARAMETER TimeoutSec
  How long to wait for the freshly started client to report healthy. Default 45.

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File C:\aiqa\tools\start_observer_tunnel_once.ps1

.NOTES
  Exit codes: 0 ok (started or already running) · 2 secret missing · 3 layout broken ·
              4 started but never became healthy
#>
[CmdletBinding()]
param(
  [int]$HealthPort = 8080,
  [string]$ProfileName = 'ai-qa-factory',
  [int]$TimeoutSec = 45
)

$ErrorActionPreference = 'Stop'

$Root = 'C:\aiqa'
$Client = Join-Path $Root 'tools\tunnel-client.exe'
$LogDir = Join-Path $env:LOCALAPPDATA 'AIQA-Observer-Tunnel'
$Log = Join-Path $LogDir 'tunnel-client.manual.jsonl'
$HealthUrl = "http://127.0.0.1:$HealthPort/healthz"
$ReadyUrl = "http://127.0.0.1:$HealthPort/readyz"

function Test-Endpoint([string]$Url) {
  try {
    $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 3 -Uri $Url
    return ($r.StatusCode -eq 200)
  } catch {
    return $false
  }
}

# 1. Already healthy -> nothing to do. Checked FIRST so the common case costs one HTTP call.
if (Test-Endpoint $HealthUrl) {
  Write-Host "[tunnel] already healthy on 127.0.0.1:$HealthPort - nothing started." -ForegroundColor Green
  Write-Host "[tunnel] proof still requires a real external ChatGPT Observer call."
  exit 0
}

# 2. A client process without health means it is starting up, wedged, or bound elsewhere. Either
#    way, starting a second one is never the right move: report and let the operator decide.
$existing = @(Get-Process tunnel-client -ErrorAction SilentlyContinue)
if ($existing.Count -gt 0) {
  $pids = ($existing | ForEach-Object { $_.Id }) -join ', '
  Write-Warning "[tunnel] tunnel-client already running (PID $pids) but 127.0.0.1:$HealthPort is not healthy."
  Write-Host "[tunnel] Not starting a second instance. Inspect, then retry:"
  Write-Host "         Get-Content '$Log' -Tail 20"
  Write-Host "         & '$Client' health --port $HealthPort"
  exit 0
}

# 3. Layout checks before touching anything, so a broken junction is named rather than guessed at.
$missing = @()
if (-not (Test-Path $Client)) { $missing += "tunnel client: $Client" }
if (-not (Test-Path (Join-Path $Root '.venv\Scripts\python.exe'))) { $missing += "venv python under $Root" }
if (-not (Test-Path (Join-Path $Root 'tools\run_mcp_server.py'))) { $missing += "MCP entrypoint under $Root" }
if ($missing.Count -gt 0) {
  Write-Error ("[tunnel] cannot start - missing:`n  - " + ($missing -join "`n  - ") +
    "`n  Check that the C:\aiqa junction still points at the canonical checkout.")
  exit 3
}

# 4. Secret from the User scope. Reading the User scope explicitly matters: a shell started before
#    the variable was set does not inherit it, so a process-only lookup reports "no key" while the
#    key exists. Fall back to the process environment for shells that do have it.
$key = [Environment]::GetEnvironmentVariable('CONTROL_PLANE_API_KEY', 'User')
if ([string]::IsNullOrWhiteSpace($key)) { $key = $env:CONTROL_PLANE_API_KEY }
if ([string]::IsNullOrWhiteSpace($key)) {
  Write-Error @"
[tunnel] CONTROL_PLANE_API_KEY is not set in the User scope.
  Set it once (in an interactive shell, not in a script committed to the repo):
    [Environment]::SetEnvironmentVariable('CONTROL_PLANE_API_KEY','<key>','User')
  Then start a new shell and re-run this script. The value is never printed or stored by it.
"@
  exit 2
}
$env:CONTROL_PLANE_API_KEY = $key   # inherited by the child; never echoed

# 5. Launch the existing profile, hidden and detached. Logs live outside the repository.
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$proc = Start-Process -FilePath $Client `
  -ArgumentList @('run', '--profile', $ProfileName, '--log.file', ('"' + $Log + '"')) `
  -WorkingDirectory $Root -WindowStyle Hidden -PassThru
Write-Host "[tunnel] started tunnel-client PID $($proc.Id) with profile '$ProfileName'."

# 6. Wait for it to report healthy, then ready.
$deadline = (Get-Date).AddSeconds($TimeoutSec)
$healthy = $false
while ((Get-Date) -lt $deadline) {
  if (Test-Endpoint $HealthUrl) { $healthy = $true; break }
  if ($proc.HasExited) { break }
  Start-Sleep -Milliseconds 750
}

if (-not $healthy) {
  if ($proc.HasExited) {
    Write-Error "[tunnel] tunnel-client exited immediately (code $($proc.ExitCode)). Last log lines:"
  } else {
    Write-Error "[tunnel] tunnel-client is running (PID $($proc.Id)) but never became healthy within ${TimeoutSec}s. Last log lines:"
  }
  if (Test-Path $Log) { Get-Content $Log -Tail 15 }
  exit 4
}

$ready = Test-Endpoint $ReadyUrl
Write-Host "[tunnel] healthz=200  readyz=$(if ($ready) { '200' } else { 'not ready yet' })" -ForegroundColor Green
Write-Host "[tunnel] log: $Log"
Write-Host "[tunnel] No autostart was registered - this process does not survive a reboot."
Write-Host "[tunnel] Local health is NOT proof: confirm with a real external ChatGPT Observer call" -ForegroundColor Yellow
Write-Host "[tunnel] and check the returned git build matches the intended exact main." -ForegroundColor Yellow
exit 0

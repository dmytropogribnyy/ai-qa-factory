<#
.SYNOPSIS
  Safe Windows helper for the AI QA Factory read-only Observer MCP (local stdio).

.DESCRIPTION
  One parameterized script - no secrets, no firewall changes, no public ports. The stdio MCP
  server is normally SPAWNED BY the MCP client (Claude Desktop / Claude Code / Cursor); this helper
  is for doctor/list/test/manual-debug.

.PARAMETER Action
  doctor  - check venv python + mcp package + list tools (default)
  list    - print the MCP tool catalog
  test    - run the real stdio transport smoke (writes a redacted acceptance report)
  start   - manually run the stdio server (debug only; clients spawn it themselves; Ctrl+C to stop)
  stop    - explains stop semantics (stdio server exits with its client)

.PARAMETER OutputRoot
  The AI QA Factory output root the Observer reads (default: env AIQA_OUTPUT_ROOT, else <repo>\outputs).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File tools\observer_mcp.ps1 -Action doctor
  powershell -ExecutionPolicy Bypass -File tools\observer_mcp.ps1 -Action test
#>
[CmdletBinding()]
param(
  [ValidateSet("doctor", "list", "test", "start", "stop", "http", "http-test")]
  [string]$Action = "doctor",
  [string]$OutputRoot = $env:AIQA_OUTPUT_ROOT,
  [int]$Port = 8765
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot           # tools\ -> repo root
$Py = Join-Path $Repo ".venv\Scripts\python.exe"
$Server = Join-Path $Repo "tools\run_mcp_server.py"
$Smoke = Join-Path $Repo "tools\mcp_smoke.py"
if (-not $OutputRoot) { $OutputRoot = Join-Path $Repo "outputs" }

function Fail($msg) { Write-Host "[observer-mcp] ERROR: $msg" -ForegroundColor Red; exit 1 }

function Assert-Python {
  if (-not (Test-Path $Py)) {
    Fail "venv python not found at $Py - create the venv, then: `"$Py`" -m pip install mcp"
  }
}
function Assert-Mcp {
  & $Py -c "import mcp" 2>$null
  if ($LASTEXITCODE -ne 0) {
    Fail "the 'mcp' package is not installed - run: `"$Py`" -m pip install mcp"
  }
}

switch ($Action) {
  "doctor" {
    Assert-Python
    Write-Host "[observer-mcp] repo:        $Repo"
    Write-Host "[observer-mcp] python:      $Py"
    Write-Host "[observer-mcp] output root: $OutputRoot"
    & $Py -c "import mcp,sys; print('[observer-mcp] mcp installed:', getattr(mcp,'__version__','?'))" 2>$null
    if ($LASTEXITCODE -ne 0) {
      Write-Host "[observer-mcp] mcp NOT installed -> `"$Py`" -m pip install mcp" -ForegroundColor Yellow
    }
    & $Py $Server --list-tools
    Write-Host "[observer-mcp] doctor done. Run '-Action test' for a real transport smoke." -ForegroundColor Green
  }
  "list" { Assert-Python; & $Py $Server --list-tools }
  "test" {
    Assert-Python; Assert-Mcp
    $env:AIQA_OUTPUT_ROOT = $OutputRoot
    & $Py $Smoke --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) { Fail "MCP smoke FAILED - see the acceptance report under outputs\mcp_acceptance." }
    Write-Host "[observer-mcp] smoke PASSED - report: outputs\mcp_acceptance\MCP_CONNECTION_ACCEPTANCE.md" -ForegroundColor Green
  }
  "start" {
    Assert-Python; Assert-Mcp
    $env:AIQA_OUTPUT_ROOT = $OutputRoot
    Write-Host "[observer-mcp] Manual stdio server (DEBUG only). MCP clients normally spawn this themselves."
    Write-Host "[observer-mcp] Press Ctrl+C to stop. Reads AIQA_OUTPUT_ROOT=$OutputRoot"
    & $Py $Server
  }
  "stop" {
    Write-Host "[observer-mcp] The stdio MCP server is spawned per-client and exits when the client disconnects."
    Write-Host "[observer-mcp] There is no long-lived daemon to stop. For a manual '-Action start', press Ctrl+C."
  }
  "http" {
    Assert-Python; Assert-Mcp
    if (-not $env:AIQA_MCP_TOKEN) {
      Write-Host "[observer-mcp] AIQA_MCP_TOKEN is not set (required - no open endpoint)." -ForegroundColor Yellow
      Write-Host "[observer-mcp] Generate + set one for this session (the value is never printed by this script):"
      Write-Host '    $env:AIQA_MCP_TOKEN = [Convert]::ToBase64String((1..24 | % {Get-Random -Max 256}))'
      Fail "set AIQA_MCP_TOKEN, then re-run: -Action http"
    }
    $env:AIQA_OUTPUT_ROOT = $OutputRoot
    Write-Host "[observer-mcp] Authenticated streamable-HTTP MCP on http://127.0.0.1:$Port/mcp (loopback)."
    Write-Host "[observer-mcp] Bearer token = your AIQA_MCP_TOKEN. Expose publicly ONLY via your own tunnel."
    Write-Host "[observer-mcp] Press Ctrl+C to stop."
    & $Py $Server --http --host 127.0.0.1 --port $Port
  }
  "http-test" {
    Assert-Python; Assert-Mcp
    $env:AIQA_OUTPUT_ROOT = $OutputRoot
    & $Py (Join-Path $Repo "tools\mcp_http_smoke.py") --output-root $OutputRoot
    if ($LASTEXITCODE -ne 0) { Fail "HTTP MCP smoke FAILED - see outputs\mcp_acceptance\MCP_HTTP_ACCEPTANCE.md" }
    Write-Host "[observer-mcp] HTTP smoke PASSED (authorized call ok, unauthenticated refused)." -ForegroundColor Green
  }
}

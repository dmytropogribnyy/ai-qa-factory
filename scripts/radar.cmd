@echo off
REM AI QA Factory / ARK Prospect QA Radar — Windows launcher.
REM Usage: radar <command>   where <command> is one of:
REM   demo          deterministic Scout QA demo
REM   discovery     deterministic discovery -> Scout demo
REM   presend       deterministic complete pre-send demo
REM   radar         deterministic complete-product demo (local sink; nothing sent)
REM   dashboard     open the localhost dashboard (attach with --run-id <campaign>)
REM   doctor        environment + communication readiness (add --db <memory.db>)
REM   mcp-audit     MCP integration audit snapshots
REM   test          full deterministic test suite
REM Sending is DISABLED by default and only via `python main.py scout send` with explicit approval.

setlocal
set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

if "%1"=="" (
  echo Usage: radar ^<demo^|discovery^|presend^|radar^|dashboard^|doctor^|mcp-audit^|test^> [args...]
  exit /b 1
)
if /I "%1"=="demo"      ( %PY% main.py scout demo & exit /b %ERRORLEVEL% )
if /I "%1"=="discovery" ( %PY% main.py scout campaign-demo & exit /b %ERRORLEVEL% )
if /I "%1"=="presend"   ( %PY% main.py scout presend-demo & exit /b %ERRORLEVEL% )
if /I "%1"=="radar"     ( %PY% main.py scout radar-demo & exit /b %ERRORLEVEL% )
if /I "%1"=="dashboard" ( %PY% main.py scout dashboard %2 %3 %4 %5 & exit /b %ERRORLEVEL% )
if /I "%1"=="doctor"    ( %PY% main.py scout doctor %2 %3 & exit /b %ERRORLEVEL% )
if /I "%1"=="mcp-audit" ( %PY% main.py scout mcp-audit --output outputs & exit /b %ERRORLEVEL% )
if /I "%1"=="test"      ( %PY% -m pytest tests/ -q & exit /b %ERRORLEVEL% )
echo Unknown command: %1
exit /b 1

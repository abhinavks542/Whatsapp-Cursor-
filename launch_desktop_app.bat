@echo off
setlocal
cd /d "%~dp0"

set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  set "PYTHON=python"
)

curl.exe -s http://127.0.0.1:5002/api/status >nul 2>&1
if errorlevel 1 (
  echo [WhatsApp AI] Starting background bridge and console service...
  start "WhatsApp AI Service" /min "%PYTHON%" "%~dp0run_live.py"
  timeout /t 3 /nobreak >nul 2>&1
)

echo [WhatsApp AI] Launching Native Desktop Window...
npx electron desktop/main.cjs
endlocal

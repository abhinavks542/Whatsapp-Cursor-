@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=%~dp0.venv\Scripts\python.exe"
if not exist "%PYTHON%" (
  where.exe python >nul 2>&1
  if errorlevel 1 (
    echo Python was not found. Install Python or create the project's .venv first.
    pause
    exit /b 1
  )
  set "PYTHON=python"
)

where.exe node >nul 2>&1
if errorlevel 1 (
  echo Node.js 20 or newer was not found. Install Node.js and try again.
  pause
  exit /b 1
)

node -e "if (Number(process.versions.node.split('.')[0]) < 20) process.exitCode = 1"
if errorlevel 1 (
  echo This WhatsApp client requires Node.js 20 or newer.
  node --version
  pause
  exit /b 1
)

if not exist "%~dp0node_modules\@whiskeysockets\baileys\package.json" (
  echo Node.js dependencies are missing.
  echo Open a terminal in this folder and run: npm install
  pause
  exit /b 1
)

"%PYTHON%" -c "import flask, dotenv; import google.genai" >nul 2>&1
if errorlevel 1 (
  echo Required Python packages are missing.
  echo Run this command from the project folder:
  echo "%PYTHON%" -m pip install -r requirements.txt
  pause
  exit /b 1
)

"%PYTHON%" "%~dp0run_live.py"
set "EXIT_CODE=%ERRORLEVEL%"
if not "%EXIT_CODE%"=="0" (
  echo WhatsApp Local Console could not start.
  pause
)
endlocal & exit /b %EXIT_CODE%
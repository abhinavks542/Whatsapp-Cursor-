$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot ".chroma_server.pid"
$Port = 8000

if (-not (Test-Path $PidFile)) {
    Write-Host "No Chroma PID file found at $PidFile; no process was stopped."
    exit 0
}

$PidText = (Get-Content -Path $PidFile -Raw).Trim()
$ServerPid = 0
if (-not [int]::TryParse($PidText, [ref]$ServerPid) -or $ServerPid -le 0) {
    throw "PID file does not contain a valid process ID: $PidFile"
}

$ProcessInfo = Get-CimInstance -ClassName Win32_Process -Filter "ProcessId = $ServerPid" -ErrorAction SilentlyContinue
if (-not $ProcessInfo) {
    Write-Host "Recorded Chroma process $ServerPid is not running; removing stale PID file."
    Remove-Item $PidFile
    exit 0
}

# Verify the PID still belongs to the Chroma command before stopping it.
$ExpectedCommand = $ProcessInfo.Name -match "^chroma(\.exe)?$" -and `
    $ProcessInfo.CommandLine -match ('(?i)\brun\b.*--path\s+"?\./chroma_data"?.*--port\s+"?' + $Port + '(?:\s|$)')
if (-not $ExpectedCommand) {
    throw "PID $ServerPid is not the expected Chroma run process; refusing to stop it."
}

Write-Host "Stopping Chroma process $ServerPid."
Stop-Process -Id $ServerPid
try {
    Wait-Process -Id $ServerPid -Timeout 10 -ErrorAction Stop
}
catch {
    $StillRunning = Get-Process -Id $ServerPid -ErrorAction SilentlyContinue
    if ($StillRunning) {
        Write-Warning "Chroma process $ServerPid is still running; PID file was kept."
        exit 1
    }
}

$StillRunning = Get-Process -Id $ServerPid -ErrorAction SilentlyContinue
if ($StillRunning) {
    Write-Warning "Chroma process $ServerPid is still running; PID file was kept."
    exit 1
}

Remove-Item $PidFile
Write-Host "Chroma process $ServerPid stopped."
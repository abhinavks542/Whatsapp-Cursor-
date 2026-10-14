param()

$ErrorActionPreference = "Stop"
$Port = 8000
$HeartbeatUrl = "http://localhost:$Port/api/v2/heartbeat"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$PidFile = Join-Path $ProjectRoot ".chroma_server.pid"
$LogFile = Join-Path $ProjectRoot ".chroma_server.log"
$ErrorLogFile = Join-Path $ProjectRoot ".chroma_server.err.log"
$InstalledPackages = [System.Collections.Generic.List[string]]::new()
$AlreadyInstalled = [System.Collections.Generic.List[string]]::new()
$ServerPid = $null

# Use python3 where available; Windows Python installations commonly expose `py` instead.
$PythonCommand = Get-Command python3 -ErrorAction SilentlyContinue
$PythonLauncherArgs = @()
if (-not $PythonCommand) {
    $PythonCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($PythonCommand) {
        $PythonLauncherArgs = @("-3")
    }
}
if (-not $PythonCommand) {
    throw "Python 3 was not found. Install Python and ensure python3 or py is on PATH."
}
$PythonExe = $PythonCommand.Source

# Install only dependencies that are missing from this Python environment.
foreach ($Package in @("chromadb", "sentence-transformers")) {
    & $PythonExe @PythonLauncherArgs -m pip show $Package *> $null
    if ($LASTEXITCODE -eq 0) {
        $AlreadyInstalled.Add($Package)
        Write-Host "$Package is already installed."
    }
    else {
        $InstalledPackages.Add($Package)
    }
}

if ($InstalledPackages.Count -gt 0) {
    Write-Host "Installing missing package(s): $($InstalledPackages -join ', ')"
    & $PythonExe @PythonLauncherArgs -m pip install @($InstalledPackages.ToArray())
    if ($LASTEXITCODE -ne 0) {
        throw "pip could not install the missing packages."
    }
}

# Detect a listener and reuse it only if its Chroma heartbeat responds.
$Listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue)
if ($Listeners.Count -gt 0) {
    $ServerPid = [int]$Listeners[0].OwningProcess
    $IsHealthy = $false
    try {
        $Response = Invoke-WebRequest -Uri $HeartbeatUrl -UseBasicParsing -TimeoutSec 2
        $IsHealthy = $Response.StatusCode -ge 200 -and $Response.StatusCode -lt 300
    }
    catch {
        $IsHealthy = $false
    }

    if (-not $IsHealthy) {
        Write-Warning "Port $Port is occupied by PID $ServerPid, but its heartbeat is not Chroma. Free the port or choose another port."
        exit 1
    }
    Write-Host "Chroma is already healthy on port $Port (PID: $ServerPid)."
}
else {
    # Locate chroma.exe, including the Scripts directory for the selected Python.
    $ChromaCommand = Get-Command chroma -ErrorAction SilentlyContinue
    $ChromaExe = if ($ChromaCommand) { $ChromaCommand.Source } else { $null }
    if (-not $ChromaExe) {
        $ScriptsDir = (& $PythonExe @PythonLauncherArgs -c "import sysconfig; print(sysconfig.get_path('scripts'))").Trim()
        $Candidate = Join-Path $ScriptsDir "chroma.exe"
        if (Test-Path $Candidate) {
            $ChromaExe = $Candidate
        }
    }
    if (-not $ChromaExe) {
        throw "chroma.exe was not found after checking dependencies and the Python Scripts directory."
    }

    # Start Chroma detached from this PowerShell session and save its exact PID.
    $ServerProcess = Start-Process -FilePath $ChromaExe `
        -ArgumentList @("run", "--path", "./chroma_data", "--port", "$Port") `
        -WorkingDirectory $ProjectRoot `
        -RedirectStandardOutput $LogFile `
        -RedirectStandardError $ErrorLogFile `
        -WindowStyle Hidden `
        -PassThru
    $ServerPid = $ServerProcess.Id
    Set-Content -Path $PidFile -Value $ServerPid -Encoding ascii

    # Poll the heartbeat every two seconds, for no more than ten attempts.
    $IsHealthy = $false
    for ($Attempt = 1; $Attempt -le 10; $Attempt++) {
        try {
            $Response = Invoke-WebRequest -Uri $HeartbeatUrl -UseBasicParsing -TimeoutSec 2
            if ($Response.StatusCode -ge 200 -and $Response.StatusCode -lt 300) {
                $IsHealthy = $true
                break
            }
        }
        catch {
            $IsHealthy = $false
        }
        if ($Attempt -lt 10) {
            Start-Sleep -Seconds 2
        }
    }

    if (-not $IsHealthy) {
        Write-Warning "Chroma did not become healthy after 10 checks. Check $LogFile and $ErrorLogFile."
        $StartedProcess = Get-Process -Id $ServerPid -ErrorAction SilentlyContinue
        if ($StartedProcess) {
            Stop-Process -Id $ServerPid -ErrorAction SilentlyContinue
        }
        Remove-Item $PidFile -ErrorAction SilentlyContinue
        exit 1
    }
}

# Summarize dependency state and the port available to the other scripts.
$InstalledSummary = if ($InstalledPackages.Count) { $InstalledPackages -join ", " } else { "none" }
$AlreadySummary = if ($AlreadyInstalled.Count) { $AlreadyInstalled -join ", " } else { "none" }
Write-Host "Installed in this run: $InstalledSummary"
Write-Host "Already installed: $AlreadySummary"
Write-Host "Server: running; PID: $ServerPid; port: $Port"
Write-Host "Endpoint: $HeartbeatUrl"
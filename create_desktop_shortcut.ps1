$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$consoleLauncher = Join-Path $projectRoot "start_whatsapp_console.bat"
$desktopLauncher = Join-Path $projectRoot "launch_desktop_app.bat"
$iconPath = Join-Path $projectRoot "assets\icon.ico"

if (-not (Test-Path -LiteralPath $consoleLauncher -PathType Leaf)) {
    throw "Console launcher not found: $consoleLauncher"
}

# Discover all active Desktop targets (Local + OneDrive synced Desktop)
$desktopFolders = [System.Collections.Generic.List[string]]::new()
$stdDesktop = [Environment]::GetFolderPath("Desktop")
if ($stdDesktop -and (Test-Path -LiteralPath $stdDesktop -PathType Container)) {
    $desktopFolders.Add($stdDesktop)
}
if ($env:USERPROFILE) {
    $oneDriveDesktop = Join-Path $env:USERPROFILE "OneDrive\Desktop"
    if ((Test-Path -LiteralPath $oneDriveDesktop -PathType Container) -and (-not $desktopFolders.Contains($oneDriveDesktop))) {
        $desktopFolders.Add($oneDriveDesktop)
    }
}

$shell = New-Object -ComObject WScript.Shell

# Clean up obsolete legacy shortcuts
$legacyNames = @("Sahayak.lnk", "WhatsApp Cursor.lnk")
foreach ($folder in $desktopFolders) {
    foreach ($leg in $legacyNames) {
        $p = Join-Path $folder $leg
        if (Test-Path -LiteralPath $p) {
            Remove-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
            Write-Host "Removed legacy shortcut: $p"
        }
    }
}

# Target folders where shortcuts should be placed
$targetFolders = [System.Collections.Generic.List[string]]::new()
$targetFolders.Add($projectRoot)
foreach ($f in $desktopFolders) {
    if (-not $targetFolders.Contains($f)) {
        $targetFolders.Add($f)
    }
}

$definitions = @(
    @{
        Name = "WhatsApp AI Pro Console.lnk"
        Target = $consoleLauncher
        Description = "WhatsApp AI Pro Console - Executive 3D Dashboard"
    },
    @{
        Name = "WhatsApp Local Console.lnk"
        Target = $consoleLauncher
        Description = "WhatsApp AI Local Console"
    },
    @{
        Name = "WhatsApp AI Desktop (Native).lnk"
        Target = $desktopLauncher
        Description = "WhatsApp AI Pro Native Desktop Window"
    }
)

Write-Host "Creating Pro Desktop Shortcuts with High-Res Icon..."
foreach ($folder in $targetFolders) {
    foreach ($def in $definitions) {
        $shortcutPath = Join-Path $folder $def.Name
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $def.Target
        $shortcut.WorkingDirectory = $projectRoot
        $shortcut.Description = $def.Description
        if (Test-Path -LiteralPath $iconPath) {
            $shortcut.IconLocation = "$iconPath,0"
        }
        $shortcut.Save()
        Write-Host "  -> Saved: $shortcutPath"
    }
}

Write-Host "Desktop configuration complete!"

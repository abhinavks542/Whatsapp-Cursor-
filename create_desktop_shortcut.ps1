$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$launcherPath = Join-Path $projectRoot "start_whatsapp_console.bat"
if (-not (Test-Path -LiteralPath $launcherPath -PathType Leaf)) {
    throw "Launcher not found: $launcherPath"
}

$desktopPath = [Environment]::GetFolderPath("Desktop")
if (-not (Test-Path -LiteralPath $desktopPath -PathType Container)) {
    throw "Desktop folder not found: $desktopPath"
}

$shell = New-Object -ComObject WScript.Shell
$shortcutPaths = @(
    (Join-Path $projectRoot "WhatsApp Local Console.lnk"),
    (Join-Path $desktopPath "WhatsApp Local Console.lnk")
)

foreach ($shortcutPath in $shortcutPaths) {
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $launcherPath
    $shortcut.WorkingDirectory = $projectRoot
    $shortcut.Description = "Start the local WhatsApp console"
    $shortcut.Save()
}

Write-Host "Shortcuts created:"
Write-Host "  Project: $($shortcutPaths[0])"
Write-Host "  Desktop: $($shortcutPaths[1])"

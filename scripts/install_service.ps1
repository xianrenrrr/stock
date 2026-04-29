# install_service.ps1 -- register stock serve as a Windows Startup item

# Resolve the stock command (installed via pip)
$stockCmd = Get-Command stock -ErrorAction SilentlyContinue
if (-not $stockCmd) {
    Write-Error "stock command not found. Install with: pip install -e ."
    exit 1
}

# Determine project root (one level up from scripts/)
$projectRoot = Split-Path $PSScriptRoot -Parent

# Create shortcut in the Startup folder
$startupFolder = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupFolder "stock-orchestrator.lnk"
$shell = New-Object -ComObject WScript.Shell
$shortcut = $shell.CreateShortcut($shortcutPath)
$shortcut.TargetPath = $stockCmd.Source
$shortcut.Arguments = "serve"
$shortcut.WorkingDirectory = $projectRoot
$shortcut.WindowStyle = 7            # Minimized
$shortcut.Description = "Stock prediction pipeline orchestrator"
$shortcut.Save()

Write-Host "Startup shortcut created at: $shortcutPath"
Write-Host "Working directory: $projectRoot"
Write-Host "Target: $($stockCmd.Source) serve"

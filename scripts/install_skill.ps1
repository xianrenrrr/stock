# install_skill.ps1 -- install the stock OpenClaw skill manifest

# Resolve project root (one level up from scripts/)
$projectRoot = Split-Path $PSScriptRoot -Parent
$src = Join-Path $projectRoot "openclaw_skill\stock.skill.md"
if (-not (Test-Path $src)) {
    Write-Error "Skill manifest not found at $src"
    exit 1
}

# Destination: OpenClaw's main agent skills folder
$destDir = Join-Path $env:USERPROFILE ".openclaw\agents\main\agent\skills"
if (-not (Test-Path $destDir)) {
    New-Item -ItemType Directory -Force -Path $destDir | Out-Null
}

$dest = Join-Path $destDir "stock.skill.md"
Copy-Item -Path $src -Destination $dest -Force

Write-Host "Installed stock.skill.md to: $dest"
Write-Host "Restart OpenClaw Gateway so the main agent picks up the new skill."

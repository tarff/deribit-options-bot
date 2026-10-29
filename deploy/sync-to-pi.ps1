# Sync project to Raspberry Pi via SCP/SSH
# Run this FROM your Windows machine
#
# Usage: .\deploy\sync-to-pi.ps1 [-PiHost "raspberrypi.local"] [-PiUser "pi"]
# Example: .\deploy\sync-to-pi.ps1 -PiHost "192.168.1.100"

param(
    [string]$PiHost = "raspberrypi.local",
    [string]$PiUser = "pi"
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $ProjectDir) {
    $ProjectDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
}

$RemoteDir = "/home/$PiUser/options-trading-bot"

Write-Host "=== Syncing to Raspberry Pi ===" -ForegroundColor Cyan
Write-Host "From: $ProjectDir"
Write-Host "To:   ${PiUser}@${PiHost}:$RemoteDir"
Write-Host ""

# Files/folders to exclude
$Excludes = @(
    "venv",
    "__pycache__",
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "htmlcov",
    "*.egg-info",
    ".env",
    "data/*.db",
    "logs"
)

# Create remote directory
Write-Host "Creating remote directory..." -ForegroundColor Yellow
ssh "${PiUser}@${PiHost}" "mkdir -p $RemoteDir"

# Build exclude args for scp
# Note: scp doesn't support excludes well, so we use rsync via WSL or copy selectively
# Check if rsync is available (via WSL or Git Bash)

$rsyncPath = $null
if (Get-Command "wsl" -ErrorAction SilentlyContinue) {
    $rsyncPath = "wsl"
}
elseif (Get-Command "rsync" -ErrorAction SilentlyContinue) {
    $rsyncPath = "rsync"
}

$synced = $false

if ($rsyncPath -eq "wsl") {
    # Check if rsync is actually installed in WSL
    $rsyncCheck = wsl which rsync 2>$null
    if ($rsyncCheck) {
        Write-Host "Using rsync via WSL..." -ForegroundColor Yellow

        # Convert Windows path to WSL path
        $WslProjectDir = $ProjectDir -replace '\\', '/' -replace '^([A-Za-z]):', '/mnt/$1'.ToLower()

        $excludeArgs = ($Excludes | ForEach-Object { "--exclude='$_'" }) -join " "

        wsl rsync -avz --progress $excludeArgs "$WslProjectDir/" "${PiUser}@${PiHost}:$RemoteDir/"
        $synced = $true
    }
    else {
        Write-Host "rsync not found in WSL. Install it with:" -ForegroundColor Yellow
        Write-Host "  wsl sudo apt update && wsl sudo apt install -y rsync" -ForegroundColor Cyan
        Write-Host ""
    }
}
elseif ($rsyncPath -eq "rsync") {
    Write-Host "Using rsync..." -ForegroundColor Yellow

    $excludeArgs = $Excludes | ForEach-Object { "--exclude=$_" }
    rsync -avz --progress @excludeArgs "$ProjectDir/" "${PiUser}@${PiHost}:$RemoteDir/"
    $synced = $true
}

if (-not $synced) {
    Write-Host "Using scp (slower, no excludes)..." -ForegroundColor Yellow

    # Selective copy with scp
    $ItemsToCopy = @(
        "src",
        "scripts",
        "config",
        "deploy",
        "requirements.txt",
        "requirements-dev.txt",
        "pyproject.toml",
        "CLAUDE.md"
    )

    foreach ($item in $ItemsToCopy) {
        $localPath = Join-Path $ProjectDir $item
        if (Test-Path $localPath) {
            Write-Host "Copying $item..." -ForegroundColor DarkGray
            scp -r "$localPath" "${PiUser}@${PiHost}:$RemoteDir/"
        }
    }
}

Write-Host ""
Write-Host "=== Sync Complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "SSH to the Pi and run setup:" -ForegroundColor Cyan
Write-Host "  ssh ${PiUser}@${PiHost}"
Write-Host "  cd $RemoteDir"
Write-Host "  chmod +x deploy/pi-setup.sh"
Write-Host "  ./deploy/pi-setup.sh"
Write-Host ""

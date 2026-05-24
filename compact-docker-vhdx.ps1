# compact-docker-vhdx.ps1
# Reclaims slack space from Docker Desktop's WSL2 VHDX.
# REQUIRES: Run as Administrator. Will stop all Docker containers temporarily.
# Target: C:\Users\bryan\AppData\Local\Docker\wsl\disk\docker_data.vhdx (321 GB -> ~20 GB expected)

$ErrorActionPreference = "Stop"

$vhdx = "$env:LOCALAPPDATA\Docker\wsl\disk\docker_data.vhdx"

if (-not (Test-Path $vhdx)) {
    Write-Error "VHDX not found at $vhdx"
    exit 1
}

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltinRole]"Administrator")) {
    Write-Error "Must run as Administrator. Right-click PowerShell -> Run as Administrator."
    exit 1
}

$beforeGB = [math]::Round((Get-Item $vhdx).Length / 1GB, 2)
Write-Host "Before: $beforeGB GB" -ForegroundColor Yellow

Write-Host "[1/4] Stopping Docker Desktop..." -ForegroundColor Cyan
Get-Process "Docker Desktop" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 5

Write-Host "[2/4] Shutting down WSL..." -ForegroundColor Cyan
wsl --shutdown
Start-Sleep -Seconds 10

Write-Host "[3/4] Compacting VHDX (this takes 10-30 minutes for 321 GB)..." -ForegroundColor Cyan
# Try Hyper-V module first
try {
    Import-Module Hyper-V -ErrorAction Stop
    Optimize-VHD -Path $vhdx -Mode Full
    Write-Host "Compacted via Optimize-VHD" -ForegroundColor Green
} catch {
    Write-Host "Hyper-V module unavailable. Falling back to diskpart..." -ForegroundColor Yellow
    $script = @"
select vdisk file="$vhdx"
attach vdisk readonly
compact vdisk
detach vdisk
exit
"@
    $tmp = New-TemporaryFile
    Set-Content -LiteralPath $tmp.FullName -Value $script
    diskpart /s $tmp.FullName
    Remove-Item -LiteralPath $tmp.FullName
}

$afterGB = [math]::Round((Get-Item $vhdx).Length / 1GB, 2)
$freed = [math]::Round($beforeGB - $afterGB, 2)
Write-Host ""
Write-Host "After:  $afterGB GB" -ForegroundColor Green
Write-Host "Freed:  $freed GB" -ForegroundColor Green

Write-Host ""
Write-Host "[4/4] Restart Docker Desktop manually (Start menu)." -ForegroundColor Cyan
Write-Host "Containers with 'restart: unless-stopped' will auto-recover." -ForegroundColor Cyan

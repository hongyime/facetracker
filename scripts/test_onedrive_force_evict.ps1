# Smoke test for the force-eviction logic in onedrive_evict.ps1.
#
# Picks a small OneDrive file, deliberately hydrates it (Read-AllBytes), then
# runs the same attrib+verify+force sequence the daemon uses. Reports timing.
#
# Does NOT touch postgres. Safe to run anytime.
#
# Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\test_onedrive_force_evict.ps1 [-Path "C:\path\to\onedrive\file.jpg"]

param(
    [string]$Path = "",
    [int]$VerifyDelaySeconds = 3
)

$ErrorActionPreference = 'Stop'

function Show-Attrs {
    param([string]$p, [string]$label)
    if (-not (Test-Path -LiteralPath $p)) {
        Write-Host "  [$label] MISSING: $p"; return
    }
    $f = Get-Item -LiteralPath $p -Force
    $isOff = ($f.Attributes -band [IO.FileAttributes]::Offline) -ne 0
    $isRep = ($f.Attributes -band [IO.FileAttributes]::ReparsePoint) -ne 0
    Write-Host "  [$label] Offline=$isOff ReparsePoint=$isRep Length=$($f.Length) Attrs=$($f.Attributes)"
}

# Auto-pick a target if none given: grab a known-OneDrive small PNG/JPG.
if ([string]::IsNullOrEmpty($Path)) {
    $candidates = Get-ChildItem -LiteralPath "C:\Users\bryan\OneDrive" -Recurse -File -Include *.png,*.jpg -ErrorAction SilentlyContinue |
        Where-Object {
            $_.Length -lt 1000000 -and
            (($_.Attributes -band [IO.FileAttributes]::Offline) -ne 0)
        } |
        Select-Object -First 1
    if (-not $candidates) {
        Write-Host "ERROR: no offline OneDrive files found to test against"
        exit 1
    }
    $Path = $candidates.FullName
}

Write-Host "TARGET: $Path"
Write-Host ""
Write-Host "STEP 1: initial state"
Show-Attrs -p $Path -label "before"

Write-Host ""
Write-Host "STEP 2: hydrate by reading 1 byte (forces Files-On-Demand pull)"
$null = [IO.File]::ReadAllBytes($Path) | Select-Object -First 1
Show-Attrs -p $Path -label "after_read"

Write-Host ""
Write-Host "STEP 3: attrib +U -P (async eviction request)"
$attribOut = & attrib +U -P $Path 2>&1
Write-Host "  exit=$LASTEXITCODE out='$attribOut'"
Show-Attrs -p $Path -label "after_attrib"

Write-Host ""
Write-Host "STEP 4: wait $VerifyDelaySeconds s, re-stat"
Start-Sleep -Seconds $VerifyDelaySeconds
Show-Attrs -p $Path -label "after_wait"

$f = Get-Item -LiteralPath $Path -Force
$isOff = ($f.Attributes -band [IO.FileAttributes]::Offline) -ne 0
if ($isOff) {
    Write-Host ""
    Write-Host "RESULT: organic eviction within $VerifyDelaySeconds s  -  no force needed."
    exit 0
}

Write-Host ""
Write-Host "STEP 5: force-set Offline bit directly"
try {
    $f.Attributes = $f.Attributes -bor [IO.FileAttributes]::Offline
    Show-Attrs -p $Path -label "after_force"
    $f2 = Get-Item -LiteralPath $Path -Force
    $stuck = ($f2.Attributes -band [IO.FileAttributes]::Offline) -ne 0
    if ($stuck) {
        Write-Host ""
        Write-Host "RESULT: force_evicted  -  Offline bit stuck."
        exit 0
    } else {
        Write-Host ""
        Write-Host "RESULT: force_attr_did_not_stick  -  bit cleared by something (open handle? pinned? OneDrive disagreed?)"
        exit 1
    }
} catch {
    Write-Host ("STEP 5 EXCEPTION: " + $_.Exception.Message)
    exit 2
}

# OneDrive eviction audit (Windows host).
#
# Companion to onedrive_evict.ps1. Where the eviction script SENDS evict
# signals (attrib +U -P, /freeup-space) and trusts them, this script
# VERIFIES the result some hours later and re-flags any OneDrive-tracked
# rows whose files are still locally cached.
#
# Workflow:
#   1. Pull all images.file_path that look like OneDrive paths AND have
#      onedrive_revert_pending = FALSE (i.e. we previously believed evicted).
#   2. For each: stat the file. If Offline bit is NOT set AND the file
#      still exists, re-flag onedrive_revert_pending = TRUE. The hourly
#      eviction daemon will pick it up next run.
#   3. Skip files that are missing (treat as unrelated to eviction).
#
# Cadence: run every 6 hours via Task Scheduler. Far less aggressive than
# the eviction daemon (hourly) so we don't ping-pong files that OneDrive
# is taking a few hours to evict legitimately.
#
# Why this exists:
#   The eviction daemon's signals (attrib + /freeup-space) are async. The
#   daemon flips pending=FALSE optimistically on signal-sent, which is
#   correct in the steady state but wrong when OneDrive ignores the
#   signal (e.g. file recently modified, sync paused, network issue).
#   This audit catches those stragglers without making the eviction
#   daemon itself re-verify and risk infinite loops.
#
# Idempotent. Safe to interrupt. Does not delete or move data.

param(
    [int]$BatchSize = 2000,
    [int]$MaxRunSeconds = 600,
    [int]$LookbackDays = 30,
    [switch]$DryRun,
    [switch]$Verbose
)

$ErrorActionPreference = 'Stop'
$startedAt = Get-Date
$logFile = Join-Path $PSScriptRoot '..\logs\onedrive_audit.log'
$logDir = Split-Path $logFile -Parent
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Write-Log {
    param([string]$msg)
    $line = "[{0:o}] {1}" -f (Get-Date), $msg
    if ($Verbose) { Write-Host $line }
    Add-Content -LiteralPath $logFile -Value $line
}

Write-Log "started batch_size=$BatchSize lookback_days=$LookbackDays dry_run=$DryRun"

# Audit ALL OneDrive paths where we believe eviction completed. We could
# limit by recency to keep this cheap, but at our scale (~hundreds of
# OneDrive rows) we just scan the lot. Add a recency clause if this gets
# slow. We use the Linux-side path pattern that Indexer stores.
$sql = @"
SELECT id, REPLACE(file_path, '/mnt/c/', 'C:/') AS win_path
FROM images
WHERE onedrive_revert_pending = FALSE
  AND file_path LIKE '/mnt/c/Users/%/OneDrive/%'
ORDER BY id
LIMIT $BatchSize
"@

try {
    $output = & docker exec facetracker-postgres psql -U postgres -d facetracker -t -A -F '|' -c $sql 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Log "psql_query_failed: $output"
        exit 2
    }
} catch {
    Write-Log ("psql_exec_exception: " + $_.Exception.Message)
    exit 2
}

$rows = $output | Where-Object { $_ -and $_ -match '\|' }
$total = ($rows | Measure-Object).Count

if ($total -eq 0) {
    Write-Log "no_rows_to_audit"
    Write-Host "OneDrive audit: nothing to check."
    exit 0
}

Write-Log "auditing=$total"

$stillCached = 0
$verifiedCloud = 0
$missing = 0
$readFailed = 0
$idsToReflag = New-Object System.Collections.Generic.List[int]

foreach ($row in $rows) {
    if (((Get-Date) - $startedAt).TotalSeconds -gt $MaxRunSeconds) {
        Write-Log "max_runtime_hit"
        break
    }

    $parts = $row -split '\|', 2
    if ($parts.Count -ne 2) { continue }
    $id = [int]$parts[0]
    $winPath = $parts[1].Trim() -replace '/', '\'

    if (-not (Test-Path -LiteralPath $winPath)) {
        $missing++
        if ($Verbose) { Write-Log "missing id=$id path='$winPath'" }
        continue
    }

    try {
        $f = Get-Item -LiteralPath $winPath -Force -ErrorAction Stop
        $isOffline = ($f.Attributes -band [IO.FileAttributes]::Offline) -ne 0
        if ($isOffline) {
            $verifiedCloud++
            if ($Verbose) { Write-Log "verified_cloud id=$id path='$winPath'" }
            continue
        }
        # Bytes are still local. Re-flag for the eviction daemon.
        $stillCached++
        $idsToReflag.Add($id)
        if ($Verbose) { Write-Log "still_cached id=$id path='$winPath' size=$($f.Length)" }
    } catch {
        $readFailed++
        Write-Log ("read_failed id=" + $id + " path='" + $winPath + "' err='" + $_.Exception.Message + "'")
    }
}

if ($idsToReflag.Count -gt 0 -and -not $DryRun) {
    $idList = ($idsToReflag -join ',')
    $updateSql = "UPDATE images SET onedrive_revert_pending = TRUE WHERE id IN ($idList);"
    try {
        $upOut = & docker exec facetracker-postgres psql -U postgres -d facetracker -c $updateSql 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Log "reflag_failed: $upOut"
        }
    } catch {
        Write-Log ("reflag_exception: " + $_.Exception.Message)
    }
}

$summary = "audited=$total verified_cloud=$verifiedCloud still_cached=$stillCached missing=$missing read_failed=$readFailed reflagged=$($idsToReflag.Count) elapsed=$([int]((Get-Date) - $startedAt).TotalSeconds)s"
Write-Log "done $summary"
Write-Host "OneDrive audit: $summary"

exit 0

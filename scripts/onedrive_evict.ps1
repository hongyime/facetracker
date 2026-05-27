# OneDrive eviction daemon (Windows host).
#
# Responsibility:
#   1. Poll postgres for images.onedrive_revert_pending = TRUE
#   2. For each path: run `attrib +U` to flag as cloud-only
#   3. On success, flip pending=FALSE in postgres
#
# Runs hourly via Windows Task Scheduler. Designed to be idempotent and
# safe to interrupt at any point — partial work shows up as a still-pending
# row on the next run.
#
# Why this exists:
#   - Reads through Docker Desktop NTFS pass-through DO trigger Files-On-
#     Demand hydration (verified empirically 2026-05-27: 138/283 ingested
#     OneDrive files were locally cached after scan). Without an eviction
#     pass, scanning OneDrive in bulk would balloon C: drive usage.
#   - This daemon closes the loop: container reads file -> hydrates ->
#     processes -> marks pending -> daemon attribs +U -> OneDrive evicts
#     local bytes on next sync -> file goes cloud-only again.
#
# See docs/onedrive-sidecar-plan.md (older "full sidecar" design) for
# context. This script is the lighter middle-ground: keep ingestion
# in-container, just clean up the C: footprint after the fact.

param(
    [int]$BatchSize = 500,
    [int]$MaxRunSeconds = 600,
    [switch]$DryRun,
    [switch]$Verbose
)

$ErrorActionPreference = 'Stop'
$startedAt = Get-Date
$logFile = Join-Path $PSScriptRoot '..\logs\onedrive_evict.log'
$logDir = Split-Path $logFile -Parent
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Write-Log {
    param([string]$msg)
    $line = "[{0:o}] {1}" -f (Get-Date), $msg
    if ($Verbose) { Write-Host $line }
    Add-Content -LiteralPath $logFile -Value $line
}

Write-Log "started batch_size=$BatchSize dry_run=$DryRun"

# Pull pending paths from postgres. Use id-paginated select so we can
# resume after partial failures.
$sql = @"
SELECT id, REPLACE(file_path, '/mnt/c/', 'C:/') AS win_path
FROM images
WHERE onedrive_revert_pending = TRUE
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
    Write-Log "psql_exec_exception: $_"
    exit 2
}

$rows = $output | Where-Object { $_ -and $_ -match '\|' }
$total = ($rows | Measure-Object).Count

if ($total -eq 0) {
    Write-Log "no_pending_rows"
    Write-Host "OneDrive eviction: nothing pending."
    exit 0
}

Write-Log "fetched_pending=$total"

$evicted = 0
$missing = 0
$failed = 0
$alreadyCloud = 0
$idsToFlip = New-Object System.Collections.Generic.List[int]

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
        # File no longer exists on disk — flip pending=false anyway so we
        # don't keep retrying. The DB row may be orphaned but that's a
        # different problem.
        $idsToFlip.Add($id)
        if ($Verbose) { Write-Log "missing id=$id path='$winPath'" }
        continue
    }

    try {
        $i = Get-Item -LiteralPath $winPath -Force -ErrorAction Stop
        $isOffline = ($i.Attributes -band [IO.FileAttributes]::Offline) -ne 0
        if ($isOffline) {
            $alreadyCloud++
            $idsToFlip.Add($id)
            if ($Verbose) { Write-Log "already_cloud id=$id path='$winPath'" }
            continue
        }

        if ($DryRun) {
            if ($Verbose) { Write-Log "dry_run_would_evict id=$id path='$winPath' size=$($i.Length)" }
            continue
        }

        # Run `attrib +U -P` on the path. +U signals OneDrive "evict allowed",
        # -P clears the "always keep on this device" pin if set. Combination
        # is the standard pattern (see Microsoft community "free up space"
        # snippets). attrib has cleaner error semantics than mutating
        # $f.Attributes directly for OneDrive paths.
        #
        # Note: this is async — OneDrive's sync engine evicts the bytes on
        # next pass (minutes to hours). The Offline attribute won't flip
        # immediately. If you need synchronous eviction, see Storage Sense
        # configuration. For our purposes (preventing C: bloat over time),
        # async eviction is fine.
        $attribOut = & attrib +U -P $winPath 2>&1
        if ($LASTEXITCODE -ne 0) {
            $failed++
            Write-Log "attrib_failed id=$id path='$winPath' output='$attribOut'"
            continue
        }
        $evicted++
        $idsToFlip.Add($id)
    } catch {
        $failed++
        Write-Log "exception id=$id path='$winPath' err='$_'"
    }
}

# Bulk flip pending=false for everyone we processed (evicted, missing,
# already_cloud). Note: we deliberately DO NOT flip for $failed rows so
# the next run retries them.
if ($idsToFlip.Count -gt 0 -and -not $DryRun) {
    $idList = ($idsToFlip -join ',')
    $updateSql = "UPDATE images SET onedrive_revert_pending = FALSE WHERE id IN ($idList);"
    try {
        $upOut = & docker exec facetracker-postgres psql -U postgres -d facetracker -c $updateSql 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Log "update_failed: $upOut"
        }
    } catch {
        Write-Log "update_exception: $_"
    }
}

$summary = "evicted=$evicted already_cloud=$alreadyCloud missing=$missing failed=$failed elapsed=$([int]((Get-Date) - $startedAt).TotalSeconds)s"
Write-Log "done $summary"
Write-Host "OneDrive eviction: $summary"

if ($failed -gt 0) { exit 3 }
exit 0

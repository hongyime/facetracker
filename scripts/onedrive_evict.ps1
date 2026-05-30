# OneDrive eviction daemon (Windows host).
#
# Responsibility:
#   1. Poll postgres for images.onedrive_revert_pending = TRUE
#   2. For each path:
#        a. attrib +U -P  (mark "evict allowed", clear pin)
#        b. OneDrive.exe /freeup-space <path>  (ask sync engine to evict NOW)
#   3. Flip pending=FALSE in postgres on signal-sent.
#   4. A separate audit pass (run on a slower cadence) re-flags any rows
#      whose files DIDN'T actually evict, letting this script pick them
#      up again. See onedrive_audit.ps1.
#
# Runs hourly via Windows Task Scheduler. Designed to be idempotent and
# safe to interrupt at any point - partial work shows up as a still-pending
# row on the next run.
#
# Why two signals (attrib + /freeup-space):
#   - attrib +U -P alone is async; OneDrive evicts on its next sync pass
#     (minutes to hours). It's the spec-correct way to say "this file is
#     a candidate for eviction".
#   - /freeup-space additionally pokes the OneDrive sync engine to process
#     this specific path NOW rather than waiting for its next idle pass.
#     Still async (Microsoft does not document a synchronous API), but
#     significantly compresses the eviction window in practice.
#
# What we DON'T do (and why):
#   - We do not set [IO.FileAttributes]::Offline directly. Empirically,
#     the cldflt minifilter silently rejects manual flips of that bit on
#     OneDrive paths (verified 2026-05-27). The setter throws no error
#     but Get-Item immediately after still reports Offline=False. Don't
#     bring it back unless you have a concrete repro that proves it sticks.
#   - We do not verify Offline=True within the same run. OneDrive's sync
#     schedule means many files won't have evicted yet by the time we'd
#     check. Verification belongs in a slower-cadence auditor that won't
#     spam-retry good signals.
#
# Why this exists:
#   - Reads through Docker Desktop NTFS pass-through DO trigger Files-On-
#     Demand hydration (verified empirically 2026-05-27: 138/283 ingested
#     OneDrive files were locally cached after scan). Without an eviction
#     pass, scanning OneDrive in bulk would balloon C: drive usage.
#
# See docs/onedrive-sidecar-plan.md (older "full sidecar" design) for
# context. This script is the lighter middle-ground: keep ingestion
# in-container, just clean up the C: footprint after the fact.

param(
    [int]$BatchSize = 500,
    [int]$MaxRunSeconds = 600,
    [string]$OneDriveExe = 'C:\Program Files\Microsoft OneDrive\OneDrive.exe',
    [switch]$DryRun,
    [switch]$Verbose,
    [switch]$NoFreeupSpace
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
$freedup = 0
$missing = 0
$failed = 0
$alreadyCloud = 0
$idsToFlip = New-Object System.Collections.Generic.List[int]

# Pre-flight check: does the OneDrive client exist? If not, fall back to
# attrib-only mode (legacy behaviour). Don't fail the whole run.
$useFreeupSpace = (-not $NoFreeupSpace) -and (Test-Path -LiteralPath $OneDriveExe)
if ($NoFreeupSpace) {
    Write-Log "freeup_space_disabled_by_flag"
} elseif (-not (Test-Path -LiteralPath $OneDriveExe)) {
    Write-Log "freeup_space_unavailable: $OneDriveExe not found, falling back to attrib-only"
}

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
        # File no longer exists on disk - flip pending=false anyway so we
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

        # Signal 1: attrib +U -P (spec-correct "evict allowed" marker)
        $attribOut = & attrib +U -P $winPath 2>&1
        if ($LASTEXITCODE -ne 0) {
            $failed++
            Write-Log "attrib_failed id=$id path='$winPath' output='$attribOut'"
            continue
        }
        $evicted++

        # Signal 2 (best-effort): /freeup-space tells OneDrive to evict
        # this specific path on its next sync tick rather than waiting
        # for its idle scan. Async; we fire-and-forget.
        if ($useFreeupSpace) {
            try {
                $proc = Start-Process -FilePath $OneDriveExe `
                    -ArgumentList @('/freeup-space', $winPath) `
                    -PassThru -WindowStyle Hidden -ErrorAction Stop
                $freedup++
                if ($Verbose) { Write-Log "freeup_space_spawned id=$id pid=$($proc.Id) path='$winPath'" }
            } catch {
                # Don't roll back attrib success on this; just log and continue.
                Write-Log "freeup_space_spawn_failed id=$id path='$winPath' err='$($_.Exception.Message)'"
            }
        }

        $idsToFlip.Add($id)
    } catch {
        $failed++
        Write-Log ("exception id=" + $id + " path='" + $winPath + "' err='" + $_.Exception.Message + "'")
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

$summary = "evicted=$evicted freedup_space=$freedup already_cloud=$alreadyCloud missing=$missing failed=$failed elapsed=$([int]((Get-Date) - $startedAt).TotalSeconds)s"
Write-Log "done $summary"
Write-Host "OneDrive eviction: $summary"

if ($failed -gt 0) { exit 3 }
exit 0

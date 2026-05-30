# OneDrive orphan REPORT (Windows host).
#
# Scans all DB image rows whose paths look like OneDrive paths, stats
# each path on the filesystem, and reports which DB rows reference files
# that no longer exist. Useful for understanding how stale the index is
# vs. live OneDrive state, and for sizing a future cleanup migration.
#
# READ-ONLY by design. Does not modify postgres or the filesystem.
# Not scheduled by default (run manually or wire into a monthly schtask
# if you want long-term tracking).
#
# Why this exists:
#   The OneDrive eviction auditor (onedrive_audit.ps1) currently spends
#   ~5s per run iterating "missing" paths that will never come back -
#   files moved/deleted in OneDrive after we ingested them. They aren't
#   harmful but they slow the audit and bloat the DB. This script
#   surfaces the size of that pile so we can decide on a cleanup
#   strategy (manual review of clusters, or a migration that adds
#   file_missing=TRUE and skips them in future audits).
#
# Output:
#   - summary line to stdout
#   - optional CSV (-CsvPath) with id,file_path,file_size for review
#
# Idempotent. Safe to interrupt - just rerun.

param(
    [int]$BatchSize = 5000,
    [int]$MaxRunSeconds = 600,
    [string]$CsvPath = "",
    [switch]$Verbose
)

$ErrorActionPreference = 'Stop'
$startedAt = Get-Date
$logFile = Join-Path $PSScriptRoot '..\logs\onedrive_orphans.log'
$logDir = Split-Path $logFile -Parent
if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }

function Write-Log {
    param([string]$msg)
    $line = "[{0:o}] {1}" -f (Get-Date), $msg
    if ($Verbose) { Write-Host $line }
    Add-Content -LiteralPath $logFile -Value $line
}

Write-Log "started batch_size=$BatchSize csv_path='$CsvPath'"

$sql = @"
SELECT id, file_size, REPLACE(file_path, '/mnt/c/', 'C:/') AS win_path
FROM images
WHERE file_path LIKE '/mnt/c/Users/%/OneDrive/%'
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
    Write-Host "No OneDrive rows in DB."
    exit 0
}

Write-Log "scanning=$total"

$present = 0
$missing = 0
$missingBytes = [int64]0
$dirCounts = @{}
$orphans = New-Object System.Collections.Generic.List[object]

foreach ($row in $rows) {
    if (((Get-Date) - $startedAt).TotalSeconds -gt $MaxRunSeconds) {
        Write-Log "max_runtime_hit"
        break
    }

    $parts = $row -split '\|', 3
    if ($parts.Count -ne 3) { continue }
    $id = [int]$parts[0]
    $size = [int64]($parts[1])
    $winPath = $parts[2].Trim() -replace '/', '\'

    if (Test-Path -LiteralPath $winPath) {
        $present++
        continue
    }
    $missing++
    $missingBytes += $size
    $orphans.Add(@{ Id = $id; Size = $size; Path = $winPath })

    # Cluster by parent directory so we can see if this is one bad
    # location vs. scattered.
    $dir = [System.IO.Path]::GetDirectoryName($winPath)
    if ($dirCounts.ContainsKey($dir)) {
        $dirCounts[$dir] = $dirCounts[$dir] + 1
    } else {
        $dirCounts[$dir] = 1
    }
}

# Optional CSV export
if ($CsvPath) {
    $csvDir = [System.IO.Path]::GetDirectoryName($CsvPath)
    if ($csvDir -and -not (Test-Path -LiteralPath $csvDir)) {
        New-Item -ItemType Directory -Path $csvDir -Force | Out-Null
    }
    "id,file_size,file_path" | Set-Content -LiteralPath $CsvPath -Encoding utf8
    foreach ($o in $orphans) {
        $escapedPath = ($o.Path -replace '"', '""')
        "$($o.Id),$($o.Size),`"$escapedPath`"" | Add-Content -LiteralPath $CsvPath -Encoding utf8
    }
    Write-Log "csv_written path='$CsvPath' rows=$($orphans.Count)"
}

# Top-N directory clusters - which folders lost the most files
$topDirs = $dirCounts.GetEnumerator() | Sort-Object -Property Value -Descending | Select-Object -First 10

$missingMb = [math]::Round($missingBytes / 1MB, 1)
$summary = "scanned=$total present=$present missing=$missing missing_size_mb=$missingMb elapsed=$([int]((Get-Date) - $startedAt).TotalSeconds)s"
Write-Log "done $summary"
Write-Host ""
Write-Host "OneDrive orphan report: $summary"
if ($missing -gt 0) {
    Write-Host ""
    Write-Host "Top 10 directories with missing files:"
    foreach ($e in $topDirs) {
        Write-Host ("  {0,5}  {1}" -f $e.Value, $e.Key)
    }
    if ($CsvPath) {
        Write-Host ""
        Write-Host "Detailed list: $CsvPath"
    }
}

exit 0

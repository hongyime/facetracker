# Audit OneDrive ingestion footprint on the local C: drive.
#
# Background: facetracker runs in a Linux container reading OneDrive
# files through Docker Desktop's NTFS bind mount. Empirically those reads
# DO trigger Files-On-Demand hydration — i.e. once the container reads a
# cloud-only file, its bytes get written to local C: cache. (Verified
# 2026-05-27: 138/283 ingested OneDrive files were locally cached.)
#
# Mitigation: scripts/onedrive_evict.ps1 is a Windows-host daemon that
# polls images.onedrive_revert_pending and runs `attrib +U -P` on each
# path so OneDrive evicts the bytes on next sync.
#
# This script is the OBSERVABILITY counterpart — it samples ingested
# OneDrive paths and reports how many bytes are currently on C:. Useful
# to catch eviction-daemon failures before they balloon disk usage.
#
# Args:
#   $args[0]  optional sample size (default 200; -1 = all)
#
# Output: structured key=value lines, plus a non-zero exit code if any of
# the sampled OneDrive-ingested files are now locally cached on disk.
# Wire this into a watcher cron later if you want.
#
# Reads the DB by shelling out to `docker exec facetracker-postgres psql`,
# so the postgres container needs to be up.

param(
    [int]$SampleSize = 200
)

$ErrorActionPreference = 'Stop'

# Pull paths from postgres. We get them in /mnt/c/... form (because that's
# what the scanner stored). Translate to C:\ for Windows path resolution.
Write-Host "Querying postgres for OneDrive-ingested paths..."
$limit = if ($SampleSize -le 0) { '' } else { "LIMIT $SampleSize" }
$sql = "SELECT REPLACE(file_path, '/mnt/c/', 'C:/') FROM images WHERE file_path ILIKE '%onedrive%' ORDER BY id $limit"

$paths = & docker exec facetracker-postgres psql -U postgres -d facetracker -t -A -c $sql 2>$null |
         Where-Object { $_ -and $_.Trim() -ne '' }

if (-not $paths) {
    Write-Host "no_onedrive_files_found=true"
    exit 0
}

Write-Host ("sampled_paths={0}" -f $paths.Count)

$cloudOnly = 0; $cloudMB = 0.0
$local     = 0; $localMB = 0.0
$missing   = 0
$localExamples = New-Object System.Collections.Generic.List[string]

foreach ($p in $paths) {
    if (-not (Test-Path -LiteralPath $p)) { $missing++; continue }
    try {
        $i = Get-Item -LiteralPath $p -Force -ErrorAction Stop
        # Files-On-Demand: a file is truly cloud-only when Offline=True.
        # ReparsePoint=True is set on BOTH cloud-only files AND "always
        # available on this device" files (the latter still has bytes on
        # disk). So checking ReparsePoint alone misclassifies cached
        # files as cloud-only.
        $reparse = ($i.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0
        $offline = ($i.Attributes -band [System.IO.FileAttributes]::Offline) -ne 0
        $mb = $i.Length / 1MB
        if ($offline) {
            # True cloud-only — bytes not on disk.
            $cloudOnly++; $cloudMB += $mb
        } else {
            # Bytes ARE on disk. Could be a hydrated reparse point or a
            # plain file. Either way, this counts toward C: drive bloat.
            $local++; $localMB += $mb
            if ($localExamples.Count -lt 5) { $localExamples.Add($p) }
        }
    } catch {
        $missing++
    }
}

Write-Host ("cloud_only_count={0}" -f $cloudOnly)
Write-Host ("cloud_only_mb={0:N1}"   -f $cloudMB)
Write-Host ("locally_cached_count={0}" -f $local)
Write-Host ("locally_cached_mb={0:N1}" -f $localMB)
Write-Host ("missing_count={0}" -f $missing)

if ($local -gt 0) {
    Write-Host ""
    Write-Host "WARNING: $local OneDrive files have been hydrated to local storage."
    Write-Host "Examples:"
    foreach ($ex in $localExamples) { Write-Host "  $ex" }
    Write-Host ""
    Write-Host "If this is unexpected, run:"
    Write-Host "  powershell -NoProfile -Command `"Get-Item <path> | ForEach-Object { `$_.Attributes = `$_.Attributes -bor [System.IO.FileAttributes]::Offline }`""
    Write-Host "to flag them back as offline. OneDrive will re-evict on next sync."
    exit 1
}

Write-Host ""
Write-Host "OK: all sampled OneDrive files are still cloud-only."
exit 0

# Prune all but the newest N completed snapshots under a backup root.
# Called from scripts/backup_snapshot.bat. Kept as a separate file so we
# don't have to escape pipes/dollar-signs through cmd.exe.
#
# Args:
#   $args[0]  backup root directory (e.g. Y:\facetracker_backups)
#   $args[1]  number of snapshots to keep (e.g. 4)
#
# A "snapshot" is any subdirectory of the root whose name does NOT end in
# `.partial`. Sorted by name (timestamps); oldest beyond keep-N are removed.

param(
    [Parameter(Mandatory=$true)] [string]$Root,
    [Parameter(Mandatory=$true)] [int]$Keep
)

if (-not (Test-Path -LiteralPath $Root -PathType Container)) {
    Write-Host "prune: root not found, nothing to do: $Root"
    exit 0
}

$dirs = Get-ChildItem -LiteralPath $Root -Directory |
        Where-Object { $_.Name -notmatch '\.partial$' } |
        Sort-Object Name

if ($dirs.Count -le $Keep) {
    Write-Host "prune: $($dirs.Count) snapshot(s), keep=$Keep, nothing to delete"
    exit 0
}

$toDelete = $dirs[0..($dirs.Count - $Keep - 1)]
foreach ($d in $toDelete) {
    Remove-Item -LiteralPath $d.FullName -Recurse -Force -ErrorAction Continue
    if ($?) {
        Write-Host "pruned $($d.Name)"
    } else {
        Write-Warning "failed to prune $($d.Name)"
    }
}

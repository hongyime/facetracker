# OneDrive Sidecar — Design Plan

Status: **PLANNED, NOT IMPLEMENTED**
Last updated: 2026-05-27
Author: Bryan + audit session
Estimated effort: 16h (multi-session)

---

## Problem statement

Facetracker runs in a Linux Docker container. OneDrive Files-On-Demand is
a Windows-host-only feature: a "cloud-only" file is a sparse reparse point
(`+U` attribute) that hydrates on read. When the container reads through
the Docker Desktop NTFS bind mount, current empirical behavior (verified
2026-05-27 across 283 ingested OneDrive files) is that hydration is **NOT**
triggered — files stay cloud-only. This is a lucky implementation detail
of Docker Desktop's NTFS pass-through, NOT a guarantee.

Without a real OneDrive integration, two failure modes loom:

1. **Behavior change**: Docker Desktop or OneDrive client updates change
   the read semantics, and a future full scan rips down 200+ GB into local
   cache, blowing C: drive.
2. **Scope creep**: Bryan adds a new scan root that covers a OneDrive
   folder we've never touched (e.g. Pictures, Camera Roll). Even at
   current behavior, *something* triggers hydration somewhere; we don't
   want to find out at 2 AM.

The temporary mitigation in production today is:

- `EXCLUDE_PATHS` includes `/mnt/c/Users/bryan/OneDrive` and
  `/mnt/c/Users/bryan/OneDriveCloudTemp`. Future scans cannot touch them.
- `src/main.py` startup performs a OneDrive safety check that refuses to
  boot if a scan root contains an unexcluded OneDrive directory. Override
  via `FACETRACKER_ALLOW_ONEDRIVE_SCAN=1`.
- `scripts/onedrive_monitor.ps1` (menu option 20) reports footprint;
  exits nonzero if any ingested OneDrive file is locally cached.

This means **OneDrive photos are not currently in facetracker.** That's
fine for now — but it's a feature gap. The sidecar closes it.

---

## Architecture choice (decided)

**Option C: Sidecar as pre-fetcher into Y: staging area.**

Rejected alternatives:
- Option A (sidecar as work producer / push model): two long-running
  processes share state via postgres outbox. Complex, two state machines.
- Option B (sidecar as RPC server / pull model): bytes over loopback
  HTTP. Slow for big videos, retry chaos on timeout.

Why C wins:
- Container never touches OneDrive paths. Future code changes inside
  the container physically cannot hydrate OneDrive — different filesystem.
- Revert to cloud-only happens IMMEDIATELY after copy, deterministically.
  No "we forgot to revert because the container died" path.
- Y: is large (2.4 TB free), local SSD, never dehydrates.
- Failure mode is graceful: sidecar crash mid-batch leaves some files
  staged-but-not-processed; container processes them on next tick;
  retry is safe.

Trade-off: **2x storage during processing** (file in OneDrive cache +
staging copy). Acceptable — files are deleted from staging after
processing, max staging budget is 50 GB (see budget below).

---

## Data flow

```
Hour T+0:00  Sidecar (Windows host, scheduled task)
  - SELECT file_path FROM images WHERE source_type='onedrive'  (already-known)
  - Walk OneDrive paths on Windows host filesystem
  - Diff: find new candidates not in DB (by path)
  - Apply per-run budget cap (1000 files OR 50 GB cumulative, whichever first)
  - For each candidate (in order, smallest first to maximize file count
    under budget):
      a. Copy <onedrive path> -> Y:\onedrive_staging\<sha256>.<ext>
      b. attrib +U "<onedrive path>" (revert to cloud-only IMMEDIATELY)
      c. INSERT INTO images (file_path, original_path, source_type,
         storage_status, status) VALUES
         ('Y:/onedrive_staging/<hash>.<ext>',
          '<original onedrive path>', 'onedrive', 'staging', 'pending')
      d. If insert fails (UNIQUE violation on file_path or original_path),
         delete the staging copy, log, continue.
  - Log run summary: discovered=N, copied=M, reverted=M, errors=E,
    bytes_staged=B, budget_remaining=R

Hour T+0:00..N  Container (already running, picks up via existing scanner)
  - Scanner walks Y:\onedrive_staging\ — already in scan roots
  - Pipeline processes file at file_path, extracts faces, writes embeddings
  - On status='completed', if storage_status='staging':
      - DELETE the staging file from Y:\onedrive_staging\
      - UPDATE images SET storage_status='processed' WHERE id=N
  - Original OneDrive file is already cloud-only (reverted at step 1b)
  - Database row keeps original_path so dashboard shows "C:\Users\bryan\OneDrive\01 PHOTOS\..."

Hour T+1:00  Next sidecar run
  - Repeat. The 1000 already-processed files are now in DB by
    original_path; they don't show up as candidates.
```

---

## Schema migration

```sql
-- Add original_path, source_type, storage_status to images.
-- Backfill existing rows (19,952) so source_type is correct.

ALTER TABLE images
  ADD COLUMN original_path TEXT,
  ADD COLUMN source_type VARCHAR(32) DEFAULT 'local' NOT NULL,
  ADD COLUMN storage_status VARCHAR(32) DEFAULT 'persistent' NOT NULL;

-- Backfill source_type from existing file_path
UPDATE images SET source_type='onedrive'
  WHERE file_path LIKE '%/OneDrive/%' OR file_path LIKE '%/OneDrive - %';

-- For pre-sidecar OneDrive files, original_path == file_path
UPDATE images SET original_path = file_path WHERE source_type = 'onedrive';

-- Index for sidecar diff queries
CREATE INDEX IF NOT EXISTS idx_images_original_path ON images (original_path);
CREATE INDEX IF NOT EXISTS idx_images_source_type ON images (source_type);
CREATE INDEX IF NOT EXISTS idx_images_storage_status ON images (storage_status);

-- UNIQUE on (source_type, original_path) prevents the same OneDrive file
-- being staged twice with different hashes.
CREATE UNIQUE INDEX IF NOT EXISTS uq_images_origin
  ON images (source_type, original_path) WHERE original_path IS NOT NULL;
```

Migration is **non-destructive** — adds columns, fills defaults, indexes.
Run with `docker exec -i facetracker-postgres psql -U postgres -d facetracker < migration.sql`.

---

## Container changes

1. `src/storage/database.py` — add columns to `Image` model:
   - `original_path: Optional[str]`
   - `source_type: str = 'local'`
   - `storage_status: str = 'persistent'`

2. `src/pipeline/processor.py` — after `status='completed'` flip:
   ```python
   if image.storage_status == 'staging':
       try:
           Path(image.file_path).unlink()
           image.storage_status = 'processed'
       except FileNotFoundError:
           pass  # already deleted, idempotent
   ```

3. `src/api/routes/files.py` and dashboard endpoints — return
   `original_path` (when set) as the user-facing path:
   ```python
   "display_path": image.original_path or image.file_path
   ```

4. Add `Y:/onedrive_staging` to `DRIVE_SOURCES` in `.env` so the scanner
   picks up files staged by the sidecar:
   ```
   DRIVE_SOURCES=[..., {"path": "/mnt/y/onedrive_staging", "type": "local"}]
   ```

---

## Sidecar implementation

**Language: PowerShell.** Reasons: native `attrib +U` access, native
unicode path handling, no extra runtime dependency on Windows host.
Python alternative would need pywin32 + harder unicode story.

**Location: `scripts/onedrive_sidecar.ps1`**

**Skeleton:**

```powershell
param(
    [string]$OneDriveRoot = "C:\Users\bryan\OneDrive",
    [string]$StagingDir = "Y:\onedrive_staging",
    [int]$MaxFiles = 1000,
    [long]$MaxBytes = 50GB,
    [string[]]$ExtensionsAllow = @(".jpg",".jpeg",".png",".heic",".mp4",".mov"),
    [switch]$DryRun
)

# 1. Pull known original_paths from postgres
$known = docker exec facetracker-postgres psql -U postgres -d facetracker -t -A -c `
    "SELECT original_path FROM images WHERE source_type='onedrive' AND original_path IS NOT NULL" |
    Where-Object { $_ } | ForEach-Object { $_ -replace "^/mnt/c/", "C:\" -replace "/", "\" }
$knownSet = [System.Collections.Generic.HashSet[string]]::new($known, [System.StringComparer]::OrdinalIgnoreCase)

# 2. Walk OneDrive
$candidates = @()
Get-ChildItem -Path $OneDriveRoot -Recurse -File -ErrorAction SilentlyContinue |
    Where-Object { $ExtensionsAllow -contains $_.Extension.ToLower() } |
    Where-Object { -not $knownSet.Contains($_.FullName) } |
    Sort-Object Length |
    ForEach-Object {
        $candidates += $_
        if ($candidates.Count -ge $MaxFiles) { break }
        if (($candidates | Measure-Object Length -Sum).Sum -ge $MaxBytes) { break }
    }

# 3. Stage each
$staged = 0; $bytes = 0
New-Item -ItemType Directory -Force -Path $StagingDir | Out-Null
foreach ($f in $candidates) {
    if ($DryRun) { Write-Host "[DRY] $($f.FullName) -> stage"; continue }
    $hash = (Get-FileHash $f.FullName -Algorithm SHA256).Hash.ToLower()
    $stagePath = Join-Path $StagingDir "$hash$($f.Extension.ToLower())"
    if (Test-Path $stagePath) { continue }  # already staged

    try {
        # 3a. Copy to staging (this hydrates the OneDrive file briefly)
        Copy-Item $f.FullName $stagePath -ErrorAction Stop
        # 3b. Revert to cloud-only IMMEDIATELY
        attrib +U "$($f.FullName)"
        # 3c. Insert DB row (uses /mnt/c-style path for container compatibility)
        $containerPath = "/mnt/y/onedrive_staging/$hash$($f.Extension.ToLower())"
        $originalPath = $f.FullName -replace "^C:\\", "/mnt/c/" -replace "\\", "/"
        $sql = "INSERT INTO images (file_path, original_path, source_type, storage_status, status, file_hash, file_size, file_mtime) VALUES ('$containerPath', '$originalPath', 'onedrive', 'staging', 'pending', '$hash', $($f.Length), $($f.LastWriteTimeUtc.Subtract([datetime]'1970-01-01').TotalSeconds)) ON CONFLICT DO NOTHING;"
        docker exec facetracker-postgres psql -U postgres -d facetracker -c $sql | Out-Null
        $staged++; $bytes += $f.Length
    } catch {
        Write-Warning "Failed to stage $($f.FullName): $_"
        if (Test-Path $stagePath) { Remove-Item $stagePath -Force }
    }
}

Write-Host "[sidecar] staged=$staged bytes=$bytes budget=$MaxFiles/$MaxBytes"
# Append to log
"$(Get-Date -Format o) staged=$staged bytes=$bytes" |
    Add-Content "$StagingDir\sidecar.log"
```

**SQL injection note:** $originalPath is path data, not user input, but
the inline-string SQL is still bad practice. Production version should
use a small Python helper that uses parameterized SQL via psycopg, OR
write a CSV + `\copy` via heredoc.

---

## Failure recovery

| Failure | Outcome | Recovery |
|---|---|---|
| Sidecar crashes after copy, before `attrib +U` | File hydrated locally on C:, no DB row | Next run sees file is hydrated (read attrib), reverts. Safe if next run is within 24h. |
| Sidecar crashes after `attrib +U`, before INSERT | File reverted, staging copy orphaned | Next run sees no DB row matching staging path, deletes orphan. Need orphan-sweep at start of run. |
| Sidecar crashes after INSERT, before container picks up | DB row points to staging path; staging file exists | Container scanner finds it, processes normally. No special handling. |
| Container crashes mid-process | Row stays `pending`; staging file stays | Recovery (`_recover_pending_images`) handles. Staging file deleted after re-process. |
| Y: drive unmounted | Sidecar refuses to start; pre-flight `Test-Path Y:` | None needed; just don't run. |
| C: hydration triggered by Get-FileHash | Acceptable temporary cost during copy step | `attrib +U` immediately after copy reverts; cost is bounded to one file at a time. |

---

## Per-run budget

- **Files**: 1000 max per run
- **Bytes**: 50 GB max cumulative per run (pre-sort by size to maximize
  file count under cap)
- **Run frequency**: hourly via Windows Task Scheduler
- **Steady-state**: 24,000 files/day, 1.2 TB/day max throughput
- **Backfill**: at 1000 files/hr, 100k OneDrive files = ~100 hours = ~4
  days. Acceptable.
- **Safety floor**: if `Y:\onedrive_staging` exceeds 75 GB (1.5x budget,
  indicates container is not draining), refuse to add more.

---

## Monitoring

`scripts/onedrive_monitor.ps1` already exists for reactive footprint checks.

Add a **proactive sidecar health check**:
- Does `Y:\onedrive_staging\sidecar.log` show a run in the last 90 min?
- If not: alert (menu option, exit nonzero)
- Are there >100 rows with `storage_status='staging'` aged >2 hr?
- If yes: container is not draining; pause sidecar until backlog clears.

Add menu option 21: "OneDrive sidecar status" (run + lag + staging size).

---

## Implementation order (when you have a weekend)

Phase 1 — Foundation (~3h):
1. Run schema migration on a backup, verify queries still work
2. Update `Image` model in `database.py`, recreate api, verify dashboard
   still loads
3. Add `Y:/onedrive_staging` to DRIVE_SOURCES, recreate api, verify
   scanner finds (currently empty) staging dir
4. Add `storage_status='processed'` cleanup to processor.py
5. Add `display_path` to dashboard API
6. Smoke test: manually drop a JPG into `Y:\onedrive_staging\`,
   confirm container picks it up, processes, deletes

Phase 2 — Sidecar (~6h):
7. Write `scripts/onedrive_sidecar.ps1` per skeleton above
8. Replace inline SQL with proper psql-via-stdin or Python helper
9. Add orphan-sweep (delete staging files with no matching DB row)
10. Add safety-floor check (refuse if staging > 75 GB)
11. Test on a small OneDrive subfolder (10 files) end-to-end
12. Test crash recovery: kill sidecar mid-run, verify next run cleans up

Phase 3 — Schedule + observability (~3h):
13. Create Task Scheduler entry: hourly, RU=bryan, /RL LIMITED, Interactive
14. Write monitor: lag detection, staging size, exit codes
15. Add menu option 21 to `facetracker.bat`
16. Add Grafana / Prometheus metrics if you want (optional)

Phase 4 — Backfill + observation (~4h):
17. Run sidecar manually against ONE folder, observe for 24h
18. Verify files revert correctly post-stage
19. Verify container processes them
20. Verify staging dir drains
21. Verify dashboard shows OneDrive paths correctly
22. Expand to full OneDrive root
23. Watch for one full week before declaring done

**DO NOT skip Phase 4.** This system has a real failure mode (rip 200 GB
to local) and we want belt-and-suspenders confidence before unleashing.

---

## When to skip the sidecar

If after a year you've never wanted OneDrive photos in facetracker,
delete this doc. The current EXCLUDE_PATHS guard is sufficient — you've
been living without the feature, no pain, no need to build.

If you start naming identities and notice "wait, where's my college-era
photos? oh right, OneDrive..." then build.

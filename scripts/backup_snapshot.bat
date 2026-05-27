@echo off
REM facetracker weekly backup snapshot.
REM
REM Pure batch + docker exec. No python, no extra dependencies on the host.
REM
REM What it does, in order:
REM   1. Make a timestamped .partial directory under Y:\facetracker_backups
REM   2. pg_dump via `docker exec facetracker-postgres` -> database.sql
REM   3. Copy live FAISS index files from Y:\faces\embeddings\live
REM   4. Copy .env so secrets + index-type setting are recoverable
REM   5. Write manifest.txt with timestamp, git sha, and DB row counts
REM   6. Atomic rename .partial -> final
REM   7. Prune all but newest 4 completed snapshots
REM
REM An interrupted run leaves a .partial directory; subsequent runs
REM ignore .partial dirs for retention purposes.
REM
REM Logs to Y:\facetracker_backups\backup.log.

setlocal enableextensions enabledelayedexpansion

set REPO_DIR=C:\facetracker
set BACKUP_ROOT=Y:\facetracker_backups
set FAISS_LIVE=Y:\faces\embeddings\live
set KEEP=4
set LOG_FILE=%BACKUP_ROOT%\backup.log
set PG_USER=postgres
set PG_DB=facetracker
set PG_CONTAINER=facetracker-postgres

if not exist "%BACKUP_ROOT%" mkdir "%BACKUP_ROOT%"

REM UTC-ish stamp via PowerShell (cmd date/time formats are locale-dependent)
for /f "usebackq delims=" %%T in (`powershell -NoProfile -Command "(Get-Date).ToUniversalTime().ToString('yyyy-MM-dd_HHmmss')"`) do set STAMP=%%T

set PARTIAL_DIR=%BACKUP_ROOT%\%STAMP%.partial
set FINAL_DIR=%BACKUP_ROOT%\%STAMP%

echo ===== %DATE% %TIME% backup starting stamp=%STAMP% ===== >> "%LOG_FILE%"

mkdir "%PARTIAL_DIR%" 2>nul
if not exist "%PARTIAL_DIR%" (
    echo FATAL: cannot create %PARTIAL_DIR% >> "%LOG_FILE%"
    exit /b 2
)
mkdir "%PARTIAL_DIR%\faiss" 2>nul

REM 1. pg_dump via postgres container. Stream stdout to host file.
echo [pg_dump] starting... >> "%LOG_FILE%"
docker exec %PG_CONTAINER% pg_dump -U %PG_USER% -d %PG_DB% --clean --if-exists --no-owner --no-privileges > "%PARTIAL_DIR%\database.sql" 2>> "%LOG_FILE%"
if %ERRORLEVEL% NEQ 0 (
    echo FATAL: pg_dump failed rc=%ERRORLEVEL% >> "%LOG_FILE%"
    exit /b 3
)

REM 2. Copy FAISS files. /Y suppresses prompt.
echo [faiss] copying index files... >> "%LOG_FILE%"
if exist "%FAISS_LIVE%\face_index.faiss"   copy /Y "%FAISS_LIVE%\face_index.faiss"   "%PARTIAL_DIR%\faiss\" >> "%LOG_FILE%" 2>&1
if exist "%FAISS_LIVE%\face_index.ids.npy" copy /Y "%FAISS_LIVE%\face_index.ids.npy" "%PARTIAL_DIR%\faiss\" >> "%LOG_FILE%" 2>&1

REM 3. Copy .env (gitignored, contains secrets + FAISS_INDEX_TYPE etc).
if exist "%REPO_DIR%\.env" copy /Y "%REPO_DIR%\.env" "%PARTIAL_DIR%\.env" >> "%LOG_FILE%" 2>&1

REM 4. Manifest with counts + git sha for forensic verification on restore.
echo [manifest] writing ... >> "%LOG_FILE%"
for /f "usebackq delims=" %%S in (`git -C "%REPO_DIR%" rev-parse HEAD 2^>nul`) do set GIT_SHA=%%S
if not defined GIT_SHA set GIT_SHA=unknown

REM Counts via psql -t -A (tuples-only, unaligned). One docker exec per query keeps logs clean.
REM Note: there is no `videos` table. Video count comes from filtering images by
REM extension/mime-type elsewhere; we don't try to reproduce that here.
for /f "usebackq delims=" %%C in (`docker exec %PG_CONTAINER% psql -U %PG_USER% -d %PG_DB% -t -A -c "SELECT COUNT(*) FROM faces"`)              do set CNT_FACES=%%C
for /f "usebackq delims=" %%C in (`docker exec %PG_CONTAINER% psql -U %PG_USER% -d %PG_DB% -t -A -c "SELECT COUNT(*) FROM images"`)             do set CNT_IMAGES=%%C
for /f "usebackq delims=" %%C in (`docker exec %PG_CONTAINER% psql -U %PG_USER% -d %PG_DB% -t -A -c "SELECT COUNT(*) FROM identities"`)         do set CNT_IDENT=%%C
for /f "usebackq delims=" %%C in (`docker exec %PG_CONTAINER% psql -U %PG_USER% -d %PG_DB% -t -A -c "SELECT COUNT(*) FROM face_identity_map"`)  do set CNT_FIM=%%C

(
    echo created_at_utc=%STAMP%
    echo git_sha=%GIT_SHA%
    echo host=%COMPUTERNAME%
    echo postgres_db=%PG_DB%
    echo counts.faces=%CNT_FACES%
    echo counts.images=%CNT_IMAGES%
    echo counts.identities=%CNT_IDENT%
    echo counts.face_identity_map=%CNT_FIM%
) > "%PARTIAL_DIR%\manifest.txt"

REM 5. Atomic rename .partial -> final. Both dirs are on Y: so this is fast.
ren "%PARTIAL_DIR%" "%STAMP%"
if %ERRORLEVEL% NEQ 0 (
    echo FATAL: could not rename .partial -^> final >> "%LOG_FILE%"
    exit /b 4
)

echo SNAPSHOT OK %FINAL_DIR% faces=%CNT_FACES% identities=%CNT_IDENT% >> "%LOG_FILE%"

REM 6. Prune all but newest %KEEP% completed snapshots. Delegate to the
REM    PowerShell script so we don't have to escape pipes through cmd.
powershell -NoProfile -ExecutionPolicy Bypass -File "%REPO_DIR%\scripts\backup_prune.ps1" -Root "%BACKUP_ROOT%" -Keep %KEEP% >> "%LOG_FILE%" 2>&1

echo ===== %DATE% %TIME% backup OK ===== >> "%LOG_FILE%"
exit /b 0

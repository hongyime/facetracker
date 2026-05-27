@echo off
setlocal EnableDelayedExpansion
title FaceTracker Control Panel

REM Always run relative to this script's directory so double-click works.
cd /d "%~dp0"

:menu
cls
echo ============================================================
echo   FaceTracker Control Panel
echo   %DATE% %TIME%
echo ============================================================
echo.

REM Show current container state at the top so the right action is obvious.
REM `docker ps` returns empty if the container isn't running; fall back to "stopped".
set "API_STATUS=stopped"
set "DB_STATUS=stopped"
set "DASH_STATUS=stopped"
for /f "usebackq delims=" %%S in (`docker ps --filter "name=facetracker-api" --format "{{.Status}}" 2^>nul`) do set "API_STATUS=%%S"
for /f "usebackq delims=" %%S in (`docker ps --filter "name=facetracker-postgres" --format "{{.Status}}" 2^>nul`) do set "DB_STATUS=%%S"
for /f "usebackq delims=" %%S in (`docker ps --filter "name=facetracker-dashboard" --format "{{.Status}}" 2^>nul`) do set "DASH_STATUS=%%S"
echo   api       : !API_STATUS!
echo   postgres  : !DB_STATUS!
echo   dashboard : !DASH_STATUS!
echo.
echo ------------------------------------------------------------
echo   START / STOP
echo ------------------------------------------------------------
echo   1.  Start  (api + postgres, build if needed)
echo   2.  Stop   (graceful, keeps data + outbox + FAISS)
echo   3.  Restart api  (no rebuild)
echo   4.  Rebuild api  (after pulling new code)
echo.
echo ------------------------------------------------------------
echo   STATUS / LOGS
echo ------------------------------------------------------------
echo   5.  Health check (HTTP /health)
echo   6.  Live api logs (Ctrl+C to exit)
echo   7.  Outbox status (pending / merging / committed / failed)
echo   8.  Container resource usage (CPU / memory live)
echo.
echo ------------------------------------------------------------
echo   SAFETY
echo ------------------------------------------------------------
echo   9.  Pause indexer (stop api, keep postgres)
echo  10.  Resume indexer (start api)
echo.
echo ------------------------------------------------------------
echo   DASHBOARD (operations UI on http://localhost:8701)
echo ------------------------------------------------------------
echo  11.  Start dashboard
echo  12.  Stop dashboard
echo  13.  Open dashboard in browser
echo.
echo ------------------------------------------------------------
echo   MAINTENANCE
echo ------------------------------------------------------------
echo  14.  Cluster faces - incremental (assign new faces only, safe)
echo  15.  Cluster faces - dry-run @ 0.6 (preview, no DB writes)
echo  16.  Cluster faces - FULL re-cluster @ 0.6 (destructive, prompts)
echo  17.  FAISS auto-tune nlist (re-train if corpus grew, prompts)
echo  18.  Backup snapshot now (writes to Y:\facetracker_backups)
echo  19.  Show last 20 backup log lines
echo  20.  OneDrive footprint check (verify ingested files still cloud-only)
echo.
echo   0.  Exit
echo.
set /p CHOICE=Enter choice: 

if "%CHOICE%"=="1"  goto start
if "%CHOICE%"=="2"  goto stop
if "%CHOICE%"=="3"  goto restart
if "%CHOICE%"=="4"  goto rebuild
if "%CHOICE%"=="5"  goto health
if "%CHOICE%"=="6"  goto logs
if "%CHOICE%"=="7"  goto outbox
if "%CHOICE%"=="8"  goto stats
if "%CHOICE%"=="9"  goto pause_idx
if "%CHOICE%"=="10" goto resume_idx
if "%CHOICE%"=="11" goto dash_start
if "%CHOICE%"=="12" goto dash_stop
if "%CHOICE%"=="13" goto dash_open
if "%CHOICE%"=="14" goto cluster_inc
if "%CHOICE%"=="15" goto cluster_dry
if "%CHOICE%"=="16" goto cluster_full
if "%CHOICE%"=="17" goto nlist_tune
if "%CHOICE%"=="18" goto backup_now
if "%CHOICE%"=="19" goto backup_log
if "%CHOICE%"=="20" goto onedrive_check
if "%CHOICE%"=="0"  goto end
goto menu


:start
echo.
echo [start] starting facetracker stack...
docker compose up -d --build api
goto pause_return

:stop
echo.
echo [stop] graceful stop (data preserved)...
docker compose stop api postgres
goto pause_return

:restart
echo.
echo [restart] restarting api only (no rebuild)...
docker compose restart api
goto pause_return

:rebuild
echo.
echo [rebuild] rebuilding api image and restarting...
docker compose up -d --build api
goto pause_return

:health
echo.
echo [health] probing http://localhost:5454/health ...
curl -fsS http://localhost:5454/health
echo.
goto pause_return

:logs
echo.
echo [logs] tailing api logs. Press Ctrl+C to return.
docker logs -f --tail 100 facetracker-api
goto pause_return

:outbox
echo.
echo [outbox] querying faiss_outbox status counts...
docker exec facetracker-postgres psql -U postgres -d facetracker -c "SELECT status, COUNT(*) FROM faiss_outbox GROUP BY status ORDER BY status;"
echo.
echo Recent failed rows (if any):
docker exec facetracker-postgres psql -U postgres -d facetracker -c "SELECT face_id, attempts, LEFT(last_error, 80) AS err FROM faiss_outbox WHERE status='failed' ORDER BY claimed_at DESC LIMIT 10;"
goto pause_return

:stats
echo.
echo [stats] live container stats. Press Ctrl+C to return.
docker stats facetracker-api facetracker-postgres
goto pause_return

:pause_idx
echo.
echo [pause] stopping api (postgres + data stay up)...
docker compose stop api
goto pause_return

:resume_idx
echo.
echo [resume] starting api...
docker compose start api
goto pause_return

:dash_start
echo.
echo [dash] starting dashboard (will build first run; takes 2-3 min)...
docker compose up -d dashboard
echo [dash] open http://localhost:8701
goto pause_return

:dash_stop
echo.
echo [dash] stopping dashboard (api + postgres unaffected)...
docker compose stop dashboard
goto pause_return

:dash_open
echo.
echo [dash] opening browser...
start "" "http://localhost:8701"
goto pause_return


:cluster_inc
echo.
echo [cluster] running incremental clustering (assigns NEW faces only)...
echo This is safe and non-destructive. Existing identities are unchanged.
docker exec facetracker-api python -u /app/scripts/cluster_faces.py --mode=incremental --threshold=0.6
goto pause_return

:cluster_dry
echo.
echo [cluster] DRY-RUN at threshold 0.6 (no DB changes)...
docker exec facetracker-api python -u /app/scripts/cluster_faces.py --mode=full --threshold=0.6 --dry-run
goto pause_return

:cluster_full
echo.
echo [cluster] FULL re-cluster at threshold 0.6.
echo WARNING: this DELETES every existing identity + face_identity_map row
echo and rebuilds from scratch. Manual labels (name, is_verified) will be LOST.
echo If you want to keep manual labels, cancel here and use option 14 instead.
echo.
set /p CONFIRM_FULL=Type YES to proceed: 
if /i not "%CONFIRM_FULL%"=="YES" (
    echo Cancelled.
    goto pause_return
)
docker exec facetracker-api python -u /app/scripts/cluster_faces.py --mode=full --threshold=0.6 --confirm
goto pause_return

:nlist_tune
echo.
echo [nlist] checking if FAISS IVF nlist needs adjustment for current corpus size...
echo (DRY RUN first - shows decision without changing anything)
docker exec facetracker-api python -u /app/scripts/faiss_autotune_nlist.py --dry-run
echo.
echo To actually rebuild, the api MUST be stopped first. The script refuses
echo to swap files while the api is up. Stop api manually then run:
echo     docker run --rm --env-file .env --network facetracker-net ^
echo         -v "C:/facetracker:/app" -v "Y:/faces:/app/storage" -w /app ^
echo         facetracker-api python scripts/faiss_autotune_nlist.py --confirm-and-swap
goto pause_return

:backup_now
echo.
echo [backup] running snapshot to Y:\facetracker_backups (keeps newest 4)...
call "%~dp0scripts\backup_snapshot.bat"
goto pause_return

:backup_log
echo.
echo [backup] last 20 lines of Y:\facetracker_backups\backup.log:
if exist "Y:\facetracker_backups\backup.log" (
    powershell -NoProfile -Command "Get-Content 'Y:\facetracker_backups\backup.log' -Tail 20"
) else (
    echo   ^(no log yet - run option 18 at least once^)
)
goto pause_return

:onedrive_check
echo.
echo [onedrive] checking that ingested OneDrive files are still cloud-only...
echo (background: facetracker reads through /mnt/c which does NOT trigger
echo  Files-On-Demand dehydration. This script verifies that's still true.)
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\onedrive_monitor.ps1" -SampleSize -1
goto pause_return


:pause_return
echo.
pause
goto menu

:end
endlocal
exit /b 0

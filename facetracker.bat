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
for /f "usebackq delims=" %%S in (`docker ps --filter "name=facetracker-api" --format "{{.Status}}" 2^>nul`) do set "API_STATUS=%%S"
for /f "usebackq delims=" %%S in (`docker ps --filter "name=facetracker-postgres" --format "{{.Status}}" 2^>nul`) do set "DB_STATUS=%%S"
echo   api      : !API_STATUS!
echo   postgres : !DB_STATUS!
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


:pause_return
echo.
pause
goto menu

:end
endlocal
exit /b 0

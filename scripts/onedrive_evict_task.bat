@echo off
REM Wrapper for the OneDrive eviction daemon. Called hourly by
REM Windows Task Scheduler entry FacetrackerOneDriveEvict.
REM Output redirected to the same log the script appends to.
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\facetracker\scripts\onedrive_evict.ps1" >> "C:\facetracker\logs\onedrive_evict_taskoutput.log" 2>&1

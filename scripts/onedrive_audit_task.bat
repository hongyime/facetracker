@echo off
REM Wrapper for the OneDrive eviction AUDIT pass. Called every 6h by
REM Windows Task Scheduler entry FacetrackerOneDriveAudit.
REM Output redirected to the same log the script appends to.
powershell -NoProfile -ExecutionPolicy Bypass -File "C:\facetracker\scripts\onedrive_audit.ps1" >> "C:\facetracker\logs\onedrive_audit_taskoutput.log" 2>&1

@echo off
REM Windows CMD — launches run.ps1 in PowerShell (do not run run.ps1 with bash)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"
if errorlevel 1 exit /b %errorlevel%

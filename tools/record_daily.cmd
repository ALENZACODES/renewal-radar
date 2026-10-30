@echo off
rem Renewal Radar daily recorder (run by Windows Task Scheduler; safe to run by hand any time).
cd /d "%~dp0.."
set PYTHONPATH=%CD%\backend
set PYTHONUNBUFFERED=1
"%CD%\.venv\Scripts\python.exe" -m renewal.ratewatch.recorder
exit /b %ERRORLEVEL%

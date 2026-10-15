@echo off
setlocal
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" "%~dp0tools\launch_local.py"
) else (
  py -3 "%~dp0tools\launch_local.py"
)
if errorlevel 1 pause

@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
echo Registering lamps 1-100 in local streetlamp.db ...
venv\Scripts\python.exe init_lamps.py
if errorlevel 1 (
  echo FAILED
  pause
  exit /b 1
)
echo OK - local DB updated.
echo For QR on Render: open Render Shell and run: python init_lamps.py
pause

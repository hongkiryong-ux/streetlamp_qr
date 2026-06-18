@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
venv\Scripts\python.exe scripts\build_lamp_codes_csv.py
venv\Scripts\python.exe import_lamps_from_csv.py
pause

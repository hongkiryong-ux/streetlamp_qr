@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
echo Building lamp_codes.csv ...
venv\Scripts\python.exe scripts\build_lamp_codes_csv.py
if errorlevel 1 exit /b 1
echo Generating QR PNG files ...
venv\Scripts\python.exe qr_generate.py
pause

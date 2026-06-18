@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
if not exist ".env.render" (
  echo .env.render not found - copy External Database URL from Render.
  pause
  exit /b 1
)
echo Importing lamp codes from data/lamp_codes.csv to Render PostgreSQL ...
powershell -NoProfile -Command "$env:DATABASE_URL=(Get-Content -LiteralPath '.env.render' -Raw).Trim(); if (-not $env:DATABASE_URL) { Write-Error 'empty .env.render'; exit 1 }; & '.\venv\Scripts\python.exe' 'import_lamps_from_csv.py'; exit $LASTEXITCODE"
if errorlevel 1 (
  echo FAILED
  pause
  exit /b 1
)
echo OK - Render DB updated from CSV.
pause

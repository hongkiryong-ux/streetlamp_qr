@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist "venv\Scripts\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
if not exist ".env.render" (
  echo.
  echo .env.render file not found.
  echo.
  echo 1. Render - streetlamp-db ^(PostgreSQL^) - Connect - External Database URL copy
  echo 2. Create file: .env.render
  echo 3. Paste one line only, example:
  echo    postgresql://user:password@host.render.com/streetlamp
  echo.
  pause
  exit /b 1
)
echo Registering lamps 1-100 on Render PostgreSQL ...
powershell -NoProfile -Command "$env:DATABASE_URL=(Get-Content -LiteralPath '.env.render' -Raw).Trim(); if (-not $env:DATABASE_URL) { Write-Error 'empty .env.render'; exit 1 }; & '.\venv\Scripts\python.exe' 'init_lamps.py'; exit $LASTEXITCODE"
if errorlevel 1 (
  echo FAILED - check .env.render URL and internet
  pause
  exit /b 1
)
echo OK - Render DB updated. Test: https://streetlamp-qr.onrender.com/lamp/1
pause

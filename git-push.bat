@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "GIT=C:\Program Files\Git\bin\git.exe"

if not exist "%GIT%" (
  echo Git을 찾을 수 없습니다: %GIT%
  echo Git 설치 후 Cursor를 재시작하세요.
  pause
  exit /b 1
)

echo === Git 상태 ===
"%GIT%" status -sb
echo.

"%GIT%" config user.name >nul 2>&1
if errorlevel 1 (
  echo [필수] Git 사용자 정보가 없습니다. 아래 두 줄을 터미널에서 먼저 실행하세요:
  echo.
  echo   "C:\Program Files\Git\bin\git.exe" config --global user.name "홍길동"
  echo   "C:\Program Files\Git\bin\git.exe" config --global user.email "github에-쓰는-이메일@example.com"
  echo.
  echo 이름/이메일은 GitHub 계정과 같게 넣으면 됩니다. 설정 후 git-push.bat 을 다시 실행하세요.
  pause
  exit /b 1
)
"%GIT%" config user.email >nul 2>&1
if errorlevel 1 (
  echo [필수] Git 이메일이 없습니다. 위 안내대로 user.email 을 설정하세요.
  pause
  exit /b 1
)

echo === database.py 추가 ===
"%GIT%" add database.py
if errorlevel 1 (
  echo git add 실패
  pause
  exit /b 1
)

echo === 커밋 ===
"%GIT%" commit -m "Fix Render Postgres SSL via asyncpg DSN sslmode=require"
if errorlevel 1 (
  echo 커밋할 변경 없거나 커밋 실패
  pause
  exit /b 1
)

echo === GitHub push ===
"%GIT%" push origin main
if errorlevel 1 (
  echo push 실패 - GitHub 로그인/토큰 확인
  pause
  exit /b 1
)

echo.
echo 완료! Render 대시보드에서 배포 상태를 확인하세요.
pause

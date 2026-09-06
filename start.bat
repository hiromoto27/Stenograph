@echo off
cd /d "%~dp0"
if not exist package.json (
  echo Нужна папка Stenograph с package.json
  pause
  exit /b 1
)
where npm >nul 2>&1
if errorlevel 1 (
  echo Установите Node.js https://nodejs.org
  start https://nodejs.org
  pause
  exit /b 1
)
echo http://127.0.0.1:4173
start http://127.0.0.1:4173
npx --yes serve -l 4173 .

@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Сначала откройте Установить.cmd.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m stenograph
if errorlevel 1 pause

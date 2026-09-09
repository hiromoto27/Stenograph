@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Сначала откройте Установить.cmd.
  pause
  exit /b 1
)
set "PYTHONUTF8=1"
".venv\Scripts\python.exe" "%~dp0scripts\setup_speech.py"
set "STENO_RESULT=%ERRORLEVEL%"
echo.
if not "%STENO_RESULT%"=="0" echo Подготовка не завершена. Скопируйте сообщение выше или сделайте скриншот.
pause
exit /b %STENO_RESULT%

@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"
title СтеноГраф - установка
set "STENO_BOOTSTRAP="
echo СтеноГраф - поиск установленного Python...
for /f "delims=" %%P in ('where python.exe 2^>nul ^| findstr /i /v WindowsApps') do call :try_python "%%P"
for /f "delims=" %%P in ('where python3.exe 2^>nul ^| findstr /i /v WindowsApps') do call :try_python "%%P"
for /f "delims=" %%P in ('where py.exe 2^>nul') do call :try_python "%%P"
for /d %%D in ("%LOCALAPPDATA%\Programs\Python\Python*") do call :try_python "%%~fD\python.exe"
for /d %%D in ("%ProgramFiles%\Python*") do call :try_python "%%~fD\python.exe"
if defined STENO_BOOTSTRAP goto install
echo.
echo Python не удалось запустить. Нужен обычный Python 3.11-3.13 x64.
echo Установите Python 3.12 x64 с python.org и отметьте Add python.exe to PATH.
echo Если Python уже установлен, пришлите файл install.log из этой папки.
>install.log echo Python bootstrap not found.
where python.exe >>install.log 2>&1
where py.exe >>install.log 2>&1
pause
exit /b 1

:install
"%STENO_BOOTSTRAP%" -I "%~dp0scripts\install.py" %*
set "STENO_RESULT=%ERRORLEVEL%"
echo.
if not "%STENO_RESULT%"=="0" echo Сохранён отчёт install.log. Пришлите его, если нужна помощь.
pause
exit /b %STENO_RESULT%

:try_python
if defined STENO_BOOTSTRAP exit /b 0
if not exist "%~1" exit /b 0
"%~1" -I "%~dp0scripts\install.py" --probe >nul 2>&1
if not errorlevel 1 set "STENO_BOOTSTRAP=%~1"
exit /b 0

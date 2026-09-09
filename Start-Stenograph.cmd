@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0Запустить.cmd"
exit /b %ERRORLEVEL%

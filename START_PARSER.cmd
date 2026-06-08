@echo off
setlocal

cd /d "%~dp0"

title Data Parser Service
echo.
echo ===============================================
echo  Data Parser Service
echo ===============================================
echo.
echo Project folder:
echo %CD%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1"

echo.
echo Launcher closed.
echo If there is an error above, copy it or send a screenshot.
echo.
pause

@echo off
setlocal

cd /d "%~dp0"

title Public Data Parser Service
echo.
echo ===============================================
echo  Public Data Parser Service
echo ===============================================
echo.
echo Project folder:
echo %CD%
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_public.ps1"

echo.
echo Public launcher closed.
echo If there is an error above, copy it or send a screenshot.
echo.
pause

@echo off
setlocal

cd /d "%~dp0"

title Install xTunnel
echo.
echo ===============================================
echo  Install xTunnel
echo ===============================================
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_xtunnel.ps1"

echo.
echo Installer closed.
echo If there is an error above, copy it or send a screenshot.
echo.
pause

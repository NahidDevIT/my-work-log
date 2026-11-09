@echo off
rem My Work Log - Windows installer (double-click me). Options: -Yes  -Uninstall
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" %*
echo.
pause

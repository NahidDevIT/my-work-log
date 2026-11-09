@echo off
rem My Work Log - start the dashboard (if it is not running) and open it.
cd /d "%~dp0"
set "PY="
if exist ".python" set /p PY=<".python"
if not defined PY set "PY=python"
netstat -an | find ":8765" | find "LISTENING" >nul || start "" /b "%PY:python.exe=pythonw.exe%" "%~dp0server.py"
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765

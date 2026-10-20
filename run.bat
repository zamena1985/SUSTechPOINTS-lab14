@echo off
chcp 65001 >nul
cd /d "%~dp0"
call "%~dp0tools\findpy.bat" || exit /b 1
set PYTHONUTF8=1
start "" http://127.0.0.1:8081
%PY% main.py
pause

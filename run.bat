@echo off
cd /d "%~dp0"
set PYTHONUTF8=1
start "" http://127.0.0.1:8081
venv\Scripts\python main.py
pause

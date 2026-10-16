@echo off
rem Проверка разметки Infrastructure в настоящей сцене (кадры 64-83).
rem Перед запуском сохраните разметку в браузере (Ctrl+S).
cd /d "%~dp0"
chcp 65001 >nul
venv\Scripts\python tools\infra_check.py --frames 64-83 %*
pause

@echo off
rem Перенос коробок Infrastructure из размеченных кадров в соседние кадры той же серии.
rem Перед запуском сохраните разметку в браузере (Ctrl+S), после - обновите страницу (F5).
cd /d "%~dp0"
chcp 65001 >nul
venv\Scripts\python tools\infra_transfer.py %*
pause

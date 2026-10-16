@echo off
rem Проверка разметки Infrastructure/Pipes/Dust по точкам. Перед запуском сохраните разметку (Ctrl+S).
rem Пример: check.bat --frames 76-78        другая сцена: check.bat --scene data\имя_сцены --frames 1-3
cd /d "%~dp0"
chcp 65001 >nul
call toolsindpy.bat || exit /b 1
%PY% tools\infra_check.py --frames 64-83 %*
pause

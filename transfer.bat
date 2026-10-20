@echo off
rem Перенос коробок Infrastructure/Pipes/Dust из размеченного кадра в соседние кадры серии.
rem Перед запуском сохраните разметку (Ctrl+S), после - обновите страницу (F5).
rem Пример: transfer.bat --frames 76-78 --ref 76
cd /d "%~dp0"
chcp 65001 >nul
call "%~dp0tools\findpy.bat" || exit /b 1
%PY% tools\infra_transfer.py %*
pause

@echo off
rem После правки любого файла в public\js запустите этот файл: он ставит новую версию в адресах скриптов,
rem иначе браузер возьмёт старые файлы из кеша. Потом в браузере - обычный F5.
cd /d "%~dp0"
call "%~dp0tools\findpy.bat" || exit /b 1
%PY% tools\bump_version.py
pause

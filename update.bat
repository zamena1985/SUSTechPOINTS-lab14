@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  Обновление SUSTechPOINTS
echo.
if not exist main.py (
    echo  Рядом с update.bat нет файлов программы.
    echo  Распакуйте архив обновления ПОВЕРХ папки программы ^(туда, где лежит main.py^)
    echo  с заменой файлов и запустите update.bat уже оттуда.
    echo.
    pause
    exit /b 1
)
call tools\findpy.bat || exit /b 1
if "%~1"=="--no-pip" goto done
if exist "python\python.exe" goto done
echo  Проверяю пакеты Python, это может занять минуту...
%PY% -m pip install --quiet --disable-pip-version-check -r requirement.txt
if errorlevel 1 (
    echo.
    echo  Пакеты обновить не удалось. Скорее всего, программа всё равно работает.
    echo  Если нет - README.md, раздел "Если что-то не так".
)
:done
echo.
echo  Готово. Запустите run.bat и один раз нажмите в браузере Ctrl+F5.
echo.
pause

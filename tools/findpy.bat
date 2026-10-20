@echo off
rem Находит Python программы и кладёт путь в переменную PY.
rem Порядок: портативная версия (папка python), затем venv, затем .venv (установка по инструкции куратора).
rem Вызов из других bat-файлов: call "%~dp0tools\findpy.bat" || exit /b 1
if exist "python\python.exe" (set "PY=python\python.exe" & exit /b 0)
if exist "venv\Scripts\python.exe" (set "PY=venv\Scripts\python.exe" & exit /b 0)
if exist ".venv\Scripts\python.exe" (set "PY=.venv\Scripts\python.exe" & exit /b 0)
echo.
echo  Не найден Python программы: рядом нет папки python, venv или .venv.
echo  Как установить - в README.md, раздел "Установка и запуск".
echo.
pause
exit /b 1

@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
set "SELF=%~dp0"
set "URL=https://github.com/zamena1985/SUSTechPOINTS-lab14/releases/latest/download/SUSTechPOINTS-update.zip"
set "TAR=%SystemRoot%\System32\tar.exe"
if not exist "%TAR%" set "TAR=tar"
set "CURL=%SystemRoot%\System32\curl.exe"
if not exist "%CURL%" set "CURL=curl"
echo.
echo  Обновление SUSTechPOINTS
echo.

rem ---------- 1. где установлена программа ----------
set "TARGET="
call :is_program "%SELF%." && set "TARGET=%SELF%."
if not defined TARGET call :find_program
if not defined TARGET (
    echo  Папка программы не найдена автоматически.
    echo  Перетащите папку программы ^(в ней лежат main.py и start.bat^) в это окно и нажмите Enter:
    set /p "TARGET=  > "
)
if not defined TARGET goto :fail_no_target
set "TARGET=!TARGET:"=!"
if "!TARGET:~-1!"=="\" set "TARGET=!TARGET:~0,-1!"
call :is_program "!TARGET!" || goto :fail_no_target
echo  Программа: !TARGET!

rem ---------- 2. откуда брать файлы обновления ----------
set "SRC="
if exist "%SELF%files\main.py" set "SRC=%SELF%files"
if exist "%SELF%main.py" if not exist "%SELF%python\python.exe" if not exist "%SELF%venv\Scripts\python.exe" if not exist "%SELF%.venv\Scripts\python.exe" set "SRC=%SELF%."
if defined SRC (
    echo  Файлы обновления: распакованный пакет рядом с update.bat
) else (
    set "ZIP=%SELF%SUSTechPOINTS-update.zip"
    if exist "!ZIP!" (
        echo  Файлы обновления: архив рядом с update.bat
    ) else (
        set "ZIP=%TEMP%\SUSTechPOINTS-update.zip"
        echo  Скачиваю свежий пакет обновления с GitHub...
        "%CURL%" -L --fail --silent --show-error -o "!ZIP!" "%URL%"
        if errorlevel 1 (
            echo.
            echo  Не удалось скачать. Проверьте интернет или скачайте SUSTechPOINTS-update.zip
            echo  вручную со страницы релизов и положите рядом с update.bat.
            goto :fail
        )
    )
    set "SRC=%TEMP%\SUSTechPOINTS-update"
    if exist "!SRC!" rmdir /s /q "!SRC!"
    mkdir "!SRC!"
    "%TAR%" -xf "!ZIP!" -C "!SRC!"
    if errorlevel 1 (
        echo  Не удалось распаковать архив обновления.
        goto :fail
    )
    if exist "!SRC!\files\main.py" set "SRC=!SRC!\files"
)
if not exist "!SRC!\main.py" (
    echo  В пакете обновления нет файлов программы.
    goto :fail
)

rem ---------- 3. программа должна быть закрыта ----------
netstat -ano 2>nul | findstr /r /c:":8081 .*LISTENING" >nul && (
    echo.
    echo  Похоже, программа сейчас запущена. Закройте её чёрное окно и запустите update.bat снова.
    goto :fail
)

rem ---------- 4. копирование с заменой ----------
echo  Копирую файлы...
robocopy "!SRC!" "!TARGET!" /E /NFL /NDL /NJH /NJS /NP /XF update.bat >nul
if errorlevel 8 (
    echo  Ошибка при копировании файлов.
    goto :fail
)
if exist "!SRC!\update.bat" (
    rem сам update.bat заменяем после завершения, иначе cmd читает уже переписанный файл
    copy /y "!SRC!\update.bat" "!TARGET!\update.bat.new" >nul
)

rem ---------- 5. пакеты Python, только для установок с venv ----------
cd /d "!TARGET!"
if not exist "python\python.exe" (
    call "!TARGET!\tools\findpy.bat" >nul 2>&1 && (
        echo  Проверяю пакеты Python, это может занять минуту...
        !PY! -m pip install --quiet --disable-pip-version-check -r requirement.txt
        if errorlevel 1 echo  Пакеты обновить не удалось. Скорее всего, программа всё равно работает.
    )
)

echo.
echo  Готово. Запустите start.bat ^(или run.bat^) и один раз нажмите в браузере Ctrl+F5.
echo.
if exist "!TARGET!\update.bat.new" start "" /min cmd /c "timeout /t 2 /nobreak >nul & move /y "!TARGET!\update.bat.new" "!TARGET!\update.bat" >nul"
pause
exit /b 0

:fail_no_target
echo.
echo  В указанной папке нет программы SUSTechPOINTS ^(нужны main.py и папка python, venv или .venv^).
:fail
echo.
pause
exit /b 1

rem ---------- папка программы: main.py + встроенный Python или окружение ----------
:is_program
if not exist "%~1\main.py" exit /b 1
if exist "%~1\python\python.exe" exit /b 0
if exist "%~1\venv\Scripts\python.exe" exit /b 0
if exist "%~1\.venv\Scripts\python.exe" exit /b 0
exit /b 1

rem ---------- поиск программы в обычных местах ----------
:find_program
set "FOUND="
set "NFOUND=0"
for %%R in ("%USERPROFILE%\Desktop" "%USERPROFILE%\Downloads" "%USERPROFILE%\Documents" "%USERPROFILE%" "C:" "D:" "E:") do (
    for /d %%D in ("%%~R\SUSTechPOINTS*") do (
        call :is_program "%%~D" && call :add_found "%%~D"
        for /d %%S in ("%%~D\SUSTechPOINTS*") do call :is_program "%%~S" && call :add_found "%%~S"
    )
)
if "!NFOUND!"=="1" set "TARGET=!FOUND1!"
if !NFOUND! GTR 1 (
    echo  Найдено несколько копий программы:
    for /l %%i in (1,1,!NFOUND!) do echo    %%i. !FOUND%%i!
    set /p "CH=  Какую обновить? Введите номер: "
    for /l %%i in (1,1,!NFOUND!) do if "!CH!"=="%%i" set "TARGET=!FOUND%%i!"
)
exit /b 0

:add_found
set /a NFOUND+=1
set "FOUND!NFOUND!=%~1"
exit /b 0

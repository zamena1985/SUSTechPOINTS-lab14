@echo off
chcp 65001 >nul
cd /d "%~dp0"
title SUSTechPOINTS - сервер (это окно не закрывать)
call "%~dp0tools\findpy.bat" || exit /b 1
set PYTHONUTF8=1

rem Сервер уже работает (например, в другом окне)? Второй не нужен: просто открываем браузер.
netstat -ano 2>nul | findstr /r /c:":8081 .*LISTENING" >nul && (
    echo.
    echo  Сервер уже работает в другом окне. Открываю браузер.
    echo  Это окно можно закрыть.
    echo.
    start "" http://127.0.0.1:8081
    pause
    exit /b 0
)

echo.
echo  Запускаю сервер SUSTechPOINTS. Запуск занимает около минуты.
echo  Браузер откроется сам, когда сервер будет готов.
echo.
echo  ЭТО ОКНО НЕ ЗАКРЫВАТЬ: пока оно открыто, программа работает.
echo  Чтобы выключить программу, закройте это окно.
echo.
start "" /min "%~dp0tools\open_when_ready.bat"
%PY% main.py
echo.
echo  Сервер остановился. Если выше есть текст ошибки, сфотографируйте его.
pause

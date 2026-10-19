@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo.
echo  Установка нейросети авто-поворота (TensorFlow) в эту копию SUSTechPOINTS.
echo  Нужна только для авто-поворота техники; для инфраструктуры программа работает и без неё.
echo  Скачивается около 500 МБ, нужен интернет. Ничего в системе не меняется.
echo.
call toolsindpy.bat || exit /b 1
%PY% -m pip install --disable-pip-version-check --no-warn-script-location -c tools\portable_constraints.txt tensorflow==2.12.0
if errorlevel 1 (
    echo.
    echo  Установить не удалось. Проверьте интернет и запустите снова.
    echo  Другой способ: скачать SUSTechPOINTS-tensorflow.zip из релиза и распаковать поверх папки программы.
) else (
    echo.
    echo  Готово. Запустите программу: в чёрном окне появится строка "нейросеть загружена".
)
echo.
pause

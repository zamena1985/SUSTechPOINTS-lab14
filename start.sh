#!/usr/bin/env bash
# SUSTechPOINTS: запуск на Linux. Нужны python3 (3.8 или новее) и интернет при первом запуске.
#   bash start.sh                 - первый запуск создаёт окружение venv-linux и ставит пакеты
#   SUSTECH_NO_BROWSER=1 bash start.sh   - не открывать браузер (для проверок)
# Нейросеть авто-поворота по желанию: venv-linux/bin/pip install tensorflow==2.12.0 (Python 3.8-3.11).
set -u
cd "$(dirname "$(readlink -f "$0")")" || exit 1
VENV="venv-linux"
PORT="$(sed -n 's/.*socket_port *= *\([0-9][0-9]*\).*/\1/p' server.conf 2>/dev/null | head -n1)"
PORT="${PORT:-8081}"

say() { printf '%s\n' "$*"; }
die() { say ""; say "  ОШИБКА: $*"; say ""; exit 1; }

# 1. Python не младше 3.8
PY=""
for c in python3.10 python3.11 python3.12 python3.13 python3.9 python3.8 python3 python; do
    if command -v "$c" >/dev/null 2>&1 && "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' 2>/dev/null; then
        PY="$c"; break
    fi
done
[ -n "$PY" ] || die "не найден python3 версии 3.8 или новее.
  Ubuntu/Debian: sudo apt install python3 python3-venv python3-pip
  Fedora:        sudo dnf install python3
  Arch:          sudo pacman -S python"
say "  Python: $("$PY" --version 2>&1), $(command -v "$PY")"

# 2. Окружение с пакетами (создаётся один раз)
if [ ! -x "$VENV/bin/python" ]; then
    say "  Создаю окружение $VENV ..."
    if ! "$PY" -m venv "$VENV" >/dev/null 2>&1; then
        # Ubuntu/Debian без пакета python3-venv: модуля ensurepip нет, но окружение без pip
        # создаётся, а pip ставим сами, права администратора не нужны
        rm -rf "$VENV"
        "$PY" -m venv --without-pip "$VENV" || die "не удалось создать окружение.
  Ubuntu/Debian: sudo apt install python3-venv python3-pip  и запустите снова"
        say "  pip в системе нет, скачиваю get-pip.py ..."
        curl -fsSL https://bootstrap.pypa.io/get-pip.py -o "$VENV/get-pip.py" \
            || die "не удалось скачать get-pip.py: нет интернета или не установлен curl"
        "$VENV/bin/python" "$VENV/get-pip.py" -q --disable-pip-version-check || die "не удалось установить pip"
    fi
fi
if [ ! -f "$VENV/.packages-ok" ]; then
    say "  Устанавливаю пакеты (один раз, нужен интернет, 1-3 минуты) ..."
    "$VENV/bin/python" -m pip install -q --disable-pip-version-check -r requirement-lite.txt \
        || die "не удалось установить пакеты, смотрите сообщения выше. Нужен интернет."
    touch "$VENV/.packages-ok"
fi
if "$VENV/bin/python" -c 'import tensorflow' >/dev/null 2>&1; then
    say "  нейросеть авто-поворота: есть"
else
    say "  нейросеть авто-поворота: нет, поворот считается по точкам (это нормально)"
fi

# 3. Сервер уже работает? Тогда только открыть браузер
port_busy() {
    "$PY" - "$PORT" <<'EOF'
import socket, sys
s = socket.socket()
s.settimeout(0.5)
sys.exit(0 if s.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
EOF
}
open_browser() {
    [ "${SUSTECH_NO_BROWSER:-}" = "1" ] && return 0
    if command -v xdg-open >/dev/null 2>&1; then
        xdg-open "http://127.0.0.1:$PORT" >/dev/null 2>&1 &
    else
        say "  Откройте в браузере: http://127.0.0.1:$PORT"
    fi
}
if port_busy; then
    say ""
    say "  Сервер уже работает в другом окне (порт $PORT). Открываю браузер."
    open_browser
    exit 0
fi

# 4. Запуск
say ""
say "  Запускаю сервер SUSTechPOINTS. Запуск занимает до минуты."
say "  Браузер откроется сам, когда сервер будет готов: http://127.0.0.1:$PORT"
say ""
say "  ЭТО ОКНО НЕ ЗАКРЫВАТЬ: пока оно открыто, программа работает."
say "  Чтобы выключить программу, нажмите Ctrl+C или закройте окно."
say ""
export PYTHONUTF8=1
mkdir -p temp    # сервер отдаёт папку temp и ругается, если её нет
"$VENV/bin/python" main.py &
SERVER=$!
trap 'kill "$SERVER" 2>/dev/null' INT TERM EXIT
i=0
while [ "$i" -lt 120 ]; do
    if port_busy; then
        say "  Сервер готов: http://127.0.0.1:$PORT"
        open_browser
        break
    fi
    if ! kill -0 "$SERVER" 2>/dev/null; then
        say ""
        say "  Сервер остановился с ошибкой. Смотрите сообщения выше и файл server_error.log."
        exit 1
    fi
    sleep 1
    i=$((i + 1))
done
wait "$SERVER"
say ""
say "  Сервер остановился."

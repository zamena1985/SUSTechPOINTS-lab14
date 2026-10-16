# -*- coding: utf-8 -*-
"""
Сборка пакета обновления dist/SUSTechPOINTS-update.zip.

В пакет входят только файлы программы из репозитория (git ls-files): интерфейс, сервер,
инструменты, bat-файлы, гайд. Не входят: данные (data/), документация авторов (doc/, кроме
PDF гайда), служебные файлы git. Студент распаковывает архив поверх своей папки программы:
его data и окружение Python не затрагиваются.

Запуск из корня проекта:
    venv\\Scripts\\python tools\\make_update.py
"""
import subprocess, zipfile, pathlib, sys, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "dist" / "SUSTechPOINTS-update.zip"

EXCLUDE_DIRS = ("data/", ".github/", "Docker/")
EXCLUDE_FILES = {".gitignore", ".gitattributes", "Dockerfile", ".dockerignore", "README_cn.md", "README_guide.md", "notes.md", "todo.md", "uwsgi.ini"}

def keep(path: str) -> bool:
    if path.startswith(EXCLUDE_DIRS): return False
    if path.startswith("doc/") and path != "doc/guide_ru.pdf": return False
    if path in EXCLUDE_FILES: return False
    return True

files = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", check=True).stdout.split("\n")
files = [f for f in files if f and keep(f) and (ROOT / f).is_file()]

OUT.parent.mkdir(exist_ok=True)
total = 0
with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
    for f in files:
        data = (ROOT / f).read_bytes()
        if f.lower().endswith(".bat"):
            # cmd.exe надёжно работает только с CRLF
            data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
        z.writestr(zipfile.ZipInfo(f, date_time=time.localtime()[:6]), data, compress_type=zipfile.ZIP_DEFLATED)
        total += len(data)

print(f"файлов: {len(files)}, распаковано {total // 1024} КБ, архив {OUT.stat().st_size // 1024} КБ")
print(f"готово: {OUT.relative_to(ROOT)}")

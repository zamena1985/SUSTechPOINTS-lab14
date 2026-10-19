# -*- coding: utf-8 -*-
"""
Сборка дополнения dist/SUSTechPOINTS-tensorflow.zip: пакеты Python, которые есть в полной
портативной сборке (dist/portable/) и отсутствуют в облегчённой (dist/portable-lite/).
Студент распаковывает архив поверх папки SUSTechPOINTS облегчённой версии, и при следующем
запуске программа использует нейросеть авто-поворота.

Перед запуском должны быть собраны обе версии:
    venv\\Scripts\\python tools\\make_portable.py --full
    venv\\Scripts\\python tools\\make_portable.py
Затем:
    venv\\Scripts\\python tools\\make_tf_addon.py
"""
import sys, zipfile, pathlib, time

ROOT = pathlib.Path(__file__).resolve().parent.parent
FULL = ROOT / "dist" / "portable" / "SUSTechPOINTS" / "python" / "Lib" / "site-packages"
LITE = ROOT / "dist" / "portable-lite" / "SUSTechPOINTS" / "python" / "Lib" / "site-packages"
OUT = ROOT / "dist" / "SUSTechPOINTS-tensorflow.zip"


def log(msg): print(time.strftime("%H:%M:%S"), msg, flush=True)


def main():
    for p in (FULL, LITE):
        if not p.is_dir(): sys.exit(f"нет папки {p.relative_to(ROOT)}: сначала соберите обе версии")
    lite_names = {p.name.lower() for p in LITE.iterdir()}
    extra = sorted(p for p in FULL.iterdir() if p.name.lower() not in lite_names)
    if not any(p.name == "tensorflow" for p in extra): sys.exit("в полной сборке нет tensorflow")
    log(f"пакетов только в полной сборке: {len(extra)}")
    if OUT.exists(): OUT.unlink()
    n = size = 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for top in extra:
            files = [top] if top.is_file() else [f for f in top.rglob("*") if f.is_file()]
            for f in files:
                if "__pycache__" in f.parts: continue
                arc = "SUSTechPOINTS/python/Lib/site-packages/" + f.relative_to(FULL).as_posix()
                z.write(f, arc); n += 1; size += f.stat().st_size
    log(f"архив: {OUT.relative_to(ROOT)}, файлов {n}, распаковано {size // 1048576} МБ, сжато {OUT.stat().st_size // 1048576} МБ")
    print("пакеты:", ", ".join(sorted({p.name.split('-')[0] for p in extra if not p.name.endswith('.dist-info')}))[:600])


if __name__ == "__main__":
    main()
